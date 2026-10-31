---
name: batch1-acceptance-backfill
overview: 实施「未实施工作清单」第一批（验收补齐）：双档仓位上限、两个死配置接线、死参数清理、Lint 补 3 条高价值硬规则、造假样本用例强化、换手率阈值对齐 SRS、文档同步。全部为本地可完成、无外部数据依赖的改动。
todos:
  - id: e1-position-cap
    content: 用 [subagent:code-explorer] 核实置信度可达性，实施 E-1 双档仓位上限（config + judgment_chain + execution_playbook）
    status: completed
  - id: e2e3-dead-config
    content: 接线 E-2 左尾腰斩与 E-3 预告变脸量化判据，并核实 forecast 数据源、必要时补采集通道
    status: completed
  - id: e4-persona-wiring
    content: 把 execution_playbook 的 matched_personas 死参数按 SEATS style/tier 接线为防砸与挂单区间信号
    status: completed
    dependencies:
      - e1-position-cap
  - id: c1-lint-rules
    content: 在 lint/validator.py 补 R10 伪造默认值、R11 单点真理越界、R12 算术闭合三条硬规则并标注 R1-R6 未实现
    status: completed
    dependencies:
      - e1-position-cap
  - id: c3-fraud-tests
    content: 扩展 tests/test_audit.py 合成造假样本覆盖度并写死阈值断言，注明为合成数据
    status: completed
  - id: c7-doc-sync
    content: 换手率对齐 8%~25%，同步 README/ARCHITECTURE 测试数量与目录索引，回写未实施清单状态
    status: completed
    dependencies:
      - c1-lint-rules
      - c3-fraud-tests
  - id: batch1-regression
    content: 编写 tests/test_batch1_backfill.py 并跑全量 pytest 至 124 passed，输出变更清单与验证方式
    status: completed
    dependencies:
      - e1-position-cap
      - e2e3-dead-config
      - e4-persona-wiring
      - c1-lint-rules
      - c3-fraud-tests
      - c7-doc-sync
---

## 产品概述

对 AST-Trader 的「未实施工作清单」第一批（验收补齐）逐项落地，消除已确认的风险敞口与需求冲突。

## 核心功能

1. **双档仓位上限**：`MAX_SINGLE_POSITION=0.20` 作为常规上限、新增 `0.25` 作为极端情形上限，由主力引擎置信度决定取哪一档；同时消除 `execution_playbook` 中脱离卡面与配置的硬编码 25%。
2. **两个死配置接线**：`LEFT_TAIL_WARN_THRESHOLD`（左尾回撤腰斩至 10%）、`FORECAST_DROP_FATAL_RATIO`（预告扣非同比下滑超 50% 致命），并核实预告数据是否真有数据源，避免重演「规则写了但空转」。
3. **死参数接线**：`execution_playbook.build(matched_personas)` 由未使用改为基于游资 `style/tier` 影响挂单区间与防砸提示。
4. **Lint 补 3 条高价值硬规则**：伪造默认值、单点真理越界、算术闭合；R1-R6 保留编号空位并在文档中说明未实现。
5. **造假样本用例强化**：扩展现有合成三表数据覆盖度并写死阈值断言，不引入康美药业名义。
6. **阈值与文档对齐**：换手率对齐 SRS 的 8%~25%；同步测试数量与目录索引；回写未实施清单状态。

## 验收口径

全部改动完成后 `python -m pytest -q` 必须为 124 passed（不得以减少断言换取通过）。

## 技术栈

沿用项目现状：Python 3.13 + pandas + pytest；配置集中于 `config.py`；`lint/validator.py` 保持纯叶子层（仅本地 `LEVEL_FATAL` 常量，不得反向依赖 `core.red_flags`）；测试沿用既有合成 DataFrame 构造风格。

## 实施策略

### 总原则

以「单点真理 + 数据纪律」为准绳：阈值一律收敛进 `config.py`，业务代码不再出现裸数字；缺失值一律 `None`，严禁 `0` 兜底。每项改动都配套可独立失败的回归用例。

### 逐项设计

**E-1 双档仓位上限**

- 需先更正上一轮清单的一处表述：`main_force_engine` 各阶段 `suggested_pos_cap` 取值域为 `{0.0, 0.10, 0.15, 0.20}`，因此 `judgment_chain.py:612` 的 `min(0.25, mf_cap)` 实际永不生效，有效上限本就是 20%；真正脱离配置、存在敞口的是 `execution_playbook.py:61` 的 `max_pos = 25`。两处都要改，并在交付说明中如实区分。
- `config.py` 新增：`MAX_SINGLE_POSITION_EXTREME = 0.25`（极端上限）、`POSITION_EXTREME_MIN_CONFIDENCE = 90.0`（触发极端档的置信度门槛）、`POSITION_EXTREME_MIN_STAGE_CAP = 0.20`（主力引擎自身 cap 需达到的门槛）。
- `judgment_chain._decide_gear`：新增内部函数按 `(mf_cap, 主力置信度, 是否致命红旗/降级)` 选择档位，替换 `:612`、`:627` 的裸 `0.25/0.20/0.10/0.08`。
- `execution_playbook.build`：BUY 分支的 `base/add/max` 不再硬编码，改为接收 `position_cap`（小数）换算为百分点，并以同一双档上限封顶；`matched_personas` 同批接线。
- 需要确认 `mf_cap` 与 `final_confidence` 是否同时可达 `_decide_gear`（`judgment_chain.py:453` 只取了 `suggested_pos_cap`），若不可达则在 `micro` 透传 `confidence`。

