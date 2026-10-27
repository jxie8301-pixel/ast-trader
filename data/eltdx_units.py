"""eltdx_units —— 单一单位换算层。

**为什么要有这一层**：eltdx 与 Tushare 的单位口径不一致，且 eltdx 内部自己就有
两套（原始值 `*_raw_float` 与已换算 property）。换算一旦分散到各消费模块，
必然出现「某处 ×1000 某处没乘」的静默脏数 —— 这种错不会报错，只会印出错 1000 倍
的数字（`data_snapshot.py:135-136` 已踩过一次同类的量纲事故：把毛利额当成毛利率，
印出「毛利率(%) | 2539181351.98」）。

所以：**所有单位换算只在这一处定义，消费模块禁止自行乘除**。

口径来源（`eltdx/docs/methods/7709-财务基础信息.md:160-167`）：
  · 股本类  raw 单位**万股**  → 实际股数 = raw × 10000
  · 金额类  raw 单位**千元**  → 人民币元 = raw × 1000
  · 每股类  raw 直接是**元**  → 不换算
  · 成交量  通达信 `volume_lots` 单位**手** → 股数 = 手 × 100

而 F10 报表（`f10.finance_report`）与专业财务 zip（`eltdx.financial`）返回的
金额**已经是元**，不需要本层的千元换算 —— 用 `yuan()` 显式标注，让"我没换算"
也是一次有意识的决定，而不是忘了。
"""
from __future__ import annotations

# ---------------------------------------------------------------- 换算因子
WAN_TO_SHARES = 10_000      # 万股 → 股
QIAN_TO_YUAN = 1_000        # 千元 → 元
LOTS_TO_SHARES = 100        # 手 → 股


def wan_to_shares(raw: float | None) -> float | None:
    """股本类：raw 单位万股 → 股。None 直通（缺值不是 0，别把 NaN 变成 0）。"""
    return None if raw is None else raw * WAN_TO_SHARES


def qian_to_yuan(raw: float | None) -> float | None:
    """金额类：raw 单位千元 → 人民币元。"""
    return None if raw is None else raw * QIAN_TO_YUAN


def qian_to_wan(raw: float | None) -> float | None:
    """金额类：raw 单位千元 → 万元（1 千元 = 0.1 万元）。

    ★ 加这个函数的直接原因：`daily_basic.ps` 曾经写成
    `qian_to_yuan(x) / 10`，等于 ×100，把营收放大了 1000 倍，ps 因此小 1000 倍
    （Tushare 27.24 vs eltdx 0.04）。ps 要求"市值与营收同为万元"，
    而市值天然是万元（元/股 × 万股），所以营收必须走这条换算。
    """
    return None if raw is None else raw * 0.1


def yuan(value: float | None) -> float | None:
    """金额已经是元（F10 报表 / 专业财务 zip）。恒等函数，用于**显式标注**单位来源。

    存在的意义不是做换算，是让读代码的人知道"这里确认过单位，是元"，
    与 `qian_to_yuan()` 形成对照，避免漏换算。
    """
    return value


def per_share(raw: float | None) -> float | None:
    """每股类（EPS / 每股净资产）：raw 直接是元，恒等。同 `yuan()`，用于显式标注。"""
    return raw


def lots_to_shares(lots: float | None) -> float | None:
    """成交量：手 → 股。通达信 K 线的 `volume_lots` 单位是手。"""
    return None if lots is None else lots * LOTS_TO_SHARES


def shares_to_lots(shares: float | None) -> float | None:
    """成交量：股 → 手（反向，用于与 Tushare 的 vol 对拍）。"""
    return None if shares is None else shares / LOTS_TO_SHARES


# ---------------------------------------------------------------- 代码归一化
# eltdx 一律用带市场前缀的完整代码（sz000001 / sh600000 / bj830799）；
# 本项目内部沿用 Tushare 形态（000001.SZ / 600519.SH）。两个方向的转换都放这里，
# 免得各处手写切片把 688（科创板，属 SH）与 8xx/9xx（北交所）搞混。
# ★ 规则必须**从长到短**排列，且长前缀优先。
#   冲突点：9 开头既可能是沪市 B 股（900xxx）也可能是北交所（920xxx，
#   2025 年由 8XXXXX 迁移而来）。只用首位数字判市场会**必然判错** ——
#   我第一版就写成 `_SH_PREFIXES = ("6", "9")`，把 920002 判成了 sh920002，
#   是单测把这个 bug 打出来的。深市同理：200xxx 是 B 股，不能被 "0" 抢先匹配。
_PREFIX_RULES = (
    ("920", "bj"),      # 北交所迁移后代码
    ("900", "sh"),      # 沪市 B 股
    ("200", "sz"),      # 深市 B 股
    ("6", "sh"),        # 沪市主板 / 科创板（688）
    ("0", "sz"),        # 深市主板
    ("3", "sz"),        # 创业板
    ("4", "bj"),        # 北交所（旧码段）
    ("8", "bj"),        # 北交所（旧码段）
)
_SUFFIX_TO_MARKET = {"SH": "sh", "SZ": "sz", "BJ": "bj"}


def to_eltdx_code(code: str) -> str:
    """Tushare 形态 → eltdx 形态：'600519.SH' → 'sh600519'；'000001' → 'sz000001'。

    带后缀时以**后缀为准**（最可靠）；纯六位时按 `_PREFIX_RULES` 推断。
    """
    raw = (code or "").strip().upper()
    if "." in raw:
        num, _, suffix = raw.partition(".")
        if suffix not in _SUFFIX_TO_MARKET:
            raise ValueError(f"未知的 A 股市场后缀: {code!r}")
        return f"{_SUFFIX_TO_MARKET[suffix]}{num}"
    if not (raw.isdigit() and len(raw) == 6):
        raise ValueError(f"不是合法的六位 A 股代码: {code!r}")
    for prefix, market in _PREFIX_RULES:
        if raw.startswith(prefix):
            return f"{market}{raw}"
    raise ValueError(f"无法推断市场的 A 股代码（请显式带 .SH/.SZ/.BJ 后缀）: {code!r}")


def to_ts_code(code: str) -> str:
    """eltdx 形态 → Tushare 形态：'sh600519' → '600519.SH'。

    纯数字时**复用** `to_eltdx_code` 的同一套前缀规则 —— 两个方向共用一份
    判定逻辑，避免"这边判 BJ 那边判 SH"的漂移。
    """
    raw = (code or "").strip().lower()
    for prefix, suffix in (("sh", "SH"), ("sz", "SZ"), ("bj", "BJ")):
        if raw.startswith(prefix):
            return f"{raw[len(prefix):].upper()}.{suffix}"
    if raw.isdigit():
        return f"{raw}.{to_eltdx_code(raw)[:2].upper()}"
    raise ValueError(f"不是合法的 eltdx 代码: {code!r}")


def code6(code: str) -> str:
    """取六位数字代码：'sh600519' → '600519'；'600519.SH' → '600519'。

    专业财务 zip 的索引里 code 是**不带前缀的六位**，F10 的 `finance_report`
    内部也是用六位请求 —— 两个接口都要它。
    """
    raw = (code or "").strip().lower()
    for prefix in ("sh", "sz", "bj"):
        if raw.startswith(prefix):
            return raw[len(prefix):]
    return raw.split(".")[0]
