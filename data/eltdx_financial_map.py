"""eltdx → Tushare 三表字段定标表（★ 三套编号空间互不通用）。

## 为什么是三张表而不是一张

M3 实测定档后发现，三张报表走的是**两个不同的数据源**，编号体系彼此独立：

| 报表 | 通路 | 编号空间 |
|---|---|---|
| 利润表 `income` | 专业财务 zip（`eltdx_financial`） | **整数下标** `[73]` |
| 资产负债表 `balancesheet` | F10 `finance_report("zcfzb")` | **T 编号** `T039` |
| 现金流量表 `cashflow` | F10 `finance_report("xjllb")` | **T 编号** `T017` |

★ 最要命的一点：**`xjllb` 的 T 编号与 `zcfzb` 是两套体系**。`xjllb.T008` 是
「销售商品收到的现金」34.89 亿，而 `zcfzb.T008` 是「交易性金融资产」——
数字不同、科目不同，只有编号长得像。所以这三张映射**绝不能合并成一张**。

## 定标方法（不是猜的）

全部条目来自 `reports/m4_tushare_calibrate.log`：
取 Tushare 同一家公司同一期的三表真值，在 eltdx 的字段里找数值吻合的位置，
要求 **≥3 只票 × 多期全部命中同一个位置** 且命中率 ≥80% 才入库。
注释里的 `n/N` 就是命中数/有效数据点数。

消歧：`operate_profit` 与 `total_profit` 在无营业外收支的公司里**完全相等**，
直接反查必然撞车 —— 定标时会丢弃"该点上本字段与同表其它字段同值"的数据点，
只留下真正有区分度的样本。这就是为什么这两个科目能干净地分开（[85] 与 [91]）。

## 定标推翻的旧结论（留痕，防止被改回去）

M0 阶段靠"年报附注逐笔核对"标过几个科目，本轮用 Tushare 真值**推翻了 4 处**：

| 下标 | M0 旧结论 | 实测结论 | 证据 |
|---|---|---|---|
| `[74]` | 主营业务利润 | **营业成本 `oper_cost`** | 12/12 |
| `[77]` | 归母所有者权益 | **管理费用 `admin_exp`** | 12/12 |
| `[82]` | 营业利润 | **投资收益 `invest_income`** | 12/12 |
| `[85]` | 利润总额 | **营业利润 `operate_profit`** | 12/12 |

利润表整体**串了一位**：营业利润→投资收益、利润总额→营业利润。
如果照旧结论喂给审计框架，`op_to_ebt`、`invest_income` 相关探针会全部算错，
而且**不会报错** —— 这就是为什么定标必须用真值对拍而不是靠位置推测。

## 纪律

1. **取不到的字段一律 `None`，绝不填 0** —— 填 0 会变成"该公司股息率为 0"这种假事实，
   比缺失危险得多。缺失统一由附录 E「数据来源与信息缺口」标注。
2. **未确认的科目不进表** —— 宁可空着。下面表里没出现的 Tushare 字段
   （`total_cogs` `assets_impair_loss` `ebit` `ebitda` `adv_receipts` `deferred_inc`
   `bond_payable` `oth_payable` `proc_issue_bonds` 等）就是没定出来的，不是漏写。
3. 定标结论改动必须同步改 `scripts/tests/test_eltdx_financial_map.py`。
"""
from __future__ import annotations

from collections import Counter

# 专业财务 zip 的字段总数（全市场统一，2022–2025 年报期实测一致）
FIELD_COUNT = 584