**E-2 / E-3 死配置接线**

- E-2：在 `_decide_gear` 中读取左尾回撤指标（需先确认 `microstructure`/`main_force_engine` 已产出该项；若字段名不同则以实际字段为准），超过 `LEFT_TAIL_WARN_THRESHOLD` 则把该分支仓位腰斩至 `MAX_SINGLE_POSITION / 2`。
- E-3：`_check_forecast_anomaly` 增加量化判据——当 `p_change_min`（或 `p_change_max`，取更保守者）低于 `FORECAST_DROP_FATAL_RATIO` 时，给出致命红旗。
- **关键前置核查**：全仓检索确认 `gov["forecast"]` 当前是否有数据源填充（初步检索 `data/` 下无任何 `forecast` 产出）。若无，则仿照 P0-3 的教训，在 `eltdx_collector` 用 `f10.profit_forecast` 补齐，否则规则仍为空转；若该通道不可用，则在代码中显式标注「规则已实现、待数据源」，并记入清单，不伪装为已生效。

**E-4 死参数接线**

- `core/youzi_personas.py` 的 `SEATS` 已含 `tier` 与 `style`（如「一日游，翘板，砸盘王」「散户大本营，高频做T」），`evaluate_youzi_personas` 返回项含 `style`/`fit_score`。
- 保持 `matched_personas: list[str]` 签名不变（避免影响 `rank_composite.py:124` 与既有用例），在 `build()` 内按名称查 `SEATS`，命中「砸盘/一日游/散户拥挤」类时：挂单区间下移、加防砸提示、收紧止损表述；其余情形保持现有行为，确保 `test_uzi_features.py`、`test_html.py` 不变红。

**C-1 Lint 补 3 条硬规则**

- **R10 伪造默认值检查**：校验 `quality_verdict`/`odds_verdict`/`state_verdict`/`path_verdict` 是否落在各自合法取值域白名单内（与 `judgment_chain` 中已建立的 `QUALITY_VERDICT_GOOD`/`ODDS_VERDICT_GOOD` 同源取值域）。这是「缺失特征自动弃权」的可机检化实现，且不会误伤。
- **R11 单点真理越界**：在 R8 之外，检查 `pillar_1/pillar_2` 正文中是否出现仓位百分比表述。**刻意避开 `pillar_4`**（路径正文含止损价位属合理），避免误报。
- **R12 算术闭合**：`position_cap` 与 `pillar_5_decision.position_cap` 必须一致；`derivation` 存在时 `sotp_ps <= dcf_ps` 且均为正；`price > 0`。
- **误报控制（主要风险）**：`audit_engine` 仍有 30+ 处 `, 0)` 兜底未清理（属 C-5，本批不处理），因此 R10 **禁止**扫描全卡数值字段判定「是否为 0」，只校验枚举取值域；R11 只针对两块正文；R12 只校验三处一致性。并在 `validator.py` 顶部写明范围边界。
- R1-R6 保留空位：在 `validator.py` 加注释说明「SRS FR-05 承诺 12 条，当前实现 R7/R8/R9/R10/R11/R12/R13 共 7 条，R1-R6 无定义、未实现」，并在清单文档中记录。

**C-3 造假样本用例**

- 扩展 `tests/test_audit.py`：构造具备典型造假特征的三表（营收增长但经营现金流长期为负、应收增速远超营收、应计异象超阈值、商誉与存货畸高），断言 Beneish / Sloan / Buffett 现金流背离均触发致命或高危，并把阈值写成模块级常量引用 `config`，杜绝 `if...else` 伪用例。用例注释中明确标注为合成数据、非真实公司数据。

**C-7 / F-1 / F-2 阈值与文档**

- `config.py:46-47` 改为 `8.0` / `25.0`，注释补明「对齐 SRS FR-06」；检查 `filter_liquidity.py:57` 注释中的 `7%~28%` 一并更新。
- `README.md:126`、`docs/ARCHITECTURE.md:171` 的「74 项」改为 124 项并注明构成。
- `README.md:78-117` 目录索引补齐 `core/industry.py`、`core/investor_panel.py`、`core/types.py`、`data/eltdx_units.py`、`data/eltdx_financial.py`、`data/eltdx_financial_map.py`、`tests/seed_universe.py`、`tests/conftest.py`、`tests/helpers_seed.py`、`tests/test_p0_fixes.py`。
- 在 `docs/SEED_VALIDATION_REPORT.md` 或新建跟踪表中把本批条目状态改为已实施，并保留 E/C 类未完成项。

