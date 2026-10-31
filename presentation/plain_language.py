"""白话层 —— 把买方黑话翻译成人话。

## 为什么需要

决断卡的正文由 `judgment_chain` 生成，术语密度极高（质地 / 状态跃迁 λ /
叙事溢价 / 反向DCF / 筹码承载 / 单向阀 …）。这些词对系统设计是有意义的
（它们是框架锚点），但**直接丢给读者就是阅读障碍**。

★ 本模块**只做展示层翻译**，绝不回写决断卡：
  · 不改 `judgment_chain` 任何判定逻辑，因此 16 条门控规则与既有回归全部不受影响；
  · 不改任何数值 —— 翻译只动文字，价位、仓位、证伪线一律原样。

## 用法

    from presentation.plain_language import plain, one_line_summary, explain_terms
    print(plain("质地五问"))        # -> "公司基本面五问"
"""
from __future__ import annotations

from typing import Any

__all__ = [
    "PLAIN_PILLAR_TITLES",
    "VERDICT_PLAIN",
    "GEAR_PLAIN",
    "TERMS",
    "SUBSTITUTIONS",
    "plain",
    "one_line_summary",
    "explain_terms",
    "generate_plain_triad_coaching",
]

# ---------------------------------------------------------------- 支柱标题
#: 五大支柱的白话标题 + 一句话说明「这段回答什么问题」
PLAIN_PILLAR_TITLES: dict[str, tuple[str, str]] = {
    "1": ("这公司靠不靠谱？", "看基本面：生意赚不赚钱、有没有别人抄不走的本事"),
    "2": ("最近在变好吗？", "看经营是在改善还是恶化，以及下一步该等什么信号"),
    "3": ("现在这个价贵不贵？", "用两种估值方法互相印证，判断价格是否合理"),
    "4": ("大资金在干什么？", "看主力进出、筹码分布，判断谁在买谁在卖"),
    "5": ("到底该怎么办？", "结论、能买多少、怎么买、错了怎么退"),
}

# ---------------------------------------------------------------- 符号判定
#: 三态符号 → 白话。只解释符号含义，不改变判定本身
VERDICT_PLAIN: dict[str, str] = {
    "✓": "✅ 达标（无异常）",
    "✅": "✅ 达标（无异常）",
    "⚠️": "⚠️ 有隐忧（需要注意，但未构成硬伤）",
    "⚠": "⚠️ 有隐忧（需要注意，但未构成硬伤）",
    "✗": "❌ 不达标（存在明确问题）",
    "✘": "❌ 不达标（存在明确问题）",
    "—": "— 无数据（无法判定，不等于没问题）",
}

#: 行动档位 → 白话
#: ★ 20261029 审计 P1-13：补齐 pillar5 六档词汇里缺失的档位。
#:   原表只有「回避/观察/试仓/买入/核心仓」，「期权仓(小)」「等证据临界(观察)」
#:   「不追高(贵但优质)」「减仓」四个真实档位没有白话释义 —— 呈现层出现
#:   「档位词汇互不认识」的裂缝，正是顶部标签画成「🔴 回避/空仓」的同源问题。
GEAR_PLAIN: dict[str, str] = {
    "回避": "别碰 —— 存在硬伤，先排除",
    "观察": "先看着 —— 可以关注，但不急着买",
    "试仓": "小仓位试试 —— 拿一点仓位验证判断",
    "买入": "可以买 —— 按执行手册分批建仓",
    "核心仓": "重点配置 —— 给到较高仓位",
    "期权仓(小)": "小仓位试试 —— 题材博弈，只拿一点仓位，错了就走",
    "等证据临界(观察)": "先看着 —— 等证据落地再决定，现在不下注",
    "不追高(贵但优质)": "别追高 —— 公司好但价格已经贵了，等回调再看",
    "减仓": "减一点 —— 把仓位降下来，先锁住利润",
}

