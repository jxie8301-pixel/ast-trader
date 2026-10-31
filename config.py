"""Global configuration for AST-Trader."""
from __future__ import annotations

import os
from pathlib import Path

# ─── .env 加载 ────────────────────────────────────────────────────
# 手写而不引入 python-dotenv：只为一个文件拉一个依赖不划算，
# 且必须保证**真实环境变量优先级更高**（CI / 生产注入不能被 .env 覆盖），
# 所以用 setdefault 而非直接赋值。
def _load_dotenv() -> None:
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.is_file():
        return
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    except Exception:                                       # noqa: BLE001
        pass                     # .env 读不动就当没有，绝不因此让系统起不来


_load_dotenv()

# ─── Tushare Pro 官方数据通道 ───────────────────────────────────────
TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "").strip()

# ─── AI 协处理器（判断层）──────────────────────────────────────────
# ★ Key 严禁硬编码，一律走环境变量；.env 不得入库。
# ★ AI_ENABLED 默认关闭：保证 166→N 项测试完全确定性，且无网时主流程照常。
AI_ENABLED = os.getenv("AST_AI_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")
AI_API_BASE = os.getenv("AST_AI_API_BASE", "https://token.vip.cpolar.cn/v1")
AI_API_KEY = os.getenv("AST_AI_API_KEY", "")
AI_MODEL = os.getenv("AST_AI_MODEL", "deepseek-v4.1-flash")
# ─── 超时总纲（★ 唯一真值源 —— 禁止在别处写死任何超时数值）────────────
# 调整超时只需改这两个值：下方所有场景常量与各调用处均由它们派生。
TIMEOUT_AI = 60.0        # AI 分析接口：prompt 长且需输出推导，实测 8/25/30s 均不足
TIMEOUT_DEFAULT = 30.0   # 其它所有需要进行超时判断的场景

AI_TIMEOUT = TIMEOUT_AI          # 单模块单次 AI 调用超时（秒）
# ★ `*_TOTAL_BUDGET` 与 `TIMEOUT_*` 性质不同，不可混用：
#   `TIMEOUT_*` 是**单次请求超时**；`*_TOTAL_BUDGET` 是**单只标的累计耗时熔断**。
#   预算若也套 30s，判断链五节点（60s × 5 串行）必然熔断、永远走不到。
#   增强模块 6 个 / 并发上限 3 → 2 批 × 60s + 余量。
AI_TOTAL_BUDGET = 150.0          # 单只标的 AI 总耗时预算（秒），硬熔断
AI_MAX_CONCURRENCY = 3           # 单只标的并发模块上限
AI_TEMPERATURE = 0.0             # 定性判定要稳定可复现，取 0
AI_MAX_TOKENS = 800

# ─── 判断链五节点（node_*）专用配额 ───
# ★ 与增强模块不同：五节点要求模型**输出推导过程**（估值推导、左尾清单、
#   证伪清单、子判定…），不是回一个判定词。800 token 装不下推导，
#   会被截断成半截 JSON 而解析失败。故单节点输出空间放宽。
# ★ 实测：1600/3000 都会把模型的推导过程**截成半截 JSON**导致解析失败
#   （模型确实在写长推导 —— 这正是我们要的，但截断了就全废）。
#   输出长度随标的波动，故留足余量；API 侧已验证接受 4000。
AI_MAX_TOKENS_NODE = 4000
# 节点调用同样是对 AI 分析接口发起的调用 → 与 AI_TIMEOUT 一致取 TIMEOUT_AI
# （语义：凡是调 AI 分析接口都是 60 秒）。
AI_TIMEOUT_NODE = TIMEOUT_AI
# 预算按超时推导：五节点**串行**执行，最坏 60s × 5 + 余量 = 320s。
# ★ 仅 `analyze` 单股路径承担；`screen` 全市场路径不跑判断链节点。
AI_NODE_TOTAL_BUDGET = 320.0