# ---------------------------------------------------------------- 利润表（zip 下标）
INCOME_MAP: dict[int, tuple[str, str | None]] = {
    0:   ("基本每股收益", "basic_eps"),                      # 5/5
    500: ("稀释每股收益", "diluted_eps"),                    # 5/5
    73:  ("营业收入", "revenue"),                            # 12/12
    74:  ("营业成本", "oper_cost"),                          # 12/12（★ 推翻旧「主营业务利润」）
    75:  ("税金及附加", "biz_tax_surchg"),                    # 12/12
    76:  ("销售费用", "sell_exp"),                            # 12/12
    77:  ("管理费用", "admin_exp"),                           # 12/12（★ 推翻旧「归母权益」）
    79:  ("财务费用", "fin_exp"),                             # 12/12
    81:  ("公允价值变动收益", "fv_value_chg_gain"),            # 12/12
    82:  ("投资收益", "invest_income"),                       # 12/12（★ 推翻旧「营业利润」）
    83:  ("其中:对联营和合营企业的投资收益", "ass_invest_income"),  # 10/10
    85:  ("营业利润", "operate_profit"),                      # 5/5（★ 推翻旧「利润总额」）
    87:  ("营业外收入", "non_oper_income"),                    # 12/12
    88:  ("营业外支出", "non_oper_exp"),                       # 12/12
    91:  ("利润总额", "total_profit"),                        # 5/5
    92:  ("所得税费用", "income_tax"),                        # 12/12
    94:  ("净利润", "n_income"),                              # 10/10
    95:  ("归属于母公司股东的净利润", "n_income_attr_p"),        # 10/10
    96:  ("少数股东损益", "minority_gain"),                    # 12/12
    303: ("研发费用", "rd_exp"),                              # 11/12
}

# ---------------------------------------------------------------- 资产负债表（zcfzb T 编号）
BALANCE_MAP: dict[str, tuple[str, str | None]] = {
    "T007": ("货币资金", "money_cap"),                        # 12/12
    "T010": ("应收账款", "accounts_receiv"),                  # 12/12
    "T011": ("预付款项", "prepayment"),                       # 12/12
    "T012": ("其他应收款", "oth_receiv"),                      # 12/12
    "T016": ("存货", "inventories"),                          # 12/12
    "T019": ("其他流动资产", "oth_cur_assets"),                # 12/12
    "T020": ("流动资产合计", "total_cur_assets"),              # 12/12
    "T024": ("长期股权投资", "lt_eqt_invest"),                # 10/10
    "T026": ("固定资产", "fix_assets"),                       # 12/12
    "T027": ("在建工程", "cip"),                              # 10/10
    "T032": ("无形资产", "intan_assets"),                     # 12/12
    "T034": ("商誉", "goodwill"),                             # 9/9
    "T036": ("递延所得税资产", "defer_tax_assets"),            # 12/12
    "T038": ("非流动资产合计", "total_nca"),                   # 12/12
    "T039": ("资产总计", "total_assets"),                     # 12/12
    "T040": ("短期借款", "st_borr"),                          # 6/6
    "T042": ("应付票据", "notes_payable"),                    # 6/6
    "T043": ("应付账款", "acct_payable"),                     # 12/12
    "T045": ("应付职工薪酬", "payroll_payable"),               # 12/12
    "T046": ("应交税费", "taxes_payable"),                    # 12/12
    "T051": ("一年内到期的非流动负债", "non_cur_liab_due_1y"),   # 12/12
    "T052": ("其他流动负债", "oth_cur_liab"),                  # 12/12
    "T053": ("流动负债合计", "total_cur_liab"),                # 12/12
    "T054": ("长期借款", "lt_borr"),                          # 6/6
    "T056": ("长期应付款", "lt_payable"),                      # 5/5
    "T059": ("递延所得税负债", "defer_tax_liab"),              # 12/12
    "T060": ("其他非流动负债", "oth_ncl"),                     # 4/4
    "T061": ("非流动负债合计", "total_ncl"),                   # 12/12
    "T062": ("负债合计", "total_liab"),                       # 12/12
    "T063": ("总股本", "total_share"),                        # 12/12
    "T064": ("资本公积", "cap_rese"),                         # 12/12
    "T065": ("盈余公积", "surplus_rese"),                     # 12/12
    "T067": ("未分配利润", "undistr_porfit"),                  # 12/12
    # ★ T068 有冲突：finance_batch 的「长期负债合计」在 3/4 只票上命中它，
    #   但 Tushare 的 minority_int 是 10/10。按「命中数更高者胜」取少数股东权益，
    #   并由恒等式 权益合计(T071) = 归母(T077) + 少数股东(T068) 兜底校验。
    "T068": ("少数股东权益", "minority_int"),                  # 10/10
    "T071": ("所有者权益合计", "total_hldr_eqy_inc_min_int"),  # 10/10
    "T077": ("归属于母公司股东权益合计", "total_hldr_eqy_exc_min_int"),  # 10/10
    "T083": ("递延收益(非流动)", "defer_inc_non_cur_liab"),     # 9/9
    "T119": ("合同负债", "contract_liab"),                    # 12/12
}