# ---------------------------------------------------------------- 术语表
#: 术语 → 白话解释。**只用于「术语速查」区块**，不参与正文替换，
#: 因此释义可以写得完整详尽。
TERMS: tuple[tuple[str, str], ...] = (
    ("反向DCF", "按现在的股价反推市场对它未来增长的预期"),
    ("叙事溢价", "市场想象空间带来的那部分溢价"),
    ("状态跃迁", "经营状况的明显变化"),
    ("筹码承载", "各价位上套牢盘与获利盘的分布"),
    ("微观穿透", "逐笔成交与盘口细节"),
    ("质地五问", "基本面五问"),
    ("质地图谱", "基本面图谱"),
    ("质地", "公司基本面"),
    ("空间板", "当前连板高度最高的那只票"),
    ("晋级率", "前一天涨停的票今天继续涨停的比例"),
    ("炸板率", "涨停后被砸开的比例"),
    ("天梯", "连板高度的梯队分布"),
    ("水温", "市场整体情绪的冷热"),
    ("龙虎榜", "交易所每日公布的异动营业部榜单"),
    ("游资", "短线活跃资金"),
    ("席位", "营业部交易通道"),
    ("竞价", "开盘前集中撮合形成开盘价的那段时间"),
    ("换手率", "当天成交股数占流通股的比例"),
    ("流通市值", "可自由交易的股票总价值"),
    ("连板", "连续涨停"),
    ("证伪线", "证明判断错了就必须卖出的价格底线"),
    ("仓位上限", "这只票最多能占用的资金比例"),
    ("护城河", "别人抄不走的竞争优势"),
    ("实锤", "已经在财报或公告里确认的事实"),
    ("回声", "市场传闻，尚未被证实"),
    ("单向阀", "只能往一个方向生效的机制"),
    ("铁门筛选", "一票否决的硬性门槛"),
    ("主力", "大资金"),
    ("变好引擎 λ", "经营向好的信号强度"),
    ("证据斜率", "证据变化的走向"),
    ("双锚同向标记", "两种估值方法结论是否一致"),
    ("筹码沉淀承载", "各价位套牢盘与获利盘的分布"),
    ("左尾深度", "极端下跌情形下的最大跌幅"),
    ("高尾险", "尾部风险：小概率但损失极大的风险"),
    ("算法拆单", "把大单拆成小单的程序化下单"),
    ("知情均线", "掌握信息的资金的平均成本线"),
    ("多空过渡区", "多空力量交界、方向未定的区域"),
    ("CAGR", "年化复合增速"),
    ("SOTP", "分部估值：各块业务分别估值再加总"),
    ("DCF", "现金流折现估值"),
    ("PE(TTM)", "市盈率（按最近 12 个月利润算）"),
    ("ROE", "净资产收益率：公司用股东的钱赚钱的效率"),
    ("OCF", "经营现金流：主业实际收到的现金"),
)


#: 正文替换表 —— **只有替换后依然简短自然**的条目才放进来。
#:
#: ★ 这是被真实报告反复打脸后收敛出来的：把 `TERMS` 整套拿去做正文替换，
#:   「游资席位」会被切成「短线活跃资金营业部交易通道」、「竞价」会被展开成
#:   一整句话 —— 术语是认识了，句子却彻底读不通。翻译的目的是好读，不是炫技。
#: ★ 顺序有意义：长词在前，避免短词先命中把长词切坏。
SUBSTITUTIONS: tuple[tuple[str, str], ...] = (
    ('条件锚点 [SOTP, DCF]（基于以下假设，非唯一真理）:', '估值区间[分部,折现]:'),
    ('[⚠️ 市场强制交付的硬性义务 (Obligation)]', '[⚠️ 增长要求苛刻]'),
    ('[✓ 白送的可选彩票 (Free Option)]', '[✓ 安全垫充沛]'),
    ('身份定位: 当前处于【P2 (细分产业优势标的)】', '产业地位: 细分优势龙头'),
    ('反向 DCF (市场到底在赌什么):', '按股价反推预期:'),
    ('反向 DCF (市场到底在赌什么)', '按股价反推预期'),
    ('现价隐含 5年收入 CAGR 需达', '现价要求年化增速达'),
    ('跌回 SOTP 保守底座左尾深度:', '距底座极端跌幅:'),
    ('P=F+N 叙事拆解: 市值', '估值拆解: 总市值'),
    ('P3 (高景气赛道先锋龙头)', '高景气龙头'),
    ('P4 (重命名重组瓶颈候选)', '重组并购标的'),
    ('P2 (细分产业优势标的)', '细分优势龙头'),
    ('P1 (普通行业参与者)', '行业跟随者'),
    ('身份定位: 当前处于【', '产业地位: 【'),
    ('SOTP 锚底座:', '分部估值底座:'),
    ('SOTP 锚底座', '分部估值底座'),
    ('基本面底座 F', '已兑现底座 F'),
    ('无记忆性警示:', '防坑提示:'),
    ('变好引擎 λ:', '向好信号:'),
    ('两端口径差异:', '区间口径说明:'),
    ('叙事溢价 N', '预期溢价 N'),
    ('聪明钱 Q=', '主力买盘 Q='),
    ('反向 DCF', '按股价反推预期'),
    ('变好引擎 λ', '向好信号'),
    ('双锚同向标记', '两法是否同向'),
    ('筹码沉淀承载', '筹码分布'),
    ('反向DCF', '按股价反推预期'),
    ('多空过渡区', '多空交界'),
    ('知情成本', '主力成本线'),
    ('证据斜率', '证据走向'),
    ('同向共振', '互相印证'),
    ('左尾深度', '极端跌幅'),
    ('算法拆单', '程序化拆单'),
    ('知情均线', '主力成本线'),
    ('叙事溢价', '想象空间溢价'),
    ('状态跃迁', '经营变化'),
    ('筹码承载', '筹码分布'),
    ('微观穿透', '盘口细节'),
    ('质地五问', '基本面五问'),
    ('质地图谱', '基本面图谱'),
    ('游资席位', '短线活跃资金席位'),
    ('流通市值', '可流通市值'),
    ('铁门筛选', '硬性门槛'),
    ('CAGR', '年化增速'),
    ('SOTP', '分部估值'),
    ('高尾险', '尾部风险高'),
    ('空间板', '最高连板'),
    ('炸板率', '涨停被砸开的比例'),
    ('晋级率', '连板晋级率'),
    ('龙虎榜', '异动营业部榜'),
    ('换手率', '换手比例'),
    ('证伪线', '判断错了就退'),
    ('单向阀', '单向机制'),
    ('护城河', '竞争壁垒'),
    ('DCF', '现金流折现'),
)