# ─── 博查 AI 搜索（Bocha AI Search API，链路 2 外部产业补证选配）────
BOCHA_API_KEY = os.getenv("BOCHA_API_KEY", "")
BOCHA_API_BASE = os.getenv("BOCHA_API_BASE", "https://api.bochaai.com/v1")
BOCHA_ENABLED = bool(BOCHA_API_KEY)

# ─── 链路 2：两阶段审问式深度验票开关（Two-Pass Adversarial Audit）────
TWO_PASS_AUDIT_ENABLED = os.getenv("AST_TWO_PASS_AUDIT", "1").strip().lower() in ("1", "true", "yes", "on")

# AI 提名的红旗**最高级别**。默认 🟠：AI 永远无法直接触发 🔴 致命封顶与清零仓位，
# 最严重的后果仍由脚本红旗掌握 —— 这是一条刻意的保守约束，防止一次幻觉毁掉整张卡。
# 确需放开时改成 "🔴"，但请先确认证据层已稳定。
AI_MAX_NOMINATION_LEVEL = "🟠"


def ai_status() -> tuple[bool, str]:
    """返回 `(是否可用, 人类可读状态)`，供 CLI 显式告知用户 AI 到底开没开。

    ★ 必须有这个函数：AI 静默回退是**特性**（保证无网可用），
      但对用户而言「没报错」和「没启用」长得一模一样，
      不做显式告知就永远搞不清 AI 到底有没有参与分析。
    """
    if not AI_ENABLED:
        return False, "AI 判断层：已关闭（默认）。加 --ai 参数或设 AST_AI_ENABLED=1 启用"
    if not AI_API_KEY:
        return False, "AI 判断层：已开启但缺少 Key —— 请在 .env 或环境变量中设置 AST_AI_API_KEY"
    return True, f"AI 判断层：已启用（模型 {AI_MODEL}）"

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "ast_trader.log"

CACHE_DIR = BASE_DIR / ".cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ─── 通达信行情服务器节点池 ───
# ★ 本项已**删除**：原 5 台固定 IP 年代久远且无故障转移，eltdx 包内自带
#   43 台候选池更新更勤、覆盖更好，直接由它兜底即可。
#   需要指定节点请设环境变量 AST_TDX_HOSTS 或建 tdx_servers.json，
#   解析优先级见 data/tdx_hosts.py。

# ─── eltdx 连接与重试参数（集中在此，禁止在采集层散落裸数字）───
ELTDX_TIMEOUT = TIMEOUT_DEFAULT        # 行情主站连接超时（秒）
ELTDX_CALC_TIMEOUT = TIMEOUT_DEFAULT   # 财务计算服务器超时（秒）
ELTDX_MAX_RETRIES = 3            # 传输类错误最大重试次数
ELTDX_RETRY_BACKOFF = 0.5        # 指数退避基数（秒）：delay = base * 2^attempt
ELTDX_RETRY_SLEEP_CAP = 8.0      # 单次退避封顶（秒），避免把采集拖到分钟级
# 构造客户端时是否并发 TCP 测速排序。默认 False：open_client 在采集层被高频调用，
# 每次扇出 43 台探测会把取数拖垮。eltdx 连接池会自动套用已持久化的排名，
# 需要重测时单独跑 eltdx.hosts.refresh_server_ranking() 一次即可。
ELTDX_PROBE_HOSTS = False

# ─── 公告语料池（证据层）───
ANNOUNCEMENT_TIMEOUT = TIMEOUT_DEFAULT   # 单份公告 PDF 下载超时（秒）
ANNOUNCEMENT_MAX_DOCS = 6        # 单只标的最多精读份数（控制延迟与上下文）
ANNOUNCEMENT_MAX_HITS = 30       # 单份公告最多保留的关键词命中条数
# AI 语境用的精读份数。★ 单股 analyze 场景延迟可接受（实测约 85s，且 PDF 落盘缓存
# 后二次命中为秒级），因此这里不再为延迟收窄 —— 证据越充分，定性判断越可靠。
AI_CONTEXT_MAX_DOCS = 6
# 每份公告最多取几条引文进 prompt
AI_CONTEXT_CITATIONS_PER_DOC = 5

