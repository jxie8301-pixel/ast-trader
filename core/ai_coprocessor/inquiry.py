"""core.ai_coprocessor.inquiry —— Pass 1: 核心矛盾提审器（Skeptic Reviewer）。

严禁直接给出买卖结论！
大模型或内置买方审计规则充当“看空风控官”，根据 5 支柱量化数据、11 经典排雷红旗
与资金微观特征，提炼出 2~3 个最致命的“核心证伪矛盾提纲”，为后续针对性检索提供明确指引。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Sequence

import config

logger = logging.getLogger("ast_trader.ai.inquiry")


@dataclass
class ContradictionInquiry:
    """一条核心矛盾审问条目。"""

    id: str                               # 矛盾编号: "C1", "C2", "C3"
    category: str                         # 矛盾类别: "financial_authenticity" | "growth_validation" | "governance_risk" | "valuation_odds"
    anomaly: str                          # 客观数据异常点 / 红旗触发点
    core_question: str                    # 致命审问问题
    keywords: list[str] = field(default_factory=list) # 推荐检索关键词
    evidence_type: str = "all"            # 优先检索类型: "announcement" | "survey" | "news" | "bocha" | "all"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "anomaly": self.anomaly,
            "core_question": self.core_question,
            "keywords": self.keywords,
            "evidence_type": self.evidence_type,
        }


def _build_rule_based_inquiries(
    ts_code: str,
    stock_name: str,
    flags: Sequence[Any],
    quant_summary: dict[str, Any],
) -> list[ContradictionInquiry]:
    """规则版核心矛盾提炼（无网/无 AI 时 100% 确定性兜底）。"""
    inquiries: list[ContradictionInquiry] = []
    c_idx = 1

    flag_titles = {str(getattr(f, "title", "") or ""): f for f in flags}

    # 1. 存贷双高 / 资金真实性
    if any("存贷双高" in t for t in flag_titles):
        inquiries.append(ContradictionInquiry(
            id=f"C{c_idx}",
            category="financial_authenticity",
            anomaly="触发【存贷双高】法务红旗：货币资金充裕的同时存在大额有息负债",
            core_question=f"{stock_name} 账面高额货币资金是否存在未披露的质押冻结或受限资金池？存款利息收益率是否显著偏低？",
            keywords=["受限资金", "质押", "定期存款", "银行存款", "利息收入"],
            evidence_type="announcement",
        ))
        c_idx += 1

    # 2. 在建工程长期挂账 / 资产虚增
    if any("在建工程" in t for t in flag_titles) and c_idx <= 3:
        inquiries.append(ContradictionInquiry(
            id=f"C{c_idx}",
            category="financial_authenticity",
            anomaly="触发【在建工程异常】法务红旗：在建工程规模庞大或建设周期异常漫长",
            core_question=f"{stock_name} 在建工程核心大项目的真实进度如何？是否存在已实质投产但长期不结转固定资产以逃避折旧的行为？",
            keywords=["在建工程", "转固", "工程进度", "固定资产", "折旧"],
            evidence_type="announcement",
        ))
        c_idx += 1

    # 3. 股权质押 / 减持 / 治理风险
    if any("质押" in t or "违规" in t or "关注函" in t for t in flag_titles) and c_idx <= 3:
        inquiries.append(ContradictionInquiry(
            id=f"C{c_idx}",
            category="governance_risk",
            anomaly="存在大额股权质押或历史合规监管记录",
            core_question=f"{stock_name} 控股股东当前质押平仓警戒线距离现价多远？近期是否有解除质押或司法拍卖风险？",
            keywords=["解除质押", "质押公告", "问询函", "监管函", "整改"],
            evidence_type="announcement",
        ))
        c_idx += 1

    # 4. 估值与成长性兑现矛盾 (高 PE / 概念炒作)
    pe = float(quant_summary.get("pe") or 0.0)
    rev_dcf_growth = float(quant_summary.get("reverse_dcf_growth") or 0.0)
    if (pe > 50.0 or rev_dcf_growth > 25.0) and c_idx <= 3:
        inquiries.append(ContradictionInquiry(
            id=f"C{c_idx}",
            category="growth_validation",
            anomaly=f"估值偏高 (PE={pe:.1f}x)，反向DCF测算股价已计入未来超额增长预期",
            core_question=f"{stock_name} 当前热门业务/概念领域（如新订单、新产线）是否有经审计的实质订单落地？机构调研中对产能爬坡的最新表态如何？",
            keywords=["订单", "产能", "客户认证", "量产", "投资意向"],
            evidence_type="all",
        ))
        c_idx += 1

    # 5. 微观主力行为分歧 (若上述未满 2 条)
    apm = str(quant_summary.get("apm_pattern") or "")
    if apm == "AM_PUMP_PM_DUMP" and c_idx <= 3:
        inquiries.append(ContradictionInquiry(
            id=f"C{c_idx}",
            category="valuation_odds",
            anomaly="分时呈现【早盘脉冲诱多、午后算法撤退下砸】的 APM 结构",
            core_question=f"{stock_name} 日内成交量放大但价格重心下移，龙虎榜或大单资金是否呈现机构对倒派发迹象？",
            keywords=["大宗交易", "龙虎榜", "机构专用", "主力资金"],
            evidence_type="survey",
        ))
        c_idx += 1

    # 兜底默认提问（确保至少有 2 条）
    if len(inquiries) < 2:
        inquiries.append(ContradictionInquiry(
            id=f"C{c_idx}",
            category="growth_validation",
            anomaly="主营业务增长持续性与下游需求博弈",
            core_question=f"{stock_name} 最新一期机构调研纪要与业绩预告中，对核心产品的订单与毛利率展望是乐观还是承压？",
            keywords=["调研", "订单", "毛利率", "产能", "业绩预告"],
            evidence_type="survey",
        ))

    return inquiries[:3]


def formulate_inquiries(
    ts_code: str,
    stock_name: str,
    quant_summary: dict[str, Any],
    flags: Sequence[Any],
) -> list[ContradictionInquiry]:
    """主入口：生成 Pass 1 核心矛盾提纲。

    优先尝试调用 AI 生成针锋相对的致命矛盾；若 AI 未开启或异常，回退到规则提炼。
    """
    rule_inquiries = _build_rule_based_inquiries(ts_code, stock_name, flags, quant_summary)

    if not config.AI_ENABLED:
        return rule_inquiries

    try:
        from core.ai_coprocessor.provider import call_llm

        flag_desc = "\n".join(f"- [{getattr(f, 'level', '')}] {getattr(f, 'title', '')}: {getattr(f, 'detail', '')}" for f in flags[:8])
        metrics_desc = (
            f"PE={quant_summary.get('pe', '-')}, PB={quant_summary.get('pb', '-')}, "
            f"ROE={quant_summary.get('roe_latest', '-')}, "
            f"聪明钱Q={quant_summary.get('smart_q', '-')}, APM形态={quant_summary.get('apm_pattern', '-')}"
        )

        prompt = f"""你是一位拥有15年经验的买方高阶风险控制官与尽调审计员。
