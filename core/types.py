"""Data models and interfaces for AST-Trader matching Section 6 of SRS/SAD."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import pandas as pd

from .red_flags import RedFlagItem


# =============================================================================
# 单股穿透分析各大支柱的强类型结果模型
# =============================================================================

@dataclass(frozen=True)
class QualityVerdict:
    """支柱 ❶ 质地判定结果。"""
    verdict: str                               # "好" / "部分好" / "不好"
    pillar_text: str                           # 支柱 ❶ 格式化全文本
    sub_verdicts: list[dict[str, str]]         # 质地五问子判定清单
    fatal_flags: list[RedFlagItem]             # 命中的 🔴 致命红旗
    is_fatal: bool                             # 是否命中致命红旗


@dataclass(frozen=True)
class StateVerdict:
    """支柱 ❷ 状态判定结果。"""
    verdict: str                               # 状态判定
    pillar_text: str                           # 支柱 ❷ 格式化全文本
    critical_wait: str                         # 全链唯一「该等什么」
    is_tech: bool                              # 是否具备科技/高成长属性


@dataclass(frozen=True)
class OddsVerdict:
    """支柱 ❸ 赔率判定结果。"""
    verdict: str                               # "便宜(有余地)" / "合理" / "未核验(财务缺失)" / "买完完美未来"
    pillar_text: str                           # 支柱 ❸ 格式化全文本
    sotp_ps: float | None                      # SOTP 每股保守底座
    dcf_ps: float | None                       # DCF 每股基准价值
    derivation: dict[str, Any]                 # 完整推导明细 (P=F+N, SOTP, DCF)
    anchor_range: dict[str, Any]               # 双锚区间 [SOTP, DCF]
    reverse_dcf: dict[str, Any]                # 反向 DCF 市场隐含增速
    ni_is_verified: bool                       # 净利润是否核验有效
    industry_pe_median: float | None = None    # 细分行业成分股动态 PE 中位数


@dataclass(frozen=True)
class PathVerdict:
    """支柱 ❹ 路径判定结果。"""
    verdict: str                               # 路径判定
    pillar_text: str                           # 支柱 ❹ 格式化全文本
    is_micro_degraded: bool                    # 微观数据是否降级
    mf_stage_code: str                         # 主力 7 阶段代码 (如 STAGE_1_ACCUMULATION)
    mf_stage: str                              # 主力阶段中文名
    mf_behavior: str                           # 主力行为描述
    mf_override: bool                          # 是否因微观盘口被强制覆盖
    mf_cap: float | None                       # 主力引擎建议仓位
    mf_conf: float                             # 主力阶段置信度 (0~100)
    is_trans: bool                             # 是否处于过渡态
    depth_to_sotp: float | None                # 现价距 SOTP 底座深度
    profit_chip_pct: float                     # 获利盘比例
    chip_peak_price: float | None = None       # 近 20 日筹码密集峰价格
    vwap_divergence_pct: float | None = None   # 现价与 Smart VWAP 动态乖离率
    is_false_breakout: bool = False            # 是否识别到假突破/脉冲诱多


@dataclass(frozen=True)
class DecisionVerdict:
    """支柱 ❺ 决断与战术判定结果。"""
    decision_gear: str                         # 行动档位: 核心仓 / 期权仓 / 等证据临界(观察) / 回避 / 减仓
    decision_title: str                        # 决断主标题
    position_cap: float                        # 建议仓位上限 (0.0~0.25)
    core_contradiction: str                    # 核心矛盾
    action_tactic: str                         # 行动战术
    invalidation_line: str                     # T+1 唯一铁律失效退出线
    regulatory_status: str                     # 监管/立案调查状态
    three_part_conclusion: str                 # 三分结论串
    triad_verdict: str                         # 三元组 [状态 | 赔率 | 路径]
    dump_warning: str | None = None            # 龙虎榜量化砸盘风险文字预警
    tactical_odds: dict[str, Any] | None = None # 买方战术下注点位与盈亏比卡


# =============================================================================
# 统一单股穿透分析不可变上下文 (SingleStockContext)
# =============================================================================

@dataclass
class SingleStockContext:
    """个股深度穿透分析的统一不可变上下文容器。"""
    ticker: str                                # 股票代码 (如 002273.SZ)
    name: str                                  # 股票名称
    trade_date: str                            # 交易日期 (YYYYMMDD)
    quote: dict[str, Any] = field(default_factory=dict)
    momentum: dict[str, Any] = field(default_factory=dict)
    daily_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    flags: list[RedFlagItem] = field(default_factory=list)
    financial_reports: dict[str, Any] = field(default_factory=dict)
    financial_derived: dict[str, Any] = field(default_factory=dict)
    microstructure: dict[str, Any] = field(default_factory=dict)
    governance_info: dict[str, Any] = field(default_factory=dict)
    concepts: list[str] = field(default_factory=list)
    ladder_info: dict[str, Any] | None = None
    sentiment_overview: Any | None = None
    matched_youzi: list[dict[str, Any]] = field(default_factory=list)
    matched_personas: list[dict[str, Any]] = field(default_factory=list)
    trap_warnings: list[str] = field(default_factory=list)
    money_flow: dict[str, Any] | None = None
    lhb_records: list[dict[str, Any]] | None = None
    ai_enrichment: dict[str, Any] = field(default_factory=dict)
    data_health: dict[str, Any] = field(default_factory=dict)
    announcements: list[dict[str, Any]] = field(default_factory=list)
    industry_valuation: dict[str, Any] = field(default_factory=dict)


@dataclass
class DecisionCardData:
    """五节点因果决断卡数据模型。"""
    ticker: str
    name: str
    trade_date: str
    price: float
    pct_chg: float
    quality_verdict: str
    state_verdict: str
    odds_verdict: str
    path_verdict: str
    decision_gear: str  # 买入 / 观察 / 回避
    position_cap: float
    invalidation_line: str
    top3_risks: list[dict[str, Any]] = field(default_factory=list)
    all_flags: list[dict[str, Any]] = field(default_factory=list)
    matched_youzi: list[dict[str, Any]] = field(default_factory=list)
    trap_warnings: list[str] = field(default_factory=list)


@dataclass
class ScreenerCandidate:
    """全市场短线漏斗筛选候选标的数据结构。"""
    code: str
    full_code: str
    name: str
    close: float
    pct_chg: float
    amount: float
    board_level: int
    limit_reason: str
    seal_amt: float
    main_net_wan: float = 0.0
    main_ratio: float = 0.0
    rank_score: float = 0.0
    concepts: list[str] = field(default_factory=list)
    plan_high_open: str = ""
    plan_stop_loss: str = ""