# ─── 短线风控红线 ───
# ★ 质押有两个**不可互换**的口径（通道 CWServ.tdxf10_gg_zbyz / section="gqzy"）：
#   · 占总股本比例（table1.t016 / table2.zzgb）—— 这才是通常说的"质押率"
#   · 占其持股比例（table1.t021）—— 爆仓踩踏指标，与总股本口径相差可达数量级
PLEDGE_FATAL_RATIO = 0.70        # 质押**占总股本** > 70% 致命
PLEDGE_HIGH_RATIO = 0.50         # 质押**占总股本** > 50% 警示
#: 控股股东把**自己持股**的多少质押掉 → 爆仓踩踏（平仓线被击穿时的强平连锁）
PLEDGE_OWN_FATAL_RATIO = 0.95    # 占其持股 > 95%（近乎满仓质押）
PLEDGE_OWN_HIGH_RATIO = 0.80     # 占其持股 > 80% 警示（仅降权，不否决）
#: ★ 占其持股比例**单独不足以判致命** —— 需叠加绝对规模。
#:   大股东把自己持股 100% 质押，但其持股本身只占总股本 5% 时，即便全部强平
#:   对股价冲击也有限。真正的踩踏需要"高强度 + 大规模"同时成立。
#:   实测格力 000651：占其持股 100%，但占总股本仅 15.35% < 20% ⇒ 不否决（避免误杀白马）。
PLEDGE_OWN_FATAL_MIN_TOTAL = 0.20
# 监管违规处罚 (立案调查/行政处罚/监管函)：近 N 年内的记录计入"近期"
GOVERNANCE_VIOLATION_RECENT_YEARS = 3
GOVERNANCE_VIOLATION_FATAL_COUNT = 3   # 近期违规记录条数 >= 该值判致命
BENEISH_M_FATAL_SCORE = -1.78   # Beneish M-Score > -1.78 判定高概率造假

# ─── 审计模型适用性准入 (P0-4) ───
# 模型 → 在其校准域外、必须主动弃权的行业。
# Beneish/Altman 均基于制造业样本校准，对银行业无判别力，套用会产生系统性误报。
AUDIT_MODEL_INDUSTRY_BLOCKLIST: dict[str, tuple[str, ...]] = {
    "Beneish": ("金融",),
    "AltmanZ": ("金融",),
    # ★ 20261029 审计 P1-10：金融业门控此前**只覆盖了两个**模型。下面四个同样是
    #   制造业/一般工商业口径校准的模型，套到银行/券商/保险上同样失真：
    #     · Piotroski F-Score：9 个签号依赖 ROA/CFO/杠杆/周转率，银行的"杠杆"
    #       是经营模式而非风险，签号方向含义相反；
    #     · DuPont：银行的高杠杆是常态，权益乘数分解出来的是经营模式而非质量；
    #     · Buffett Quality：依赖利润率/毛利率/债务权益比，银行无"毛利率"概念；
    #     · Sloan Accrual：依赖应计项目（应收/存货/应付），银行报表无此结构。
    "Piotroski": ("金融",),
    "DuPont": ("金融",),
    "Buffett": ("金融",),
    "Sloan": ("金融",),
}
SLOAN_ACCRUAL_FATAL_RATIO = 0.15 # 应计利润 / 总资产 > 15% 严重异象
# 业绩预告扣非同比下滑 > 50% 判致命（E-3 已接线至 audit_engine._check_forecast_anomaly）
# ⚠️ 数据源状态：eltdx F10 无「公司业绩预告」通道，gov["forecast"] 当前无生产者，
#    规则已实现但处于待数据源状态，严禁视为已生效。
FORECAST_DROP_FATAL_RATIO = -0.50

# ─── 全市场短线漏斗初筛阈值 ───
LIQUIDITY_MAIN_MIN_AMOUNT = 5.0e8   # 主板最低成交额 5.0 亿元
LIQUIDITY_GEM_MIN_AMOUNT = 3.0e8    # 双创板最低成交额 3.0 亿元
MOMENTUM_MIN_PCT_CHG = 4.5          # 最低涨幅 4.5%
# 换手率区间对齐 SRS FR-06 的 8%~25% (此前为 7%~28%，与需求文档不一致)
MOMENTUM_MIN_TURNOVER_RATE = 8.0    # 换手率下限 8%
MOMENTUM_MAX_TURNOVER_RATE = 25.0   # 换手率上限 25% (过高防滞涨出货)