# ---------------------------------------------------------------- 现金流量表（xjllb T 编号）
CASHFLOW_MAP: dict[str, tuple[str, str | None]] = {
    "T008": ("销售商品、提供劳务收到的现金", "c_fr_sale_sg"),     # 12/12
    "T012": ("购买商品、接受劳务支付的现金", "c_paid_goods_s"),   # 12/12
    "T013": ("支付给职工以及为职工支付的现金", "c_paid_to_for_empl"),  # 12/12
    "T014": ("支付的各项税费", "c_paid_for_taxes"),              # 12/12
    "T017": ("经营活动产生的现金流量净额", "n_cashflow_act"),      # 12/12
    "T018": ("收回投资收到的现金", "c_disp_withdrwl_invest"),     # 12/12
    "T019": ("取得投资收益收到的现金", "c_recp_return_invest"),   # 12/12
    "T024": ("购建固定资产无形资产及其他长期资产支付的现金",
             "c_pay_acq_const_fiolta"),                          # 12/12
    "T025": ("投资支付的现金", "c_paid_invest"),                 # 12/12
    "T029": ("投资活动产生的现金流量净额", "n_cashflow_inv_act"),  # 12/12
    "T031": ("取得借款收到的现金", "c_recp_borrow"),              # 6/6
    "T034": ("偿还债务支付的现金", "c_prepay_amt_borr"),          # 6/6
    "T035": ("分配股利、利润或偿付利息支付的现金",
             "c_pay_dist_dpcp_int_exp"),                          # 11/12
    "T038": ("筹资活动产生的现金流量净额", "n_cash_flows_fnc_act"),  # 12/12
    "T041": ("现金及现金等价物净增加额", "n_incr_cash_cash_equ"),  # 12/12
    "T042": ("期初现金及现金等价物余额", "c_cash_equ_beg_period"), # 12/12
    "T043": ("期末现金及现金等价物余额", "c_cash_equ_end_period"), # 12/12
    "T046": ("净利润", "net_profit"),                            # 12/12
    "T047": ("资产减值准备", "prov_depr_assets"),                 # 8/9
    "T048": ("固定资产折旧、油气资产折耗、生产性生物资产折旧",
             "depr_fa_coga_dpba"),                               # 11/12
    "T049": ("无形资产摊销", "amort_intang_assets"),              # 12/12
    "T054": ("财务费用", "finan_exp"),                            # 12/12
    "T058": ("存货的减少", "decr_inventories"),                   # 12/12
    "T059": ("经营性应付项目的减少", "decr_oper_payable"),         # 12/12
    "T060": ("经营性应付项目的增加", "incr_oper_payable"),         # 12/12
    "T098": ("信用减值损失", "credit_impa_loss"),                 # 7/7
}

# ---------------------------------------------------------------- zip 空间的资产负债科目
# 备用通路：专业财务 zip 里也有资产负债科目（下标与 zcfzb 的 T 编号同源），
# 走 zip 时用这张表。日常取数走上面的 BALANCE_MAP（F10 更轻）。
BALANCE_ZIP_MAP: dict[int, tuple[str, str | None]] = {
    7:   ("货币资金", "money_cap"),
    8:   ("交易性金融资产", None),           # Tushare core 无对应列
    9:   ("应收票据", None),                 # Tushare core 无对应列
    10:  ("应收账款", "accounts_receiv"),
    16:  ("存货", "inventories"),
    20:  ("流动资产合计", "total_cur_assets"),
    24:  ("长期股权投资", "lt_eqt_invest"),
    26:  ("固定资产", "fix_assets"),
    27:  ("在建工程", "cip"),
    32:  ("无形资产", "intan_assets"),
    38:  ("非流动资产合计", "total_nca"),
    39:  ("资产总计", "total_assets"),
    40:  ("短期借款", "st_borr"),
    42:  ("应付票据", "notes_payable"),
    43:  ("应付账款", "acct_payable"),
    53:  ("流动负债合计", "total_cur_liab"),
    60:  ("其他非流动负债", "oth_ncl"),
    62:  ("负债合计", "total_liab"),
    63:  ("总股本", "total_share"),
    64:  ("资本公积", "cap_rese"),
    67:  ("未分配利润", "undistr_porfit"),
    71:  ("所有者权益合计", "total_hldr_eqy_inc_min_int"),
    72:  ("负债和股东权益合计", None),        # Tushare 无此列，留作恒等式校验用
    119: ("合同负债", "contract_liab"),
}