def plain(text: str | None) -> str:
    """把文本里的黑话替换成**简短**白话。**仅用于展示**，不回写决断卡。

    ★ 只做字面替换，绝不改数字 —— 价位、仓位、比例一律原样保留。
    ★ 只替换 `SUBSTITUTIONS`（短替换），不替换完整 `TERMS`（长释义），
      否则句子会被撑成一团读不通的解释文字。
    """
    if not text:
        return ""
    out = str(text)

    # ★ 两遍替换，中间用占位符：直接顺序替换会让**替换结果**被后面的规则
    #   二次改写。真实案例：「知情均线」→「主力成本线」后，「主力」→「大资金」
    #   再命中一次，最后变成「大资金成本线」—— 好好的词被改坏了。
    meanings: list[str] = []
    for jargon, meaning in SUBSTITUTIONS:
        if jargon in out:
            out = out.replace(jargon, f"\x00{len(meanings)}\x00")
            meanings.append(meaning)
    for idx, meaning in enumerate(meanings):
        out = out.replace(f"\x00{idx}\x00", meaning)
    return out


def smart_natural_cutoff(text: str, max_chars: int = 150) -> str:
    """按句子语义边界进行自然截取，严禁暴力斩断断尾。"""
    if not text:
        return ""
    text = text.strip()
    if len(text) <= max_chars:
        return text

    min_pos = int(max_chars * 0.5)
    max_search_pos = min(len(text), int(max_chars * 1.35))
    candidate_sub = text[:max_search_pos]

    puncts = ["。", "！", "!", "；", ";", "\n"]
    best_pos = -1
    for p in puncts:
        pos = candidate_sub.rfind(p)
        if pos >= min_pos and pos > best_pos:
            best_pos = pos

    if best_pos != -1:
        return candidate_sub[:best_pos + 1].strip()

    for marker in ["②", "③", "④", "2)", "3)", "4)"]:
        pos = candidate_sub.find(marker)
        if pos >= min_pos:
            res = candidate_sub[:pos].strip()
            if res and res[-1] not in "。！!；;，,":
                res += "。"
            return res

    res = text[:max_chars].rstrip()
    for tail in ("，", "、", "与", "及", "和", "或", "若", "的", "为", "以", "在", "等"):
        if res.endswith(tail):
            res = res[:-len(tail)].rstrip()
    if "(" in res and ")" not in res[res.rfind("("):]:
        res = res[:res.rfind("(")].rstrip()
    if "（" in res and "）" not in res[res.rfind("（"):]:
        res = res[:res.rfind("（")].rstrip()
    if res and res[-1] not in "。！!；;":
        res += "。"
    return res