# ─── 沪深全市场母池 (Universe) ───
# ★ 口径决策：本项目只做**沪市 + 深市 A 股**，北交所（8/4/920）为业务性永久排除，
#   不是"数据取不到"。故在母池层显式产出 BSE_OUT_OF_SCOPE 剔除码并加混入告警，
#   不允许靠"成交额门槛"这类间接手段隐式排掉（那样对账表会永远少一行，无法排查）。
UNIVERSE_MARKETS: tuple[str, ...] = ("sh", "sz")
UNIVERSE_CODE_PAGE_SIZE = 1000          # eltdx 单页上限 1600，取 1000 留余量
# ★ 20261028 实测：stock_profile_table 单次 200 只耗时 0.32s、返回 200 行且 199 行
#   换手率/上市日期非空（1 行确为停牌）。全市场 5225 只 ≈ 26 批 ≈ 10~30s，可接受。
#   继续加大需重新压测：重点是确认服务端不做隐式截断。
UNIVERSE_PROFILE_BATCH_SIZE = 200
UNIVERSE_MIN_COVERAGE_RATIO = 0.98      # 扫描数/预期数 低于此值 → 拒绝出结果并报断流
# Tier 2 排雷队列上限。母池放开到全市场后，Tier 1 存活集可能达数百只，而
# filter_audit 是**逐只**调 F10 治理接口，不设上限会把跑批拖到分钟级。
# ★ 与旧的硬编码 15 截断的本质区别：这里是**显式声明 + 计入归因矩阵**
#   （reason_code = AUDIT_QUEUE_TRUNCATED），绝不再做无声丢弃。
UNIVERSE_MAX_AUDIT_QUEUE = 120
UNIVERSE_EXCLUDE_ST = True              # 剔除 ST / *ST / SST / S*ST
UNIVERSE_EXCLUDE_DELISTING = True       # 剔除退市整理期（简称含"退"）
UNIVERSE_EXCLUDE_SUSPENDED = True       # 剔除当日停牌
# latest_suspended() 会按 80 只一批对全部 A 股发 legacy_quotes 请求，是代码表族里最重的
# 接口；非交易时段结果还可能与盘中不一致。默认开启，可关以省一次全量扫描。
UNIVERSE_USE_SUSPENDED_API = True
# 上市不足 N 个**交易日**的新股剔除（次新波动失真、无稳定财务与均线）。
# 代码表不提供上市日期，ipo_date 由 helpers.stock_profile_table 提供，故该规则在
# L1（profile 吞吐之后）执行，不在 L0。交易日/自然日按 5/7 近似换算。
UNIVERSE_NEW_LISTING_MIN_TRADING_DAYS = 60
UNIVERSE_TRADING_DAYS_PER_NATURAL_DAY = 5.0 / 7.0
# 死代码告警白名单：下列规则在特定行情下本就可能为 0，不参与「恒定不触发」告警。
# ★ 反例：换手率门槛曾因取错字段恒为 0（死代码），正是靠这条白名单之外的告警才能暴露。
# 支持两种写法：裸 ``reason_code``（对该码在所有层豁免）与 ``"层名/reason_code"``
# （仅对某一层豁免 —— 同一判据在不同层的"应不应该触发"可能不同）。
UNIVERSE_DEAD_RULE_WHITELIST: frozenset[str] = frozenset({
    "SUSPENDED",                          # 无停牌股时为 0
    "NEW_LISTING_LT_MIN_DAYS",            # 无新股上市时为 0
    "DELISTING",                          # 退市整理期可为空
    "BSE_OUT_OF_SCOPE",                   # 沪深数据源下恒为 0 属正常
    "PROFILE_MISSING",                    # 全量取数成功时应为 0
    "NOT_A_SHARE",                        # 代码表已按 a_share 过滤，恒为 0
    "AUDIT_QUEUE_TRUNCATED",              # 仅在存活集超过队列上限时才触发
    "AUDIT_VETO",                         # 零否决是好事，不是死规则
    "RANK_TRUNCATED",                     # 候选数 <= top_n 时不触发
    # ── 层内豁免：以下判据在 L0 已执行，T1 层只是**兜底防线**，恒 0 属正常 ──
    "T1_liquidity/ST_RISK_WARNING",
    "T1_liquidity/DELISTING",
    "T1_liquidity/BSE_OUT_OF_SCOPE",
    # ── 数据通道类判据：为 0 恰恰说明**通道健康**，不是规则失效 ──
    #   （不可核验与不合格必须分家，但"零缺失"不该被当成死规则告警）
    "B_BARS_MISSING",
    "B_PREFILTER_OUT",
    "B_VWAP_WEAK",          # 承接良好时为 0，属正常
    "C_BARS_MISSING",
    "C_PREFILTER_OUT",
    "D_FINANCE_MISSING",
    "D_VALUATION_UNVERIFIED",
})

