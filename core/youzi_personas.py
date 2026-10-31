"""Authentic 24 Youzi Personas & tape feature evaluator ported from UZI-Skill.
Includes full SEATS database, 500-billion market cap boundary and LHB seat matching.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PersonaSpec:
    """顶级游资操盘战法规范。"""
    investor_id: str
    name: str
    style: str
    must_have: tuple[str, ...]
    positive_patterns: tuple[str, ...]
    veto_rules: tuple[str, ...]
    entry_condition: str
    invalidation: str
    horizon: str = "1-3d"


# UZI-Skill 真实定义之 24 大一线游资操盘画像与严苛条件
F_PERSONAS: tuple[PersonaSpec, ...] = (
    PersonaSpec("zhang_mz", "章盟主", "容量趋势", ("capacity", "trend_up"), ("leader", "theme_hot"), ("illiquid", "isolated"), "主线核心维持放量承接", "跌破上午均价且板块转弱"),
    PersonaSpec("sun_ge", "孙哥", "板块引导", ("theme_hot", "leader"), ("breadth", "active"), ("isolated",), "板块宽度继续扩散", "个股强而板块不响应 (跌破 -3% 坚决离场)"),
    PersonaSpec("zhao_lg", "赵老哥", "一二板定龙头", ("strong", "leader"), ("fresh_theme", "active"), ("extended", "laggard"), "前排换手确认且题材保持新鲜", "后排化或题材快速退潮"),
    PersonaSpec("fs_wyj", "佛山无影脚", "超跌反核", ("small_cap", "reversal"), ("active",), ("large_cap", "illiquid"), "反核后承接不破启动位", "冲高无承接或跌破启动位坚决平仓"),
    PersonaSpec("yangjia", "炒股养家", "情绪周期", ("theme_hot",), ("breadth", "strong"), ("risk_off", "climax"), "赚钱效应继续向同题材扩散", "高位一致转分歧且亏钱效应扩散"),
    PersonaSpec("chen_xq", "陈小群", "龙头全周期", ("leader", "strong"), ("reversal", "hard_event"), ("laggard", "priced_in"), "总龙分歧转一致并带动板块", "后排跟风或消息兑现后失去承接"),
    PersonaSpec("hu_jl", "呼家楼", "板块平铺协同", ("breadth", "theme_hot"), ("capacity", "active"), ("isolated",), "多标的同步放量", "协同消失并退化为单票脉冲"),
    PersonaSpec("fang_xx", "方新侠", "大成交趋势", ("capacity", "trend_up"), ("near_high", "leader"), ("illiquid",), "大成交趋势保持在均价上方", "放量跌破趋势承接位"),
    PersonaSpec("zuoshou", "作手新一", "主线接力", ("theme_hot", "leader"), ("reversal", "active"), ("laggard", "competition"), "弱转强或回封确认", "竞争板抢位且自身地位下降"),
    PersonaSpec("xiao_ey", "小鳄鱼", "基本面盘面共振", ("trend_up", "fundamental_proxy"), ("theme_hot", "hard_event"), ("governance_risk",), "业务证据与盘面同时增强", "纯概念冲高或基本面证据被证伪"),
    PersonaSpec("jiao_yy", "交易猿", "容量龙头加速", ("capacity", "leader"), ("strong", "near_high"), ("small_cap", "failed_acceleration"), "渡劫后再次放量确认", "加速失败并跌破上午均价"),
    PersonaSpec("mao_lb", "毛老板", "AI 主线重仓", ("ai_chain", "capacity"), ("hard_event", "leader"), ("fake_ai",), "AI 硬催化和容量承接同时成立", "仅关键词无订单或产业证据"),
    PersonaSpec("xiao_xian", "消闲派", "超预期加速", ("hard_event", "strong"), ("leader", "near_high"), ("priced_in", "laggard"), "预期上修后强度可持续", "低于预期或补涨末端"),
    PersonaSpec("lasa", "拉萨天团", "散户拥挤反向", ("crowded",), ("active",), ("climax",), "只作为拥挤观察信号", "拥挤继续上升时禁止追涨"),
    PersonaSpec("chengdu", "成都帮", "底部点火", ("low_position", "active"), ("reversal", "hard_event"), ("extended",), "低位直线放量后回踩不破", "高位接力或消息无发酵"),
    PersonaSpec("sunan", "苏南帮", "低价小盘联动", ("small_cap", "breadth"), ("low_price", "active"), ("large_cap",), "区域/题材小票同步", "大市值或只有单票异动"),
    PersonaSpec("ningbo_st", "宁波桑田路", "连板接力", ("strong", "leader"), ("active", "theme_hot"), ("failed_acceleration",), "梯队高度和换手继续确认", "断板修复弱或板块高度下降"),
    PersonaSpec("liuyi_zl", "六一中路", "题材龙头接力", ("theme_hot", "leader"), ("hard_event", "active"), ("stale_theme", "laggard"), "主线回流且龙头确认", "旧题材无回流或后排套利"),
    PersonaSpec("liu_sh", "流沙河", "分歧低吸", ("trend_up", "not_extended"), ("reversal", "active"), ("breakdown", "climax"), "分歧低吸后出现承接", "一致缩量或破位无承接"),
    PersonaSpec("gu_bl", "古北路", "活跃容量", ("active", "capacity"), ("theme_hot", "leader"), ("sample_low",), "滚动活跃且板块启动", "样本不足或板块未启动"),
    PersonaSpec("bj_cj", "北京炒家", "首板快速套利", ("mid_cap", "strong"), ("active", "fresh_theme"), ("extended", "illiquid"), "上午放量首板代理条件成立", "午后被动跟风或流动性下降"),
    PersonaSpec("wang_zr", "瑞鹤仙", "强势题材", ("strong", "active"), ("theme_hot", "leader"), ("illiquid", "climax"), "强势题材保持辨识度", "次日追高拥挤或交易活跃度下降"),
    PersonaSpec("xin_dd", "鑫多多", "困境反转", ("low_position", "reversal"), ("hard_event", "small_cap"), ("extended", "priced_in"), "低位反转催化获盘口确认", "高位纯接力或预期已兑现"),
    PersonaSpec("ghzw", "股海贼王", "主线接力与格局票", ("theme_hot", "leader"), ("active", "capacity", "hard_event"), ("laggard", "failed_acceleration"), "涨停原因、板块地位与大盘环境同时成立", "非主线、承接差或高位竞争失败"),
)

# 游资通用大市值上界 (元) (对齐 UZI seat_db.py:235)
FALLBACK_YOUZI_MAX_MCAP_YUAN = 50_000_000_000  # 500 亿元
_MEGA_CAP_ALLOWLIST = frozenset({"章盟主"})     # 可做大盘的游资

# 游资真实营业部席位速查表 (镜像自 UZI seat_db.py)
SEATS: dict[str, dict[str, Any]] = {
    "章盟主": {
        "tier": "legend",
        "style": "大资金趋势波段，格局锁仓",
        "seats": ["江苏路", "宁波彩虹北路", "延安路"],
    },
    "孙哥": {
        "tier": "legend",
        "style": "板块引导，波段锁仓",
        "seats": ["溧阳路", "上海古北路", "上海分公司"],
    },
    "赵老哥": {
        "tier": "legend",
        "style": "打板，二板定龙头",
        "seats": ["解放北路", "绍兴证券营业部", "阜成路"],
    },
    "佛山无影脚": {
        "tier": "legend",
        "style": "一日游，翘板，砸盘王",
        "seats": ["绿景路", "季华六路", "祖庙路"],
    },
    "炒股养家": {
        "tier": "legend",
        "style": "情绪揣摩，通道排板",
        "seats": ["红宝石路", "宛平南路"],
    },
    "陈小群": {
        "tier": "new_gen",
        "style": "龙头接力、一线天、反核按钮",
        "seats": ["大连黄河路"],
    },
    "呼家楼": {
        "tier": "new_gen",
        "style": "多席位协同、板块平铺扫货",
        "seats": ["上海凯滨路", "中信北京总部", "朝外大街"],
    },
    "方新侠": {
        "tier": "new_gen",
        "style": "大成交趋势票、格局锁仓",
        "seats": ["陕西分公司", "朱雀大街"],
    },
    "作手新一": {
        "tier": "new_gen",
        "style": "龙头战法，连板+趋势兼做",
        "seats": ["南京太平南路"],
    },
    "小鳄鱼": {
        "tier": "new_gen",
        "style": "主流热点题材，趋势+接力",
        "seats": ["佛山顺德", "上海浦东南路"],
    },
    "六一中路": {
        "tier": "new_2025",
        "style": "大格局引导，锁仓带动全行业",
        "seats": ["六一中路"],
    },
    "宁波桑田路": {
        "tier": "regional",
        "style": "纯连板接力，市场高标接力",
        "seats": ["桑田路"],
    },
    "拉萨天团": {
        "tier": "regional",
        "style": "散户大本营，高频做T",
        "seats": ["东环路", "团结路"],
    },
}

_AI_TERMS = (
    "AI", "人工智能", "算力", "光模块", "CPO", "半导体", "芯片", "PCB", "铜箔", "机器人",
    "液冷", "电源", "数据中心", "固态电池", "低空经济", "华为", "消费电子",
)


def match_seats_in_lhb(lhb_records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """根据龙虎榜明细匹配游资席位 (对齐 UZI seat_db.py:217)。"""
    matches: dict[str, list[dict[str, Any]]] = {}
    for nick, info in SEATS.items():
        keywords = info["seats"]
        hits = []
        for row in lhb_records:
            text = " ".join(str(v) for v in row.values())
            if any(kw in text for kw in keywords):
                hits.append(row)
        if hits:
            matches[nick] = hits
    return matches


def extract_tape_features(
    quote: dict[str, Any],
    momentum: dict[str, Any],
    market_cap: float = 0.0,
    theme_info: dict[str, Any] | None = None,
    governance_risk: bool = False,
    hard_event: bool = False,
    # ★ 20261029 审计 P1-8：市场级 risk_off（退潮/冰点）与"样本量是否充足"
    #   由调用方传入真实观测值；传不进来就是 `None`（弃权），**绝不默认 False** ——
    #   旧实现恒为 False 等于永远声称"市场没有风险、样本永远够"，这两个判据
    #   在 24 个游资画像里因此从未真正生效过。
    market_risk_off: bool | None = None,
    sample_low: bool | None = None,
) -> dict[str, bool | None]:
    """提取真实盘口博弈特征 (全面对齐 UZI 盘面微观特征集)。"""
    theme = theme_info or {}
    price = quote.get("close", 0.0)
    change_pct = quote.get("pct_chg", 0.0)
    amount = quote.get("amount", 0.0)
    high = quote.get("high", price)
    open_p = quote.get("open", price)
    pre_close = quote.get("pre_close", price)
    # ★ 20261029 审计 P1-8：换手率旧默认 3.0 —— 那是"凭空捏造的活跃度"，
    #   取不到就按 3.0 算，等于默认每只票都够活跃。现改为可缺失（None = 弃权）。
    turnover = quote.get("turnover_ratio")
    # ★ 量比改成「可缺失」语义。此前调用方把 volume_ratio 硬编码成 1.5（伪装成真实
    #   量比的假数据），且本函数对 None 会直接抛 TypeError（``None >= 1.2``）。
    #   现改为：量比不可核验时判据**弃权**——``active`` 只看换手率，不再拿假量比凑数。
    vol_ratio = momentum.get("volume_ratio")
    is_bull = momentum.get("is_bullish_ma", False)
    concepts = theme.get("concepts", [])

    concept_text = " ".join(concepts)
    ai_chain = any(term.lower() in concept_text.lower() for term in _AI_TERMS)
    near_high = bool(high and price >= high * 0.985)
    reversal = bool(open_p and pre_close and open_p < pre_close and change_pct > 1.0)

    # ★ 20261029 审计 P1-8：旧实现在无题材/概念为空时给 `leader_rank` 默认 1（= 自封龙头）、
    #   `breadth_pct` 默认 65.0（= 自封题材热度）—— 全是"没有数据就编一个好看的"。
    #   现一律取不到即 `None`（弃权）：龙头位与题材热度必须是**观测到的**，不能是假定的。
    has_theme = bool(concepts) or bool(theme.get("has_theme"))
    leader_rank = theme.get("leader_rank")
    breadth_pct = theme.get("breadth_pct")
    fresh_theme = bool(theme.get("fresh_theme", has_theme))

    # ★ 市值同理：旧实现 ``price * 1e8`` 是用股价反推市值的**凭空造数**
    #   （10 元股价 → 一律假设 10 亿市值），让"小市值偏好"判据永远成立。
    cap_val = float(market_cap) if market_cap and market_cap > 0 else None

    # 区分主板 (10%) 与双创板 (20%) 弹性空间
    ts_code = str(quote.get("ts_code", ""))
    # ★ 20261029 审计 P1-12：补 302 / 689（深市 302、沪市 689 是真实存在的双创代码段，
    #   漏了会把它们的涨跌停空间按主板 10% 算，弹性与空间板判定全错）。
    is_gem_or_star = ts_code.startswith(("300", "301", "302", "688", "689"))
    # 北交所 30%（8/4/920 段）
    if ts_code.startswith(("8", "4", "920")):
        limit_pct = 30.0
    else:
        limit_pct = 20.0 if is_gem_or_star else 10.0

    return {
        "illiquid": amount < 2e8,
        "capacity": amount >= 10e8,
        # ★ 换手率/量比双双不可核验 → ``active`` 弃权（None），不拿默认值凑数
        "active": (
            None
            if turnover is None and vol_ratio is None
            else ((turnover is not None and turnover >= 3.0)
                  or (vol_ratio is not None and vol_ratio >= 1.2))
        ),
        "trend_up": is_bull,
        "strong": change_pct >= (limit_pct * 0.4),
        "extended": change_pct >= (limit_pct * 0.95),
        "not_extended": change_pct < (limit_pct * 0.7),
        "near_high": near_high,
        "reversal": reversal,
        # ★ 龙头位/题材热度取不到 → None（弃权），不再"自封龙头 / 自封热度"
        "leader": (leader_rank <= 2) if (has_theme and leader_rank is not None) else None,
        "laggard": (leader_rank > 5) if (has_theme and leader_rank is not None) else None,
        "theme_hot": (breadth_pct >= 55.0) if (has_theme and breadth_pct is not None) else None,
        "breadth": (breadth_pct >= 65.0) if (has_theme and breadth_pct is not None) else None,
        "isolated": (breadth_pct < 40.0) if (has_theme and breadth_pct is not None) else None,
        "fresh_theme": fresh_theme,
        "stale_theme": not fresh_theme,
        # ★ 市值未知 → None（弃权），不再用 ``price * 1e8`` 反推
        "small_cap": (0 < cap_val <= 100e8) if cap_val is not None else None,
        "mid_cap": (20e8 <= cap_val <= 800e8) if cap_val is not None else None,
        "large_cap": (cap_val > 800e8) if cap_val is not None else None,
        "low_price": price <= 20.0,
        "low_position": not is_bull,
        "crowded": (turnover is not None and turnover >= 12.0) or change_pct >= (limit_pct * 0.9),
        "climax": change_pct >= (limit_pct * 0.95),
        "hard_event": hard_event and has_theme,
        "priced_in": change_pct >= (limit_pct * 0.8) and hard_event,
        "ai_chain": ai_chain,
        "fake_ai": ai_chain and not hard_event,
        "fundamental_proxy": hard_event and has_theme,
        "governance_risk": governance_risk,
        "competition": bool(
            breadth_pct is not None and leader_rank is not None
            and breadth_pct > 80.0 and leader_rank > 2
        ),
        "failed_acceleration": change_pct < 2.0 and not near_high,
        "breakdown": change_pct < -2.0,
        # ★ 由调用方给出真值；None = 不可核验（弃权），不再是恒 False 的假事实
        "risk_off": market_risk_off,
        "sample_low": sample_low,
        "_market_cap": cap_val,
    }


def evaluate_youzi_personas(features: dict[str, Any]) -> list[dict[str, Any]]:
    """针对标的特征严格比对 24 大顶级游资战法规则 (一票否决 + 必备项校验 + 500亿市值上限)。"""
    matched: list[dict[str, Any]] = []
    cap_val = float(features.get("_market_cap") or 0.0)

    for spec in F_PERSONAS:
        # 0. 500 亿大市值上限 (对齐 UZI seat_db.py:255)
        if cap_val > FALLBACK_YOUZI_MAX_MCAP_YUAN and spec.name not in _MEGA_CAP_ALLOWLIST:
            continue

        # 1. 一票否决检查
        vetoed = False
        for veto_k in spec.veto_rules:
            if features.get(veto_k) is True:
                vetoed = True
                break
        if vetoed:
            continue

        # 2. 必备项检查 (必须全为 True)
        missing_must = False
        for must_k in spec.must_have:
            if features.get(must_k) is not True:
                missing_must = True
                break
        if missing_must:
            continue

        # 3. 加分项匹配数
        pos_matches = [k for k in spec.positive_patterns if features.get(k) is True]
        fit_score = len(pos_matches) * 20 + 60

        matched.append({
            "investor_id": spec.investor_id,
            "youzi_name": spec.name,
            "style": spec.style,
            "fit_score": fit_score,
            "matched_patterns": pos_matches,
            "entry_condition": spec.entry_condition,
            "invalidation": spec.invalidation,
            "horizon": spec.horizon,
        })

    # 按匹配拟合度排序
    return sorted(matched, key=lambda x: x["fit_score"], reverse=True)
