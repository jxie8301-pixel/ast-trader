"""种子标的清单与特征契约。

本模块只做**声明**，不含网络调用与断言逻辑。它回答两个问题：

1. 我们想用哪些典型个股覆盖 A 股市场的哪几类特征？
   —— 由 ``SEEDS`` 给出：跨行业、跨市值档位、跨板块、跨财务特征与风险标签。
2. 每只种子「此刻是否仍然具备我们所声称的特征」？
   —— 由 :func:`probe_seed` 在跑批后基于真实数据判定，不成立即视为**特征漂移**，
      只记录告警并跳过方向性断言，绝不把漂移伪装成失败。

之所以把「预期」与「校验」分开：A 股个股特征会随摘帽、重组、业绩变脸而变化，
若把预期写死进断言，套件会在某个交易日突然变红且原因不明。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

# ─────────────────────────────────────────────────────────────────────────────
# 市场结构常量（用于把实时数值映射到离散档位，供方向性比对）
# ─────────────────────────────────────────────────────────────────────────────

#: 市值档位下限（单位：元）。由高到低匹配，未命中即 MICRO。
CAP_TIER_THRESHOLDS: tuple[tuple[str, float], ...] = (
    ("MEGA", 5000e8),    # ≥ 5000 亿：超大盘权重股
    ("LARGE", 500e8),    # 500 ~ 5000 亿：大盘蓝筹
    ("MID", 100e8),      # 100 ~ 500 亿：中盘
    ("SMALL", 30e8),     # 30 ~ 100 亿：小盘
)
#: 档位由小到大，便于计算「相差几档」
CAP_TIER_ORDER: tuple[str, ...] = ("MICRO", "SMALL", "MID", "LARGE", "MEGA")

#: 板块 → 代码前缀。MAIN 为兜底（含主板与 002 中小板）。
BOARD_PREFIXES: dict[str, tuple[str, ...]] = {
    "STAR": ("688", "689"),
    "GEM": ("300", "301"),
    "BSE": ("920", "8", "4"),
}

#: 板块 → 涨跌停幅度（%）。A 股现行规则：主板 10%，双创 20%，北交所 30%。
BOARD_LIMIT_PCT: dict[str, float] = {"MAIN": 10.0, "GEM": 20.0, "STAR": 20.0, "BSE": 30.0}


def board_of(code: str) -> str:
    """由六位代码推断板块归属。"""
    for board, prefixes in BOARD_PREFIXES.items():
        if code.startswith(prefixes):
            return board
    return "MAIN"


def cap_tier_of(total_mv: float | None) -> str | None:
    """由总市值（元）推断市值档位；缺失时返回 ``None``。"""
    if not total_mv or total_mv <= 0:
        return None
    for tier, floor in CAP_TIER_THRESHOLDS:
        if total_mv >= floor:
            return tier
    return "MICRO"


def tier_distance(a: str | None, b: str | None) -> int | None:
    """两个市值档位相差几档；任一为空返回 ``None``。"""
    if a not in CAP_TIER_ORDER or b not in CAP_TIER_ORDER:
        return None
    return abs(CAP_TIER_ORDER.index(a) - CAP_TIER_ORDER.index(b))


# ─────────────────────────────────────────────────────────────────────────────
# 特征探针：判定「此刻该股是否仍具备声称的特征」
# ─────────────────────────────────────────────────────────────────────────────


def probe_st(card: dict[str, Any]) -> bool:
    """风险警示股：证券名称含 ST。"""
    return "ST" in str(card.get("name") or "").upper()


def probe_loss_making(card: dict[str, Any]) -> bool:
    """亏损股：PE 缺失或为负（负 PE 是净利润为负的直接表征）。"""
    pe = card.get("pe")
    if pe is None:
        return True
    try:
        return float(pe) <= 0
    except (TypeError, ValueError):
        return True


def probe_high_valuation(card: dict[str, Any]) -> bool:
    """高估值股：PE 显著高于市场常见区间（取 60 倍为界）。"""
    pe = card.get("pe")
    try:
        return pe is not None and float(pe) >= 60.0
    except (TypeError, ValueError):
        return False


def _always(_card: dict[str, Any]) -> bool:
    """无特殊特征的常规标的，恒成立。"""
    return True


# ─────────────────────────────────────────────────────────────────────────────
# 种子契约
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SeedSpec:
    """一只种子标的的声明式特征契约。

    Attributes:
        code: 六位 A 股代码。
        name: 采集时的证券简称，仅用于展示与漂移提示，不做硬断言。
        board: 预期板块（MAIN/GEM/STAR/BSE）。
        cap_tier: 预期市值档位（MEGA/LARGE/MID/SMALL/MICRO）。
        industry: 行业标签，用于评估阶段按行业归集结论。
        financial_traits: 预期财务特征，作为吻合度比对的靶子。
        risk_tags: 预期风险标签，如 ST / 亏损 / 高质押。
        expect: 方向性预期。键为断言名，值为期望值。
        probe: 特征校验函数，接收决断卡并返回该特征是否仍成立。
    """

    code: str
    name: str
    board: str
    cap_tier: str
    industry: str
    financial_traits: tuple[str, ...] = ()
    risk_tags: tuple[str, ...] = ()
    expect: dict[str, Any] = field(default_factory=dict)
    probe: Callable[[dict[str, Any]], bool] = _always


#: 种子池。覆盖 4 个板块 × 5 个市值档位 × 7 个行业 × 4 类财务/风险特征。
SEEDS: tuple[SeedSpec, ...] = (
    # ── 超大盘消费蓝筹：高毛利、低杠杆、高 ROE，A 股质量因子的典型代表 ──
    SeedSpec(
        code="600519",
        name="贵州茅台",
        board="MAIN",
        cap_tier="MEGA",
        industry="食品饮料/白酒",
        financial_traits=("高毛利", "低资产负债率", "高ROE", "强现金流"),
        expect={"board": "MAIN", "limit_pct": 10.0, "cap_tier": "MEGA"},
    ),
    # ── 超大盘银行：金融机构天然高杠杆，是检验「负债率阈值是否误伤金融股」的关键样本 ──
    SeedSpec(
        code="601398",
        name="工商银行",
        board="MAIN",
        cap_tier="MEGA",
        industry="银行",
        financial_traits=("极高资产负债率(金融业固有)", "低PE", "低PB"),
        expect={"board": "MAIN", "limit_pct": 10.0, "cap_tier": "MEGA"},
    ),
    # ── 大盘股份行：与国有大行对照，检验同行业内估值差异是否被区分 ──
    SeedSpec(
        code="000001",
        name="平安银行",
        board="MAIN",
        cap_tier="LARGE",
        industry="银行",
        financial_traits=("极高资产负债率(金融业固有)", "低PE"),
        expect={"board": "MAIN", "limit_pct": 10.0, "cap_tier": "LARGE"},
    ),
    # ── 双创超大盘制造：重资产、中毛利，检验双创板 20% 涨跌停分支 ──
    SeedSpec(
        code="300750",
        name="宁德时代",
        board="GEM",
        cap_tier="MEGA",
        industry="电力设备/电池",
        financial_traits=("中毛利", "重资产", "高研发"),
        expect={"board": "GEM", "limit_pct": 20.0, "cap_tier": "MEGA"},
    ),
    # ── 科创板半导体：高 PE，检验「已被价格计入」与估值透支判定 ──
    SeedSpec(
        code="688981",
        name="中芯国际",
        board="STAR",
        cap_tier="MEGA",
        industry="电子/半导体",
        financial_traits=("高PE", "重资产", "高资本开支"),
        risk_tags=("高估值",),
        expect={"board": "STAR", "limit_pct": 20.0, "cap_tier": "MEGA"},
        probe=probe_high_valuation,
    ),
    # ── 中盘制造：既有历史研报可对照，检验结论纵向稳定性 ──
    SeedSpec(
        code="002273",
        name="水晶光电",
        board="MAIN",
        cap_tier="MID",
        industry="电子/光学光电子",
        financial_traits=("中毛利", "中等成长"),
        expect={"board": "MAIN", "limit_pct": 10.0, "cap_tier": "MID"},
    ),
    # ── 北交所微盘：检验 30% 涨跌停分支与微盘流动性处理 ──
    SeedSpec(
        code="920002",
        name="万达轴承",
        board="BSE",
        cap_tier="SMALL",
        industry="机械设备",
        financial_traits=("微盘", "低流动性"),
        expect={"board": "BSE", "limit_pct": 30.0, "cap_tier": "SMALL"},
    ),
    # ── 风险警示 + 亏损：检验致命红旗/亏损是否触发严格防守 ──
    SeedSpec(
        code="605336",
        name="*ST帅电",
        board="MAIN",
        cap_tier="MICRO",
        industry="家用电器",
        financial_traits=("净利润为负", "净资产承压"),
        risk_tags=("ST", "亏损"),
        expect={"board": "MAIN", "limit_pct": 10.0, "cap_tier": "MICRO"},
        probe=probe_st,
    ),
    SeedSpec(
        code="603959",
        name="ST百利",
        board="MAIN",
        cap_tier="MICRO",
        industry="建筑装饰",
        financial_traits=("净利润为负", "持续经营存疑"),
        risk_tags=("ST", "亏损"),
        expect={"board": "MAIN", "limit_pct": 10.0, "cap_tier": "MICRO"},
        probe=probe_st,
    ),
    SeedSpec(
        code="601718",
        name="ST际华",
        board="MAIN",
        cap_tier="MID",
        industry="纺织服饰",
        financial_traits=("净利润为负", "大额亏损"),
        risk_tags=("ST", "亏损"),
        expect={"board": "MAIN", "limit_pct": 10.0, "cap_tier": "MID"},
        probe=probe_st,
    ),
)

#: 便捷索引
SEEDS_BY_CODE: dict[str, SeedSpec] = {s.code: s for s in SEEDS}


def iter_seeds(*, only: str | None = None) -> tuple[SeedSpec, ...]:
    """按代码筛选种子；``only`` 为 None 时返回全部。"""
    if not only:
        return SEEDS
    return tuple(s for s in SEEDS if s.code == only)