# 兼容旧接口的合并视图（zip 空间全量）
FIELD_MAP: dict[int, tuple[str, str | None]] = {**BALANCE_ZIP_MAP, **INCOME_MAP}


# ---------------------------------------------------------------- 反查
def index_of(tushare_column: str) -> int | None:
    """按 Tushare 列名反查 zip 下标（同一列被多个下标占用时取最小的）。"""
    hits = [i for i, (_cn, col) in FIELD_MAP.items() if col == tushare_column]
    return min(hits) if hits else None


def tushare_column_of(index: int) -> str | None:
    """zip 下标 → Tushare 列名；未定标返回 None。"""
    item = FIELD_MAP.get(index)
    return item[1] if item else None


# ---------------------------------------------------------------- 记录转换
def _to_record(values, mapping, cast) -> dict[str, float]:
    """通用的「按映射表取值」：只输出已定标的列，未定标的**丢弃**而不是塞 None。"""
    out: dict[str, float] = {}
    for key, (_cn, col) in mapping.items():
        if not col:
            continue
        raw = values[key] if _has(values, key) else None
        v = cast(raw)
        if v is not None:
            out[col] = v
    return out


def _has(values, key) -> bool:
    try:
        values[key]
        return True
    except (KeyError, IndexError, TypeError):
        return False


def _num(v) -> float | None:
    if v is None:
        return None
    try:
        s = str(v).strip()
        if not s or s in ("None", "nan", "-", "---"):
            return None
        return float(s)
    except (TypeError, ValueError):
        return None


def to_record(fields) -> dict[str, float]:
    """zip 字段数组 → {Tushare 列名: 值}（利润表 + 资产负债表混合视图）。"""
    return _to_record(fields, FIELD_MAP, _num)


def to_income_record(fields) -> dict[str, float]:
    """zip 字段数组 → 利润表记录。"""
    return _to_record(fields, INCOME_MAP, _num)


def to_balance_record(row: dict) -> dict[str, float]:
    """F10 zcfzb 的一行 → 资产负债表记录。"""
    return _to_record(row, BALANCE_MAP, _num)


def to_cashflow_record(row: dict) -> dict[str, float]:
    """F10 xjllb 的一行 → 现金流量表记录。"""
    return _to_record(row, CASHFLOW_MAP, _num)


def period_of(row: dict) -> str | None:
    """从 F10 行取报告期（YYYYMMDD）；F10 返回的是 `2025-12-31` 形式。"""
    rq = row.get("rq") if isinstance(row, dict) else None
    if rq is None:
        return None
    return str(rq).replace("-", "").strip() or None


# ---------------------------------------------------------------- 恒等式自检
# 格式：(标签, 左列, 右列列表)；左 ≈ 右之和 视为成立
IDENTITIES = (
    ("资产总计 == 负债合计 + 所有者权益合计", "total_assets",
     ("total_liab", "total_hldr_eqy_inc_min_int")),
    ("负债和股东权益合计 == 资产总计", "total_assets", ("total_assets",)),
    ("所有者权益合计 == 归母权益 + 少数股东权益", "total_hldr_eqy_inc_min_int",
     ("total_hldr_eqy_exc_min_int", "minority_int")),
)

_TOLERANCE = 0.002          # 0.2%：float32 精度 + 报表四舍五入都远小于此


def check_identities(record) -> list[tuple[str, bool, float]]:
    """对一条记录做会计恒等式自检。返回 [(标签, 是否成立, 相对差)]。

    这是**发现映射错位最有效的手段**：科目定错了，恒等式几乎立刻不成立，
    而数值本身看着完全正常。

    入参既可以是已转换好的 `{Tushare 列名: 值}`，也可以是原始的 zip 字段数组
    （内部先过一遍 `to_record`）—— 调用方手上是哪一种都别让它崩。
    """
    if not isinstance(record, dict):
        record = to_record(record)
    out: list[tuple[str, bool, float]] = []
    for label, left, rights in IDENTITIES:
        lv = record.get(left)
        parts = [record.get(r) for r in rights]
        if lv is None or any(p is None for p in parts):
            continue
        rv = sum(p for p in parts if p is not None)
        denom = max(abs(lv), abs(rv), 1.0)
        rel = abs(lv - rv) / denom
        out.append((label, rel <= _TOLERANCE, rel))
    return out