# ─── K 线批量吞吐 ─────────────────────────────────────────────
# ★ 20261028 实测：bars.get 成本约 **26ms/只且与根数无关**（count=6 与 count=70 同为
#   200 只 5.2~5.4s）。全市场 5000 只 ≈ 130s —— **不可全量扫**。
#   ⇒ 硬约束：任何需要日 K 的轨道，都必须先用**免费字段**（市值分位/换手率/成交额/
#     涨跌幅，均来自 stock_profile_table）把候选压到数百只，再懒加载日 K。
KLINE_BATCH_SIZE = 50
KLINE_MISSING_REASON = "BARS_MISSING"

# ─── 财务批量吞吐 ─────────────────────────────────────────────
# ★ 20261028 实测：corporate.finance_batch 请求 300 只**只返回 100 只**（静默截断！），
#   但极快（100 只 0.03s）。⇒ 批大小必须 ≤ 100，且必须以返回的 code 为准建索引，
#   绝不能假设"请求 N 只就回来 N 只"。
FINANCE_BATCH_SIZE = 100
FINANCE_MISSING_REASON = "FINANCE_MISSING"

# ─── 轨道 B：弱转强 / 首阴反包 ────────────────────────────────
TRACK_B_ENABLED = True
TRACK_B_BARS_COUNT = 6              # 拉最近 6 根日 K（够判 3 日内曾涨停 + MA5 + 缩量）
TRACK_B_LOOKBACK_DAYS = 3           # 近 N 日内曾涨停
TRACK_B_MIN_AMOUNT = 1.0e8          # 候选预筛成交额下限（压缩日 K 拉取量）
TRACK_B_MAX_PCT_CHG = 3.0           # 今日涨幅上限：不收阴/不炸板者不属"弱"
# ★ 20261029 审计 P1-1：旧实现只有**上限** —— 于是"今日跌 9%"也满足"弱"的判据，
#   把破位暴跌当成弱转强洗盘接飞刀。弱转强要的是**浅回调**（有强之后的健康缩量回踩），
#   不是崩塌。现补跌幅下限：跌破该阈值即剔除（炸板行天然豁免，它才是"弱"的来源）。
TRACK_B_MIN_PCT_CHG = -7.0          # 今日跌幅下限：跌过头属破位，不属"弱转强"
TRACK_B_MAX_VOLUME_RATIO = 0.8      # 今日量 / 昨日量 < 0.8 = 缩量回踩
TRACK_B_MA_PERIOD = 5               # 收盘不得跌破 MA5
TRACK_B_MAX_VWAP_DEVIATION = 0.02   # |现价/均价 - 1| ≤ 2% → 未大幅低于均价（承接尚可）
TRACK_B_TRIAL_POSITION_PCT = 0.10   # 反包试错仓