## 架构与目录

```
d:/workspace/ast-trader/
├── config.py                          # [MODIFY] 新增 MAX_SINGLE_POSITION_EXTREME、
│                                      #   POSITION_EXTREME_MIN_CONFIDENCE、
│                                      #   POSITION_EXTREME_MIN_STAGE_CAP；
│                                      #   MOMENTUM_MIN/MAX_TURNOVER_RATE 改 8.0/25.0
├── core/
│   ├── judgment_chain.py              # [MODIFY] _decide_gear 双档上限 + 左尾腰斩；
│   │                                  #   透传主力置信度（若当前未透传）
│   ├── execution_playbook.py          # [MODIFY] build() 仓位由入参 position_cap 换算并
│   │                                  #   受双档上限约束；matched_personas 接线
│   │                                  #   （基于 youzi_personas.SEATS 的 style/tier）
│   └── audit_engine.py                # [MODIFY] _check_forecast_anomaly 接入
│                                      #   FORECAST_DROP_FATAL_RATIO 量化判据
├── data/
│   └── eltdx_collector.py             # [MODIFY] 若 forecast 无数据源，用
│                                      #   f10.profit_forecast 补齐（含 health 记录）
├── lint/
│   └── validator.py                   # [MODIFY] 新增 R10/R11/R12；补 R1-R6 未实现说明
├── tests/
│   ├── test_audit.py                  # [MODIFY] 强化合成造假样本与阈值断言
│   ├── test_lint.py                   # [MODIFY] 新增 R10/R11/R12 正向与反向用例
│   └── test_batch1_backfill.py        # [NEW] 本批专属回归：双档上限、左尾腰斩、
│                                      #   预告变脸、persona 接线、换手率阈值
├── README.md                          # [MODIFY] 测试数量 124、目录索引补齐
├── docs/ARCHITECTURE.md               # [MODIFY] 测试数量 124
└── docs/SEED_VALIDATION_REPORT.md     # [MODIFY] 回写第一批条目状态
```

## 关键代码结构

```python
# config.py —— 仓位双档上限（唯一真值来源）
MAX_SINGLE_POSITION = 0.20            # 常规单票上限
MAX_SINGLE_POSITION_EXTREME = 0.25    # 极端情形上限（需同时满足下列两项）
POSITION_EXTREME_MIN_CONFIDENCE = 90.0   # 主力引擎置信度门槛
POSITION_EXTREME_MIN_STAGE_CAP = 0.20    # 主力引擎自身建议仓位门槛
LEFT_TAIL_WARN_THRESHOLD = 0.25       # 左尾回撤超此值 → 仓位腰斩
FORECAST_DROP_FATAL_RATIO = -0.50     # 预告扣非同比下限（低于即致命）
```

```python
# core/judgment_chain.py —— 档位选择（替换 :612/:627 的裸数字）
def _resolve_position_cap(
    mf_cap: float | None,
    stage_confidence: float | None,
    *,
    small_track: bool = False,
    degraded: bool = False,
) -> float:
    """按主力置信度在常规档/极端档之间选择仓位上限；降级时恒为 0。"""
```

```python
# lint/validator.py —— 新增三条，findings 仅收阻断级
def _check_r10_verdict_domain(self, card: dict[str, Any]) -> list[str]: ...
def _check_r11_single_truth_leak(self, card: dict[str, Any]) -> list[str]: ...
def _check_r12_arithmetic_closure(self, card: dict[str, Any]) -> list[str]: ...
```

## 实施要点（防回归）

- **顺序**：先改 `config.py` 与 `judgment_chain/execution_playbook` 的仓位口径，再补 Lint——因为 Lint 的 R12 会校验 `position_cap` 一致性，顺序颠倒会造成连锁失败。
- **不触碰**：C-5（`audit_engine` 30+ 处 0 兜底）、C-6（`LintError` 抛异常口径）、D-2（北交所档位）、D-3（Tier 2 只审前 15 只）均属后续批次，本批保持原状，仅在文档中标注。
- **Blast radius**：`execution_playbook.build()` 签名如需新增 `position_cap` 参数，须给默认值以兼容 `tests/test_uzi_features.py`、`tests/test_html.py` 的现有调用。
- **性能**：Lint 新增三条均为纯字典/字符串校验，无 IO、无遍历放大，对单股 2 秒与全市场 15 秒预算无可观测影响。
- **验证纪律**：每条规则与每档上限都要有「正向命中」与「反向不误报」两类断言；允许通过放宽测试，禁止通过删断言。

## Agent Extensions

### SubAgent

- **code-explorer**
- Purpose：在实施前复核两类事实——(1) `mf_cap` 与主力置信度是否同时可达 `_decide_gear`；(2) `gov["forecast"]` 是否真有数据源填充，以及 `eltdx.f10.profit_forecast` 是否可用。
- Expected outcome：给出明确的文件:行号证据，决定 E-1 是否需要透传 `confidence`、E-3 是否需要补采集通道，避免规则实现后空转。