def check_balance_identities(row: dict) -> list[tuple[str, bool, float]]:
    """对 F10 zcfzb 的一行做恒等式自检（走 BALANCE_MAP）。"""
    return check_identities(to_balance_record(row))


# ---------------------------------------------------------------- 金融股模板识别
def looks_like_financial_template(fields) -> bool:
    """★ 金融股另用一套 F10 列模板，明细列会全 0 但汇总列有值。

    平安银行实测：流动资产/存货/应收账款全是 0（不是真为 0，是模板不同）。
    不识别出来就拿去算流动比率，会得出 0，进而触发一堆**假红旗**。
    """
    if not fields:
        return False
    total = _num(fields[39]) if _has(fields, 39) else None
    if not total:
        return False                      # 连资产总计都没有 → 是"没数据"，不是金融模板
    detail_idx = (10, 16, 20, 38, 53)     # 应收 / 存货 / 流动资产 / 非流动资产 / 流动负债
    vals = [_num(fields[i]) if _has(fields, i) else None for i in detail_idx]
    if all(v is None for v in vals):
        return False
    return all(not v for v in vals if v is not None)


def looks_like_financial_row(row: dict) -> bool:
    """同上，但针对 F10 `zcfzb` 的一行（键是 T 编号）。"""
    if not row:
        return False
    total = _num(row.get("T039"))
    if not total:
        return False
    detail = ("T010", "T016", "T020", "T038", "T053")
    vals = [_num(row.get(k)) for k in detail]
    if all(v is None for v in vals):
        return False
    return all(not v for v in vals if v is not None)


# ---------------------------------------------------------------- 覆盖率
def coverage_report() -> str:
    """人类可读的定标覆盖率报告（给迁移计划 / 交接用）。"""
    lines = [
        "eltdx → Tushare 三表字段定标覆盖率",
        "-" * 62,
        f"  利润表 income 已确认科目      : {len(INCOME_MAP):>3} 个（zip 下标）",
        f"  资产负债表 balance 已确认科目 : {len(BALANCE_MAP):>3} 个（zcfzb T 编号）",
        f"  现金流量表 cashflow 已确认科目: {len(CASHFLOW_MAP):>3} 个（xjllb T 编号）",
        f"  专业财务 zip 总数  : {FIELD_COUNT} 个字段",
        "",
        "未确认（定不出来，保持空缺，绝不填 0）:",
    ]
    for api, got in (("income", {c for _cn, c in INCOME_MAP.values() if c}),
                     ("balancesheet", {c for _cn, c in BALANCE_MAP.values() if c}),
                     ("cashflow", {c for _cn, c in CASHFLOW_MAP.values() if c})):
        pass
    lines.append("  income: total_revenue / total_cogs / assets_impair_loss / "
                 "credit_impa_loss / ebit / ebitda")
    lines.append("  balance: adv_receipts / contract_assets / deferred_inc / "
                 "oth_payable / bond_payable")
    lines.append("  cashflow: free_cashflow（可自算）/ proc_issue_bonds")

    dupes = [c for c, n in Counter(
        [c for _cn, c in INCOME_MAP.values() if c]).items() if n > 1]
    dupes += [c for c, n in Counter(
        [c for _cn, c in BALANCE_MAP.values() if c]).items() if n > 1]
    dupes += [c for c, n in Counter(
        [c for _cn, c in CASHFLOW_MAP.values() if c]).items() if n > 1]
    lines.append("")
    lines.append(f"  重复列名: {dupes or '无'}")
    return "\n".join(lines)


def entry() -> dict:
    """给 check_env / 自检脚本用的摘要。"""
    return {
        "income_mapped": len([c for _cn, c in INCOME_MAP.values() if c]),
        "balance_mapped": len([c for _cn, c in BALANCE_MAP.values() if c]),
        "cashflow_mapped": len([c for _cn, c in CASHFLOW_MAP.values() if c]),
        "field_count": FIELD_COUNT,
    }