def one_line_summary(card: dict[str, Any]) -> str:
    """一句话结论：把整张决断卡压成「能不能买、买多少、错了怎么退」。

    ★ 全部取自结构化字段，**不做任何推断**，因此不会与正文矛盾。
    """
    name = card.get("name") or card.get("ticker") or "该股"
    gear = str(card.get("decision_gear") or "")
    cap = float(card.get("position_cap", 0.0) or 0.0)
    gear_text = GEAR_PLAIN.get(gear, gear or "未给出档位")

    if cap > 0.0:
        size_text = f"最多投入总资金的 {cap * 100:.0f}%"
    else:
        size_text = "不建议占用资金"

    line = f"{name}：{gear_text}。{size_text}。"

    inv = str(card.get("invalidation_line") or "").strip()
    if inv:
        # ★ 采用智能自然断句，彻底杜绝 [:100] 导致的断尾与半句问题
        inv_text = smart_natural_cutoff(plain(inv), max_chars=130).strip()
        if inv_text:
            line += f"判断错了就退：{inv_text}"

    fatal = sum(1 for f in (card.get("all_flags") or []) if f.get("level") == "🔴")
    if fatal:
        line += f" ⚠️ 另有 {fatal} 条致命风险必须先看完。"
    return line


def explain_terms(text: str | None, limit: int = 12) -> list[tuple[str, str]]:
    """列出文本中**实际出现**的术语及其白话解释。

    ★ 只解释正文里真的有的词 —— 整表照抄会变成噪音，读者根本不会看。
    """
    if not text:
        return []
    blob = str(text)
    hits: list[tuple[str, str]] = []
    seen: set[str] = set()
    for jargon, meaning in TERMS:
        if jargon in blob and jargon not in seen:
            seen.add(jargon)
            hits.append((jargon, meaning))
        if len(hits) >= limit:
            break
    return hits



def generate_plain_triad_coaching(card: dict[str, Any]) -> str:
    """生成买方白话点拨条 —— 消除三段式结论（好公司/好下注/好价格）的逻辑张力。"""
    p5 = card.get("pillar_5_decision") or {}
    conclusion = str(p5.get("three_part_conclusion") or card.get("three_part_conclusion") or "")
    gear = str(card.get("decision_gear") or "")
    pos_cap = float(card.get("position_cap", 0.0) or 0.0)

    # 1. 回避与零仓位风控铁律优先拦截：绝不允许出现「好公司配好价格...主力在洗盘...建议加入自选观察」
    if "回避" in gear or "减仓" in gear or pos_cap <= 0.0:
        flags = card.get("all_flags") or card.get("top3_risks") or []
        has_fatal = any(
            (f.get("severity") in ("FATAL", "HIGH") or f.get("level") == "🔴")
            for f in flags if isinstance(f, dict)
        )
        if has_fatal:
            return "【💡 买方白话点拨】公司基本面排雷触发买方硬性风控（主营质量或财务真实性存疑），盘面缺乏增量做多合力，弱势中继平台极易破位补跌，坚决空仓回避不碰。"
        return "【💡 买方白话点拨】公司基本面存在硬伤或估值严重透支，盘面缺乏增量做多合力，盈亏比极差，坚决回避不碰。"

    is_good_co = "好公司? 【是】" in conclusion or "好公司? 是" in conclusion
    is_good_bet = "好下注? 【是】" in conclusion or "好下注? 是" in conclusion
    is_good_price = "好价格? 【是】" in conclusion or "好价格? 是" in conclusion

    if is_good_co and is_good_price and not is_good_bet:
        return "【💡 买方白话点拨】公司基本盘扎实、估值有安全垫，属于好公司配好价格；但当前大盘处于弱势或主力仍在低位吸筹洗盘，左侧伸手容易挨套，建议先加入自选观察，等放量企稳或大盘好转再行介入。"
    elif is_good_co and not is_good_price and is_good_bet:
        return "【💡 买方白话点拨】虽然当前估值偏高甚至透支，但当前属于超短主线资金抱团品种，动能强劲；此阶段仅适合短线右侧博弈，严禁长线死扛，破止损线坚决离场。"
    elif is_good_co and is_good_price and is_good_bet:
        return "【💡 买方白话点拨】公司质地过硬，估值具有充分安全垫，且主力资金已给出明确的右侧买入信号，天时地利人和，可以积极按计划分批建仓。"
    elif not is_good_co and not is_good_bet:
        return "【💡 买方白话点拨】公司基本面存在硬伤或估值严重透支，盘面缺乏增量做多合力，盈亏比极差，坚决回避不碰。"
    elif "观察" in gear:
        return "【💡 买方白话点拨】基本面或估值尚可，但盘口缺乏右侧启动催化剂，建议持币观望，让子弹再飞一会儿。"
    else:
        return "【💡 买方白话点拨】严格遵守执行手册买卖纪律，分批建仓并设好证伪止损线。"