# ─── 轨道 C：产业中军与趋势白马 ───────────────────────────────
# ★ 用户已裁决：「前十大流通股东机构持股占比 ≥15%」在 eltdx 无数据通道，
#   降级为**有则加权、无则 UNVERIFIED 降权、不参与准入**。
# ★ 另实测：ranking_detail 的行业排名 section（hypmdela/hypm）返回空，只有市场排名
#   pm 可得 ⇒ 行业排名同样降级为可选增强；**市值分位由本项目对全池自算**（5225 只
#   真实分位，比任何第三方分位都准），作为核心判据。
TRACK_C_ENABLED = True
TRACK_C_BARS_COUNT = 70             # 需 MA60
TRACK_C_MIN_MARKET_CAP_PCTILE = 0.70  # 市值分位 ≥ 70%（即全池前 30%）
TRACK_C_MIN_MARKET_CAP = 1.0e10     # 绝对市值下限 100 亿
TRACK_C_MIN_AVG_AMOUNT_20D = 8.0e8  # 20 日日均成交额 ≥ 8 亿
# ★ 换手率**必须按市值分档**（20261028 实测校准）：
#   美的集团(000333，市值约 5800 亿)当日换手仅 **0.345%**。若对全池套用统一的
#   1.5%~5%，所有大市值中军都会被这条规则误杀 —— 而它们恰恰是轨道 C 要选的目标。
#   市值越大换手天然越低，这是市场结构而非异常。分档格式：(市值下限, 换手下%, 换手上%)
TRACK_C_TURNOVER_BANDS: tuple[tuple[float, float, float], ...] = (
    (1.0e11, 0.2, 3.0),   # ≥ 1000 亿：0.2% ~ 3.0%
    (1.0e10, 0.5, 5.0),   # 100 亿 ~ 1000 亿：0.5% ~ 5.0%
    (0.0,    1.0, 8.0),   # 兜底档
)
TRACK_C_MIN_PCT_CHG = 0.0           # 不要求涨停，稳步推升即可
TRACK_C_MAX_PCT_CHG = 9.5           # 涨停的归轨道 A，中军不追板
TRACK_C_MA_PERIODS = (5, 20, 60)    # 多头排列 Close > MA5 > MA20 > MA60
TRACK_C_PRE_FILTER_MAX = 400        # 进入日 K 懒加载的候选上限（按市值降序）
TRACK_C_MAX_POSITION_PCT = 0.25

# ─── F10 深度取数（多期财报 + 十大流通股东）──────────────────────
# ★ 20261028 实测：F10 走 HTTP 7615 无状态，单线程 268~293ms/只；
#   每线程独立 F10Client + 并发可大幅摊薄（150 只实测）：
#     并发 8  → 14.4s（96ms/只）
#     并发 16 →  8.7s（58ms/只）  ← 采用
#   只调利润表（不取资产负债表）可再降到 6.2s。
F10_DEEP_MAX_WORKERS = 16
F10_DEEP_TIMEOUT = TIMEOUT_DEFAULT

# ─── 机构持股（前十大流通股东）────────────────────────────────
# ★ 通道：CWServ.tdxf10_gg_gdyj + section="ltgd" 的 tables[1]，
#   每行带 lb 股东类别标签 + cgs 持股数，18 个报告期 × 10 名股东。
#   （此前判"无数据通道"是错的 —— 错在用错了 Entry，不是通道不存在。）
TRACK_C_INSTITUTION_MIN_RATIO = 0.15
#: 严格机构（度量"专业机构认可度"）
TRACK_C_INSTITUTION_LABELS = (
    "基金", "保险", "QFII", "券商", "社保", "信托", "财务公司",
    "资管计划", "私募证券投资基金", "北上资金",
)
#: 国家队 / 特殊法人（证金、汇金等），单独统计，默认不计入严格机构
TRACK_C_INSTITUTION_STATE_LABELS = ("特殊法人",)
#: 一般法人 = 控股股东 / 产业资本（如美的控股占十大流通股东 48.6%）。
#: ★ 刻意**不计入**机构：否则大股东持股会把机构占比整体顶高，指标失效。