现在你面对标的【{stock_name} ({ts_code})】的量化基线与法务财务初筛结果。

【初步量化与财务异动】:
{metrics_desc}

【触发的法务与业务红旗】:
{flag_desc if flag_desc else '暂无严重法务红旗'}

【任务要求】:
1. 严禁给出“买入/卖出/持有”等任何结论！你的唯一职责是专门“挑刺与找致命隐患”。
2. 请提炼出 2~3 个最可能推翻做多逻辑的【核心证伪矛盾】（如：造假嫌疑、订单未落地、大客户依赖被砍单、商誉爆雷、巨额减持）。
3. 必须输出合法 JSON 数组，每个对象包含字段：
   - "id": 序号 ("C1", "C2", "C3")
   - "category": 类别 ("financial_authenticity" | "growth_validation" | "governance_risk" | "valuation_odds")
   - "anomaly": 观察到的数据异动
   - "core_question": 针对性的致命审问问题
   - "keywords": 检索关键词数组（3~4个最具辨识度的词）
   - "evidence_type": 优先信源 ("announcement" | "survey" | "news" | "bocha" | "all")

直接输出 JSON 代码块：
```json
[
  ...
]
```"""

        content = call_llm(prompt, temperature=0.0)
        if content:
            raw = content.strip()
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()
            parsed = json.loads(raw)
            if isinstance(parsed, list) and parsed:
                out = []
                for idx, item in enumerate(parsed[:3], start=1):
                    out.append(ContradictionInquiry(
                        id=f"C{idx}",
                        category=item.get("category") or "growth_validation",
                        anomaly=item.get("anomaly") or "指标异常",
                        core_question=item.get("core_question") or "",
                        keywords=list(item.get("keywords") or ["公告", "调研"]),
                        evidence_type=item.get("evidence_type") or "all",
                    ))
                if out:
                    return out
    except Exception as exc:
        logger.warning("Pass 1 AI 核心矛盾生成异常，回退规则版: %s", exc)

    return rule_inquiries
