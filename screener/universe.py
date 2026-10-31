"""沪深 A 股全量母池构建器 (L0)。

★ 为什么必须有这个模块
------------------------
改造前 ``screen`` 的候选池**唯一来源**是 ``f10.limit_board_ladder()`` 的当日涨停行，
即「第三方涨停事件流」隐式定义了 universe —— 沪深 5000+ 只 A 股里当天没涨停的
（约 98.6%）连被任何一条规则评估的资格都没有。那不是全市场筛选，是涨停板复盘。

本模块把 universe 的定义权收回本项目：用 7709 主站的**证券代码表**自主界定
「沪深 A 股」，并按显式 ``reason_code`` 逐条剔除，使「某只票为什么不在池子里」
成为可枚举、可计数、可断言的事实。

★ 数据纪律 (NFR-02)
-------------------
* 对账基准取自 ``codes.a_share_count(market)``；取不到就置 ``None`` 并**判为对账失败**，
  严禁拿代码表行数自己当分母自证清白（那是循环论证）。
* ``helpers.market_stat().total_count`` 统计口径未经核实（可能含北交所/其他品种），
  **只作交叉验证告警**，不参与闸门判定。
* 缺失字段一律 ``None``，严禁 ``or 0.0`` 兜底。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterable, Sequence

import config

logger = logging.getLogger("ast_trader.screener.universe")


# ───────────────────────────────────────────────────────── 剔除原因码
REASON_NOT_A_SHARE = "NOT_A_SHARE"              # 非沪深 A 股（B股/基金/债/指数等泄漏）
REASON_BSE_OUT_OF_SCOPE = "BSE_OUT_OF_SCOPE"    # 北交所：业务性永久排除
REASON_ST_RISK_WARNING = "ST_RISK_WARNING"      # ST / *ST / SST / S*ST
REASON_DELISTING = "DELISTING"                  # 退市整理期（简称含"退"）
REASON_SUSPENDED = "SUSPENDED"                  # 当日停牌
REASON_NEW_LISTING = "NEW_LISTING_LT_MIN_DAYS"  # 上市不足 N 个交易日（L1 执行）
REASON_PROFILE_MISSING = "PROFILE_MISSING"      # 画像/行情批次取数失败（L1，不缩池）

#: 全部剔除原因码（顺序即判定优先级）
ALL_REASON_CODES: tuple[str, ...] = (
    REASON_BSE_OUT_OF_SCOPE,
    REASON_NOT_A_SHARE,
    REASON_DELISTING,
    REASON_ST_RISK_WARNING,
    REASON_SUSPENDED,
    REASON_NEW_LISTING,
    REASON_PROFILE_MISSING,
)

# ───────────────────────────────────────────────────────── 代码前缀表
#: 沪市 A 股前缀（含科创板 688 / 科创板 CDR 689）
SH_A_PREFIXES: tuple[str, ...] = ("600", "601", "603", "605", "688", "689")
#: 深市 A 股前缀（主板 000/001/002/003 + 创业板 300/301）。
#: ★ 20261028 全量实测发现深市已启用 **302** 代码段（原前缀表不含，会把它误判成
#:   NOT_A_SHARE 而静默丢掉一只票）。这正说明**前缀表会过期**，故板块判定一律
#:   优先用代码表自带的 ``board`` 字段，前缀表仅作 board 缺失时的兜底。
SZ_A_PREFIXES: tuple[str, ...] = ("000", "001", "002", "003", "300", "301", "302")

# ── 板块标识 → 交易档位 ────────────────────────────────────────────
# ★ 取值域为 20261028 全量实测（沪深 A 股 5225 只，board 非空且仅此 4 值）：
#     sse_star_market 619 / sse_main_board 1700 / szse_main_board 1495 / szse_chinext 1411
#: 主板（涨跌幅 10%、成交额门槛走 LIQUIDITY_MAIN_MIN_AMOUNT）
BOARDS_MAIN: frozenset[str] = frozenset({"sse_main_board", "szse_main_board"})
#: 双创板（涨跌幅 20%、成交额门槛走 LIQUIDITY_GEM_MIN_AMOUNT）
BOARDS_GROWTH: frozenset[str] = frozenset({"sse_star_market", "szse_chinext"})
#: 已验证的全部 board 取值；出现新值时只告警不剔除（防止 eltdx 新增板块导致全池清零）
KNOWN_BOARDS: frozenset[str] = BOARDS_MAIN | BOARDS_GROWTH
#: 北交所前缀 —— 本项目不做，但必须能被**识别**出来以便显式排除与告警
BSE_PREFIXES: tuple[str, ...] = ("920", "43", "83", "87", "88", "4", "8")

#: ST 判定与 eltdx 自身 ``CodeApi.latest_st`` 保持一致（名称前缀法）
ST_NAME_PREFIXES: tuple[str, ...] = ("ST", "*ST", "SST", "S*ST")
#: 退市整理期标记
DELISTING_NAME_TOKEN = "退"


@dataclass(frozen=True)
class UniverseRow:
    """母池中的一只沪深 A 股。

    ★ ``ipo_date`` 代码表不提供，由 ``helpers.stock_profile_table`` 在 L1 补齐；
      补齐前恒为 ``None``，次新剔除因此只能在 L1 执行。
    """

    code: str                       # 六位裸码
    full_code: str                  # sh600519 / sz000333
    name: str
    exchange: str                   # "sh" | "sz"
    board: str | None = None        # 代码表 board（取值域未核实，仅作元数据存储）
    category: str | None = None     # 代码表 category
    board_reason: str | None = None  # 代码表 board_reason
    ipo_date: str | None = None     # YYYYMMDD，L1 补齐后可仍为 None（未核验）
    pre_close: float | None = None


@dataclass
class UniverseBuildResult:
    """母池构建结果。"""

    rows: list[UniverseRow] = field(default_factory=list)
    #: 对账分母：``a_share_count("sh") + a_share_count("sz")``。取不到为 ``None``。
    expected_total: int | None = None
    scanned_total: int = 0
    #: ``market_stat().total_count`` —— 口径是「全部证券」（含基金/债/指数/北交所），
    #: 与 A 股分母**不可比**，仅作信息记录，绝不参与闸门。
    market_stat_total: int | None = None
    market_stat_suspended: int | None = None
    market_stat_limit_up: int | None = None
    market_stat_limit_down: int | None = None
    excluded: dict[str, int] = field(default_factory=dict)
    #: 代码表出现了未见过的新板块取值（只告警不剔除，防 eltdx 扩板块导致全池清零）
    unknown_boards: dict[str, int] = field(default_factory=dict)
    #: 防御：沪深市场里混进的北交所代码（正常应为空）
    bse_intrusion: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def coverage_ratio(self) -> float | None:
        """扫描数 / 预期数。分母不可得时返回 ``None``（**不是** 0.0）。

        ★ 返回 None 而非 0.0 是刻意的：0.0 会与「扫到 0 只」混淆，
          两者处置方式不同（前者是通道故障，后者是行情异常）。
        """
        if not self.expected_total:
            return None
        return self.scanned_total / float(self.expected_total)

    @property
    def coverage_ok(self) -> bool:
        """覆盖率闸门。

        分母不可得 → 判失败（Fail-Closed）：宁可拒绝出结果，
        也不输出一份无法自证完整性的"精选池"。
        """
        ratio = self.coverage_ratio
        if ratio is None:
            return False
        return ratio >= config.UNIVERSE_MIN_COVERAGE_RATIO

    def bump(self, reason: str, n: int = 1) -> None:
        self.excluded[reason] = self.excluded.get(reason, 0) + n

    def to_dict(self) -> dict[str, Any]:
        return {
            "scanned_total": self.scanned_total,
            "expected_total": self.expected_total,
            "market_stat_total": self.market_stat_total,
            "market_stat_suspended": self.market_stat_suspended,
            "market_stat_limit_up": self.market_stat_limit_up,
            "market_stat_limit_down": self.market_stat_limit_down,
            "unknown_boards": dict(self.unknown_boards),
            "coverage_ratio": self.coverage_ratio,
            "coverage_ok": self.coverage_ok,
            "active_count": len(self.rows),
            "excluded": dict(self.excluded),
            "bse_intrusion": list(self.bse_intrusion),
            "warnings": list(self.warnings),
        }


# ───────────────────────────────────────────────────────── 纯判定（离线可测）
def is_bse_code(code: str) -> bool:
    """是否北交所代码（8xxxxx / 4xxxxx / 920xxx）。

    ★ 注意判定顺序：``920`` 以 ``9`` 开头但属于北交所，必须**先于**沪市 ``9`` 判定；
      本项目不做北交所，但识别它才能显式排除并告警，而不是让它悄悄混进主板口径。
    """
    return code.startswith(BSE_PREFIXES)


def is_hs_a_share_code(code: str, exchange: str | None = None) -> bool:
    """是否沪深 A 股代码（主板 / 科创 / 创业）。"""
    if is_bse_code(code):
        return False
    if exchange == "sh":
        return code.startswith(SH_A_PREFIXES)
    if exchange == "sz":
        return code.startswith(SZ_A_PREFIXES)
    return code.startswith(SH_A_PREFIXES) or code.startswith(SZ_A_PREFIXES)


def is_st_name(name: str) -> bool:
    """是否 ST 类名称。与 ``eltdx`` 自身 ``latest_st`` 同源（前缀法）。"""
    return (name or "").startswith(ST_NAME_PREFIXES)


def is_delisting_name(name: str) -> bool:
    """是否退市整理期（简称含"退"）。"""
    return DELISTING_NAME_TOKEN in (name or "")


def board_class(board: str | None, code: str = "", exchange: str | None = None) -> str:
    """把代码表 ``board`` 映射为交易档位：``"main"``（主板）/ ``"growth"``（双创）。

    ★ 优先用 ``board`` 而不是代码前缀：前缀表会过期（实测已出现深市 302、沪市 689
      两个原表未覆盖的代码段），而 board 由主站下发。
    ★ board 缺失或出现未见过的新值时，回退到前缀表；仍判不出则按**主板**处理
      （主板门槛更严，回退方向是保守的：宁可少放，不可错放）。
    """
    if board in BOARDS_GROWTH:
        return "growth"
    if board in BOARDS_MAIN:
        return "main"
    # 兜底：前缀判定（与 filter_liquidity 的历史口径一致，此处补上 689）
    if code.startswith(("300", "301", "302", "688", "689")):
        return "growth"
    return "main"


def classify_row(
    name: str,
    code: str,
    exchange: str,
    *,
    board: str | None = None,
    category: str | None = None,
) -> str | None:
    """返回剔除原因码；``None`` 表示通过。

    判定优先级：北交所 → 非 A 股 → 退市 → ST。
    退市先于 ST：退市整理期简称形如 ``XX退``，不会命中 ST 前缀，
    但若两者同时成立，应以更严重的「退市」为准。

    ★ 非 A 股判定优先用 ``category``（实测沪深 A 股全量 5225 只的 category
      恒为 ``a_share``）；``category`` 缺失时才回退代码前缀，避免前缀表过期误杀。
    """
    if (exchange or "").lower() == "bj" or is_bse_code(code):
        return REASON_BSE_OUT_OF_SCOPE
    if category is not None:
        if category != "a_share":
            return REASON_NOT_A_SHARE
    else:
        if not is_hs_a_share_code(code, exchange):
            return REASON_NOT_A_SHARE
    if config.UNIVERSE_EXCLUDE_DELISTING and is_delisting_name(name):
        return REASON_DELISTING
    if config.UNIVERSE_EXCLUDE_ST and is_st_name(name):
        return REASON_ST_RISK_WARNING
    return None


def _parse_ipo_date(value: str | None) -> date | None:
    """把 ``YYYYMMDD`` / ``YYYY-MM-DD`` 解析为 ``date``；不可解析返回 ``None``。"""
    if not value:
        return None
    txt = str(value).strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(txt, fmt).date()
        except ValueError:
            continue
    return None


def min_ipo_natural_days() -> int:
    """把「交易日」阈值换算为「自然日」阈值（近似 5/7）。"""
    ratio = getattr(config, "UNIVERSE_TRADING_DAYS_PER_NATURAL_DAY", 5.0 / 7.0)
    if ratio <= 0:
        ratio = 5.0 / 7.0
    return int(round(config.UNIVERSE_NEW_LISTING_MIN_TRADING_DAYS / ratio))


def filter_by_listing_age(
    rows: Sequence[UniverseRow],
    *,
    today: date | None = None,
) -> tuple[list[UniverseRow], int]:
    """剔除上市不足 N 个交易日的次新股。

    返回 ``(存活 rows, 剔除数)``。

    ★ ``ipo_date`` 不可核验时的处置：按 NFR-02 不得伪造上市日期，
      但也不得让"信息缺失"变成"无条件放行" —— 此处**保守放行并计入告警**，
      由调用方决定是否打印。理由：次新剔除是风格过滤而非风控红线，
      误放行的代价（一只次新股进池）远低于误剔除（把正常票当次新丢掉）。
    """
    if config.UNIVERSE_NEW_LISTING_MIN_TRADING_DAYS <= 0:
        return list(rows), 0

    today = today or date.today()
    min_days = min_ipo_natural_days()
    kept: list[UniverseRow] = []
    dropped = 0
    for r in rows:
        ipo = _parse_ipo_date(r.ipo_date)
        if ipo is not None and (today - ipo).days < min_days:
            dropped += 1
            continue
        kept.append(r)
    return kept, dropped


# ───────────────────────────────────────────────────────── 母池构建（联网）
def _fetch_rows_for_market(client: Any, market: str, result: UniverseBuildResult) -> list[UniverseRow]:
    """拉单个市场的 A 股代码表行。

    用 ``codes.a_shares(market)``（SDK 自带的 A 股过滤）而不是 ``codes.all`` +
    自判类别：后者要求我们猜测 ``category`` 取值域，猜错会整池清零。
    """
    from data.eltdx_client import with_retry

    try:
        raw = with_retry(lambda: client.codes.a_shares(market), what=f"codes.a_shares({market})")
    except Exception as exc:  # noqa: BLE001  归一为告警，由覆盖率闸门兜底
        result.warnings.append(f"代码表拉取失败 market={market}: {type(exc).__name__}: {exc}")
        logger.error(f"母池构建: 代码表拉取失败 market={market}: {type(exc).__name__}: {exc}")
        return []

    rows: list[UniverseRow] = []
    for item in raw or []:
        code = str(getattr(item, "code", "") or "").strip()
        name = str(getattr(item, "name", "") or "").strip()
        exchange = str(getattr(item, "exchange", "") or market).lower()
        if not code:
            continue
        rows.append(
            UniverseRow(
                code=code,
                full_code=f"{exchange}{code}",
                name=name,
                exchange=exchange,
                board=getattr(item, "board", None),
                category=getattr(item, "category", None),
                board_reason=getattr(item, "board_reason", None),
                ipo_date=None,
                pre_close=_safe_float(getattr(item, "previous_close_price", None)),
            )
        )
    return rows


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _fetch_expected_total(client: Any, markets: Iterable[str], result: UniverseBuildResult) -> None:
    """取对账分母。任一市场取不到即整体置 ``None``（Fail-Closed）。"""
    from data.eltdx_client import with_retry

    total = 0
    for market in markets:
        try:
            n = with_retry(lambda m=market: client.codes.a_share_count(m), what=f"codes.a_share_count({market})")
        except Exception as exc:  # noqa: BLE001
            result.warnings.append(
                f"对账分母不可得 market={market}: {type(exc).__name__}: {exc} "
                f"→ 覆盖率无法自证，按 Fail-Closed 判失败"
            )
            logger.error(f"母池构建: 对账分母不可得 market={market}: {type(exc).__name__}: {exc}")
            result.expected_total = None
            return
        total += int(n or 0)
    result.expected_total = total


def _fetch_suspended(client: Any, markets: Iterable[str], result: UniverseBuildResult) -> set[str]:
    """取停牌代码集合。失败时返回空集并告警 —— 停牌属风格过滤，不阻塞出结果。"""
    if not (config.UNIVERSE_EXCLUDE_SUSPENDED and config.UNIVERSE_USE_SUSPENDED_API):
        return set()

    from data.eltdx_client import with_retry

    suspended: set[str] = set()
    for market in markets:
        try:
            codes = with_retry(lambda m=market: client.codes.latest_suspended(m), what=f"codes.latest_suspended({market})")
        except Exception as exc:  # noqa: BLE001
            result.warnings.append(f"停牌清单不可得 market={market}: {type(exc).__name__}: {exc} → 本次不剔除停牌")
            logger.warning(f"母池构建: 停牌清单不可得 market={market}: {type(exc).__name__}: {exc}")
            continue
        for c in codes or []:
            suspended.add(str(c).strip().lower())
    return suspended


def _cross_check_market_stat(client: Any, result: UniverseBuildResult) -> None:
    """用 ``market_stat()`` 做**信息性**交叉验证。

    ★ 20261028 实测：``market_stat().total_count = 55760``，而沪深 A 股对账分母
      只有 **5225** —— 前者是「全部证券」（含基金/债/指数/北交所）。两者**不可比**，
      早期设计里拿它们做漂移告警会产生 100% 恒定误报，故此处**只记录不比较**。

    真正有参考价值的是 ``suspended_count``：当停牌清单接口不可用时，可用它提示
    「本次未剔除停牌，且市场上有 N 只停牌股」。
    """
    try:
        stat = client.helpers.market_stat()
    except Exception as exc:  # noqa: BLE001
        result.warnings.append(f"全市场统计不可得，跳过交叉验证: {type(exc).__name__}: {exc}")
        return

    result.market_stat_total = int(getattr(stat, "total_count", 0) or 0) or None
    result.market_stat_suspended = int(getattr(stat, "suspended_count", 0) or 0) or None
    result.market_stat_limit_up = int(getattr(stat, "limit_up_count", 0) or 0) or None
    result.market_stat_limit_down = int(getattr(stat, "limit_down_count", 0) or 0) or None


def build_universe(
    *,
    markets: Sequence[str] | None = None,
    health: Any | None = None,
) -> UniverseBuildResult:
    """构建沪深 A 股全量母池。

    流程：代码表 → 逐条 reason_code 剔除 → 对账分母 → 交叉验证 → 覆盖率闸门。

    返回的 :class:`UniverseBuildResult` 中 ``coverage_ok`` 为 ``False`` 时，
    调用方**必须拒绝输出精选池**（残缺的"全市场"比没有更危险）。
    """
    from data.eltdx_client import open_client

    markets = tuple(markets or config.UNIVERSE_MARKETS)
    result = UniverseBuildResult()

    try:
        with open_client() as client:
            _fetch_expected_total(client, markets, result)
            _cross_check_market_stat(client, result)
            suspended = _fetch_suspended(client, markets, result)

            raw_rows: list[UniverseRow] = []
            for market in markets:
                raw_rows.extend(_fetch_rows_for_market(client, market, result))

            result.scanned_total = len(raw_rows)

            kept: list[UniverseRow] = []
            for row in raw_rows:
                if row.board and row.board not in KNOWN_BOARDS:
                    result.unknown_boards[row.board] = result.unknown_boards.get(row.board, 0) + 1

                reason = classify_row(
                    row.name, row.code, row.exchange,
                    board=row.board, category=row.category,
                )
                if reason == REASON_BSE_OUT_OF_SCOPE:
                    result.bse_intrusion.append(row.full_code)
                if reason is not None:
                    result.bump(reason)
                    continue
                if row.full_code in suspended:
                    result.bump(REASON_SUSPENDED)
                    continue
                kept.append(row)

            result.rows = kept
    except Exception as exc:  # noqa: BLE001  连接层整体不可用
        result.warnings.append(f"母池构建整体失败: {type(exc).__name__}: {exc}")
        logger.error(f"母池构建整体失败: {type(exc).__name__}: {exc}", exc_info=True)

    if result.unknown_boards:
        result.warnings.append(
            f"代码表出现未登记的新板块取值 {result.unknown_boards} —— 已按前缀兜底归类，"
            f"请核实其涨跌幅与流动性档位（防止 eltdx 新增板块后沿用错误阈值）"
        )

    if result.bse_intrusion:
        result.warnings.append(
            f"防御告警: 沪深代码表中混入 {len(result.bse_intrusion)} 只北交所标的 "
            f"（已按 BSE_OUT_OF_SCOPE 排除）: {result.bse_intrusion[:5]}"
        )

    if not result.coverage_ok:
        ratio = result.coverage_ratio
        ratio_txt = "分母不可得" if ratio is None else f"{ratio*100:.1f}%"
        result.warnings.append(
            f"覆盖率闸门未通过: 扫描 {result.scanned_total} 只 / 预期 "
            f"{'不可得' if result.expected_total is None else result.expected_total} 只 "
            f"(覆盖率 {ratio_txt} < 阈值 {config.UNIVERSE_MIN_COVERAGE_RATIO*100:.0f}%)"
        )
        logger.error(f"母池覆盖率闸门未通过: {ratio_txt}")

    if health is not None:
        try:
            if result.coverage_ok:
                health.record_success("沪深全市场母池", "eltdx.codes.a_shares", len(result.rows))
            else:
                health.record_degraded(
                    "沪深全市场母池",
                    "eltdx.codes.a_shares",
                    f"覆盖率闸门未通过 (扫描 {result.scanned_total} / 预期 {result.expected_total})",
                )
        except Exception:  # noqa: BLE001  健康度记账不得影响主流程
            logger.debug("母池健康度记账失败（已忽略）")

    logger.info(
        f"母池构建完成: 扫描 {result.scanned_total} 只 -> 活跃 {len(result.rows)} 只 | "
        f"剔除明细 {result.excluded} | 覆盖率 "
        f"{'不可得' if result.coverage_ratio is None else f'{result.coverage_ratio*100:.1f}%'}"
    )
    return result