# ─── ROE / 净利润边际拐点（多期财报）──────────────────────────
# ★ 通道：CWServ.tdxf10_gg_cwfx（finance_report）一次返回 32~114 个报告期，
#   每行带 rq 报告期 ⇒ 拐点**可核验**（此前误判为不可得）。
TRACK_D_TREND_ENABLED = True
#: 同比增速边际变化达 ±N 个百分点才算「加速 / 减速」
TRACK_D_TREND_MIN_YOY_DELTA_PCT = 10.0
#: 「边际恶化」是否作为轨道 D 的否决项（仅对**可核验**标的生效）
TRACK_D_TREND_REJECT_DETERIORATING = True
#: 是否额外取资产负债表以计算 ROE 序列（多一次调用；关掉则只算净利润拐点）
TRACK_D_TREND_WITH_BALANCE = True

# ─── 轨道 D：困境反转与价值成长 ───────────────────────────────
# ★ 实测：f10.valuation 只返回分页计数（num/total_num），**无 PE/PB**；
#   f10.finance_diagnosis 返回 0 行。**PE/PB/ROE/经营现金流一律改由
#   corporate.finance_batch 自算**（eps / 每股净资产 / 净利润 / 净资产 / 经营现金流）。
# ★ 拐点走 f10_deep 的多期财报（T030 归母净利润 + 恒等式净资产），
#   不再是"单期快照不可得"。
TRACK_D_ENABLED = True
TRACK_D_MAX_PE = 30.0               # 估值双锚之一：PE 上限
TRACK_D_MAX_PB = 3.0                # 估值双锚之二：PB 上限
TRACK_D_MIN_ROE = 8.0               # ROE 下限 (%)
TRACK_D_MIN_OCF_TO_PROFIT = 0.8     # 经营现金流 / 净利润 ≥ 0.8 → 利润有现金支撑
TRACK_D_MIN_AMOUNT = 5.0e7          # 成交额下限（防僵尸股）
TRACK_D_MAX_POSITION_PCT = 0.20

# ─── 轨道 A：首板次日集合竞价确认条件 ───
# 盘后选股是为次日（T+1）做预案，首板当日涨停是客观事实，不能因"涨停=追高"把仓位归零。
# 改为给出可在次日 9:25 被客观验证的触发条件：满足才建试错仓，不满足即废单。
AUCTION_MIN_OPEN_PCT = 2.0          # 次日竞价高开下限 (%)
# ★ 20261029 审计 P1-6：原 0.15（竞价量≥昨日全天 15%）是**拍脑袋的门槛** ——
#   实测 20 只样本 0 只可达，等于把所有首板次日方案一律废单（与"首板死锁"同源）。
#   现按实测可达区间下调至 0.03，并在报告与剧本中标注"该阈值未经大样本校准"。
AUCTION_MIN_VOLUME_RATIO = 0.03     # 竞价成交量 / 昨日全天成交量 下限
AUCTION_TRIAL_POSITION_PCT = 0.10   # 竞价条件满足时的试错仓位

# ─── 仓位与博弈阈值 ───
# 单票仓位双档上限 (E-1)：常规档与极端档二选一，由主力引擎置信度裁决。
# 说明：主力引擎各阶段 suggested_pos_cap 取值域为 {0.0, 0.10, 0.15, 0.20}，
# 因此常规档下有效上限即 20%；极端档放开至 25%，仅在高置信度且主力已给满档时启用。
MAX_SINGLE_POSITION = 0.20          # 常规单票仓位上限 20%
MAX_SINGLE_POSITION_EXTREME = 0.25  # 极端情形单票仓位上限 25%
POSITION_EXTREME_MIN_CONFIDENCE = 90.0   # 启用极端档所需的主力引擎置信度下限
POSITION_EXTREME_MIN_STAGE_CAP = 0.20    # 启用极端档所需的主力引擎自身建议仓位下限
LEFT_TAIL_WARN_THRESHOLD = 0.25     # 左尾回撤 > 25% 仓位强制腰斩至 10%
# 执行剧本仓位配比：首仓占比，以及非龙头标的相对上限的折价
PLAYBOOK_BASE_POSITION_RATIO = 0.60
PLAYBOOK_NON_LEADER_CAP_RATIO = 0.80

# ─── 追踪账本：T+1 收益口径（20261029 审计 P0-4）───
# ★ 旧实现用「选出日收盘价」当买入基准，那是**看后视镜开车**：选出日收盘时
#   人还没下单，次日开盘能不能按那个价成交根本不保证。现改为**次日开盘价**成交、
#   次日收盘价卖出，并扣除真实交易成本 —— 否则胜率是被高估的假账。
TRACKER_STAMP_DUTY_PCT = 0.05        # 卖出印花税（%，2023 年起 0.05%）
TRACKER_COMMISSION_PCT = 0.025       # 佣金（万 2.5 = 0.025%，双边）
TRACKER_COMMISSION_MIN_YUAN = 5.0    # 佣金最低 5 元（小额交易时占比会显著上升）
TRACKER_TRANSFER_FEE_PCT = 0.001     # 过户费（%，沪深双边）
TRACKER_ASSUMED_AMOUNT_YUAN = 100000.0   # 单票名义成交额假设，用于把固定费用折算成百分比

# ─── 主力阶段：确定性标注阈值（仅供展示，不参与判定计算）───
# ★ 主力阶段的**定性校验**已交由 AI 判断层（模块 `mainforce`）依据判据手册
#   完成 —— 判据写在 `core/ai_coprocessor/prompts/mainforce.md`，
#   由模型综合市值、波动特性、量比、资金方向等上下文判断，
#   **不再用固定阈值硬编码**（绝对阈值在不同市值/波动标的间不可比）。
# 此处仅保留"置信度不足时不以确定性口吻输出阶段名"的**展示**阈值。
MF_MIN_CONFIDENCE_FOR_STAGE_LABEL = 55.0
# E-4: 命中具备下列风格关键词的游资席位时，判定为「次日砸盘 / 一日游 / 散户拥挤」高危
PLAYBOOK_DUMP_RISK_STYLE_KEYWORDS: tuple[str, ...] = ("砸盘", "一日游", "散户大本营", "高频做T")

# ─── 门控规则严重度（fail 参与 passed / warn 仅提示）───
# 新增规则一律默认 warn：门控失败会把决断卡降级为「观察」并清零仓位，
# 一条误报规则的代价是全市场标的集体失效，远高于漏报。
# 观察一个周期确认无噪声后，把对应项改成 "fail" 即可，无需改代码。
LINT_RULE_SEVERITY: dict[str, str] = {
    "R1": "warn",    # 契约校验
    "R2": "warn",    # 红旗闭环
    "R3": "warn",    # 数值单点真理
    "R4": "warn",    # 支柱正文预算
    "R5": "warn",    # 区间锚自洽
    "R14": "warn",   # 无过程注释
    "R15": "fail",   # 三元组同源（纯字符串相等，零误报风险）
    "R16": "warn",   # 锚引用过期
    "R18": "warn",   # 红旗台账同步
}


# ─── 本土法务会计与排雷专项阈值 ──────────────────────────────────────
# 存贷双高高危阈值 (康美/康得新暴雷模型)
FORENSIC_CASH_RATIO_WARN = 0.20          # 货币资金占总资产下限
FORENSIC_DEBT_RATIO_WARN = 0.20          # 有息负债占总资产下限
FORENSIC_CASH_RATIO_FATAL = 0.25         # 致命存贷双高货币资金占比下限
FORENSIC_DEBT_RATIO_FATAL = 0.25         # 致命存贷双高有息负债占比下限
FORENSIC_FIN_EXP_EROSION_RATIO = 0.25    # 财务费用占营业利润或净利润侵蚀比下限

# 在建工程长期不转固阈值 (虚构资产/隐藏折旧模型)
FORENSIC_CIP_TO_FIXED_WARN = 0.40        # 在建工程 / 固定资产下限
FORENSIC_CIP_TO_FIXED_FATAL = 0.60       # 在建工程 / 固定资产高危下限
FORENSIC_CIP_TO_ASSETS_MIN = 0.15        # 在建工程占总资产下限 (排除小体量)
