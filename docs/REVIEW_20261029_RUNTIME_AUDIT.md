# AST-Trader 架构与实战性审查报告（含 eltdx 运行时实证）—— **修复后复审版 v2**

> 首审：2026-10-29　　**复审：2026-10-30**
> 审查方式：静态代码走查 + **本机安装 eltdx 3.3.0 后的真实数据运行验证** + 修复后二次运行复验
> 数据基准日：2026-10-29 收盘（2026-10-30 盘前复验）　　样本：贵州茅台 600519 / 工商银行 601398 / 和泰机电 001225 / 巴比食品 605338 等
> 结论口径：本文所有数字均为**实测值**。凡未实测的，一律标注「静态推断」。
>
> **v2 说明**：首审列出 4 个 P0 / 14 个 P1 / 13 个 P2。修复波次共改动 45 个源文件（2026-10-29 20:30 → 2026-10-30 01:31）。
> 本版对每一条给出**复审状态**（✅已修 / ⚠️部分修复 / ❌未修）与**复验证据**，并记录复审中**新发现的 3 个回归缺陷**与**1 处首审误判更正**。

---

## 0. 审查环境

| 项 | 值 |
|---|---|
| Python | 3.13.13 |
| eltdx | 3.3.0（`pip install eltdx`，原生扩展 `eltdx._native` 就绪） |
| 其它补装 | pytest 9.2.0 / beautifulsoup4 4.15.0 / pypdf 6.21.4 |
| 通达信服务器 | 43 台候选池，连接正常（`data/tdx_hosts.resolve_quote_hosts`） |
| 单元测试（首审时） | 591 passed, 1 skipped in 143.77s |
| 单元测试（**修复后复审**） | **644 passed, 1 skipped in 120.18s**（+53 个新测试；本轮 2 处 f-string 修补后复跑 644 passed / 123.21s） |
| 端到端复验 | `python3 cli.py analyze 001225`（真实行情 + 真实 LLM 节点）跑通；`python3 cli.py screen --mode close --top 10` 跑通；`python3 cli.py track` 跑通 |
| 复审时钟 | 2026-10-30 07:38 CST（**盘前**，见 §7.1 —— 该时点恰好暴露了 P0-1 的残余缺陷） |

**关键背景**：`.env` 中 `AST_AI_ENABLED=1`，AI 五节点在默认配置下**处于开启状态**并真实调用 LLM（`AST_AI_API_BASE=https://token.vip.cpolar.cn/v1`，模型 `deepseek-v4.1-flash`）。因此下文中所有「AI 覆写」路径都是**默认可达的生产路径**，不是边缘情况。

---

## 1. 复审结论摘要

### 1.1 总体判断

**修复波次的工程质量是高的**：P0-1~P0-4 与 P1-1~P1-14 全部有对应改动落点，测试从 591 增至 644，新增测试覆盖了修复路径；多处修复不仅改了主逻辑，还补了口径标签（如 `overhead_chip_basis`、`pe_basis`、`roe_basis`）和归因矩阵记录。

**但修复尚未闭环**，三类问题仍在：

1. **P0-1 名义修复、运行时失效** —— 宏观闸门代码链路完整，但 `ladder_analyzer` 在连板天梯数据为空时**提前 return**，`macro_result` 恒为 `None`，闸门静默降级为 `UNVERIFIED`，全市场链路仍原样输出带仓位的 `buyable` 标的。复审实测：同一天同一份数据直接调用引擎得 `is_gate_open=False`（闸门本应关闭）。
2. **P1-2 的修复引入了新的系统性口径错误** —— 为解决「单期 PE/ROE 与年度阈值不可比」，改为按报告期年化；但**报告期是全局的、不是逐股的**。2026-10-30 时点 `20260930`（三季报）档案仅收录 **1688 / 5578 家**，而代码把 `20260930` 这个年化系数（×4/3）套给了**全部**公司 —— 未披露三季报的公司（约 72%）被按错误系数年化，**ROE 系统性低估 33%、PE 系统性高估 50%**。
3. **P1-5 / P1-14 / P1-7(残) / P1-10(接线空转) 未真正闭合** —— 真实盘口数据仍未接入；`mode` 仍只是标签；一字跌停不可卖仍无免责；`looks_like_financial_row` 接线后**在任何标的上都返回 False**（恒不触发）。

### 1.2 P0 复审状态总表

| # | 问题 | 状态 | 复审结论与证据 |
|---|---|---|---|
| **P0-1** | 全市场链路缺大盘情绪硬闸门 | ⚠️ **代码已修，运行时仍失效** | `screener/market_gate.py` 新增（`apply_macro_gate` / `single_name_cap_pct` / `GATE_BLOCKED_ACTION`），`pipeline.py:226-228,255` 已接线并输出 `macro_gate` 字段。**但** `ladder_analyzer.py:88-100` 在 `lad.rows` 为空时提前 return → `macro_regime_result=None` → 闸门 `UNVERIFIED` → 盘前实跑仍输出「轨道 C 25% / 轨道 D 20%」仓位建议。详见 §4.1 / §7.1 |
| **P0-2** | AI 绕过单向阀 + 覆写后不重算仓位 | ✅ **已修复** | `pillar5_decision.py:314-331` 改用 `apply_verdict_downgrade_only`，档位变更后经 `cap_of_gear(...)` 重算 `position_cap`；`cap_of_gear` 成为「档位→仓位」唯一映射（`:84-110`）。**复验**：001225 实跑输出「🤖 大模型裁定 · 回避」+「能买多少: 0%」，档位/仓位/标签三者一致 ✅ |
| **P0-3** | 字段名错配致核心指标静默恒 0 | ✅ **已修复** | `main_force_engine.py:218` 改读 `turnover_ratio`；`eltdx_financial_map.py:123,191` 修正为 `undistr_profit`；`audit_engine.py:483` 改用 `total_hldr_eqy_inc_min_int`/`_exc_min_int`；`eltdx_collector.py:22` 删除三份重复映射表。**复验**：001225 换手显示 **7.99%**；茅台 RE = 1996.83 亿，Z 由 5.1296 → **6.0342**（+0.90 分）✅ |
| **P0-4** | 实盘胜率账本口径错误 | ✅ **已修复**（1 处残余） | `tracker.py` 改为次日开盘价基准、`UNFILLABLE` 剔除、扣双边费用、分轨统计。**复验**：`cli.py track` → 77 可成交样本 / 18 一字板剔出分母 / 胜率 50.6% / 净 +0.08% vs 毛 +0.18%。**残余**：历史 115 条无 `track` 字段的旧记录仍占 overall 分母 100%，分轨胜率暂为 0 ✅→⚠️ |

### 1.3 P1 复审状态总表

| # | 问题 | 状态 | 复审结论 |
|---|---|---|---|
| P1-1 | 轨道 B「弱」无下限 | ✅ 已修 | `config.py:250` 新增 `TRACK_B_MIN_PCT_CHG = -7.0`，`tracks.py:196,233` 双向判定 |
| **P1-2** | 轨道 D PE/ROE 口径与阈值错配 | 🔴 **修复引入新错配** | 改为年化，但**报告期全局化** → 未披露三季报的公司被套用 ×4/3 → ROE 低估 33%、PE 高估 50%。实测工行 ROE 5.35%（正确 8.03%）→ 被 `D_ROE_TOO_LOW` 否决。详见 §7.2 |
| P1-3 | `report_date` 是数据更新日 | ⚠️ 部分修复 | 已拆分 `report_period` / `report_date` / `data_updated_at` / `report_period_source` ✅，但 `report_period` 逐股不准（见 P1-2） |
| P1-4 | 伪筹码可单独触发清仓 | ⚠️ **仅加标签，触发权仍在** | `game_features.py:102` 增 `overhead_chip_basis="volume_proxy_60d"` ✅、呈现层加「口径: 60日量能代理」✅；但 `main_force_engine.py:597/645/736`（≤35/≤30/≥60）与 `pillar4_path.py:143`（≥55）仍按该值判「高尾险·不可承受」。详见 §5.4 |
| **P1-5** | 伪「主动买卖方向 / 聪明钱 Q」 | ❌ **未修** | 全仓 grep `get_depth` / `buy_sell_strength` / `auctions.series` / `trades.` **零命中**；`microstructure.py:235-239` 仍写「collector 无 trades 封装」——**该断言为假**（eltdx 3.3.0 `TradeApi` 提供 `today / all_today / opening_match_today`） |
| P1-6 | 竞价量门槛不可达（0/20） | ✅ 已修 | `config.py:338` `AUCTION_MIN_VOLUME_RATIO` 0.15 → **0.03**（与实测中位 3.08% 吻合） |
| P1-7 | 执行剧本含不可执行指令 | ⚠️ **大修，1 处残余** | 一字板豁免收紧为 `high == low` 真一字 ✅；`life_line` 改真实 `pre_close` ✅；**但 5 处「市价止损」文案仍无「一字跌停无法成交」免责** ❌ |
| P1-8 | 游资画像默认值造数 | ✅ 已修 | `youzi_personas.py:187-193` 缺数据即 `None` 弃权；`risk_off`/`sample_low` 改为入参 ✅ |
| P1-9 | Tier 2 排雷队列截断 | ✅ 已修 | `pipeline.py:493-534` 显式限流 + 归因矩阵 `AUDIT_QUEUE_TRUNCATED` + **尾部补排雷补位**（`:186-206`）+ `rebate_drop` 回冲守恒 ✅ |
| P1-10 | 金融业报表错位 + 行业门控 | ⚠️ **接线空转** | 行业词表补「人寿/财险/保险经纪」✅、行业门控已进 `audit_engine` ✅；但 `looks_like_financial_row` **在真实数据上恒为 False**（要求 T020 流动资产合计与 T038 非流动资产合计同时为 0）→ 接线不产生任何效果。详见 §5.10 |
| P1-11 | 万元换算错 100 倍 | ✅ 已修（**首审误判更正**） | `capital_matrix.py:86,118-121` 改 `/10000` ✅。**更正**：首审称「机构净买入恒 0」不成立 —— `inst_buy`/`inst_sell` 分别取 `buy_amt`/`sell_amt` 两个不同字段，净额本就可非零。详见 §5.11 |
| P1-12 | 板块识别漏 302/689 | ✅ 已修 | `judgment_chain.py:938`、`youzi_personas.py:199` 均改为 `("300","301","302","688","689")` |
| P1-13 | 呈现层缺一致性校验 | ✅ 根因已修 | `cap_of_gear` 成为单一真源，`html_renderer.py:95` 的标签由 `gear_display(gear, cap)` 派生 → 三者同源 ✅（但仍**没有独立的一致性校验器**，缺字段时无法自检） |
| P1-14 | `mode` 只是标签 | ❌ **未修** | `pipeline.py:256` 仅把 `mode` 放进结果体，筛选行为本身 close/noon 完全一致 |

### 1.4 P2 复审状态

| 项 | 状态 |
|---|---|
| `data/supplement_api.py` 明文 HTTP | ✅ 已修（改 HTTPS，含东财接口） |
| `core/analyzer.py` `trade_date` 取 `now()` | ✅ 已修（改用日线最后交易日） |
| `core/trap_detector.py` 概念标签冒充舆情 | ✅ 已修（呈现层加口径免责说明） |
| `data/eltdx_financial_map.py` 死代码 | ⚠️ 已接线但**空转**（见 P1-10） |
| `screener/funnel_audit.py` 无 PIT | ❌ 未修 |
| `core/derivation.py` 参数硬编码 | ❌ 未修（该文件未进入修复波次） |
| `lint/validator.py` R6/R17 未实现、阈值硬编码 | ❌ 未修（该文件未进入修复波次） |
| `.env` cpolar 隧道外发持仓/财务数据 | ❌ 未修（**合规项，需用户决策**） |
| `screener/finance_batch.py` 应收口径/总负债自加总 | ❌ 未修 |
| `core/audit_engine.py` 阈值硬编码、仅排除金融 | ❌ 未修 |
| `cli.py` 单文件巨石 | ❌ 未修 |
| `data/eltdx_collector.py` float32 尾数 | ❌ 未修（影响可忽略） |
| `screener/tracker.py` `(report_id, code)` 去重 | ⚠️ 未见显式去重（`record_screen_picks` 有 `report_id` 但未见唯一约束） |

### 1.5 本轮复审新发现（3 个回归 + 1 处更正）

| # | 位置 | 性质 | 摘要 |
|---|---|---|---|
| **N-1** | `screener/ladder_analyzer.py:88-100` | 🔴 **P0-1 残余（可复现）** | 梯子数据为空 → 提前 return → 宏观闸门永久 `UNVERIFIED` → 全市场链路不做任何市场级约束。复审在盘前实跑中稳定复现 |
| **N-2** | `screener/finance_batch.py:203-217, 299-323` | 🔴 **P1-2 修复引入的回归** | 报告期取**全局最新档案期**（`20260930`），而该期仅 1688/5578 家已披露 → 其余公司年化系数错配 → ROE 低估 33%、PE 高估 50%，直接改变轨道 D 准入名单 |
| **N-3** | `core/pillars/pillar5_decision.py:255`、`core/main_force_engine.py:940` | 🟡 **呈现层占位符泄漏** | 两处 f-string 漏写 `f` 前缀，`{sotp_ps:.2f}` / `{smart_vwap:.2f}` 原样出现在用户可见文案中（已在本轮修补） |
| **C-1** | 首审 §5.11 | ⚪ **首审误判更正** | 「资金矩阵机构净买入恒 0」不成立 —— `inst_buy`/`inst_sell` 取的是 `buy_amt`/`sell_amt` 两个不同字段 |

---

## 2. 系统全景

### 2.1 两条并行主链路

```
链路一：全市场选股（screener）
  L0  universe.py        沪深母池（证券代码表为准，非涨停梯）
  L1  profile_batch.py   全市场行情画像
  T1  filter_liquidity.py 成交额/换手/涨幅/板块闸门
  T2  filter_audit.py    财务+治理排雷（一票否决）★ 队列限流 120 + 尾部补排雷
  T3  rank_composite.py  tape_score 排序 + 行动决断 → 轨道 A
      tracks.py          轨道 B/C/D（D 轨走 finance_batch 财务快照）
      market_gate.py     ★ P0-1 宏观闸门（本次新增）
  → pipeline.py → 漏斗归因 / 情绪总览 / ledger / html_renderer / tracker 账本

链路二：单股深度分析（analyzer）
  analyzer.py → judgment_chain.py → pillars 1~5
     ①质量 ②护城河 ③赔率 ④路径 ⑤决断
     支撑：audit_engine / derived_metrics / derivation / microstructure / main_force_engine
     → lint/validator.py 质量门控 → presentation（HTML / 终端）
```

### 2.2 数据层真相（运行时验证）

| 数据 | 来源 | 实测结论 |
|---|---|---|
| 实时快照 | `eltdx.quotes.get_snapshots` | `last_price / pre_close / total_hand / amount / open_amount_yuan` 可用 |
| **十档盘口** | `eltdx.quotes.get_depth` | **可用**，返回完整 buy_levels/sell_levels（茅台实测 ≥10 档）——**仓库仍未使用** |
| **集合竞价逐秒** | `eltdx.auctions.series` | **可用**——**仓库仍未使用** |
| **逐分钟委托买卖强度** | `eltdx.minutes.buy_sell_strength` | **可用**——**仓库仍未使用** |
| **逐笔成交** | `eltdx.trades.today / all_today / opening_match_today` | **接口存在且可用**（`eltdx.client.TradeApi`）——**仓库仍未使用**；首审记录的 `all_today` 分页异常不影响 `today`/`opening_match_today` |
| 日 K | `eltdx.bars.get(period="day", adjust=None)` | `core/analyzer.py:104` 已改 `adjust="qfq"` ✅；**`screener/kline_batch.py:142` 仍无 adjust → 轨道 B/C 的均线判据仍用不复权序列** ❌ |
| 资金流 | `eltdx.money_flow.daily` | 单位 = **元**（`main_net=110,509,511.6` ↔ 当日成交额 57.98 亿，比例 1.906% 自洽） |
| 专业财务 | `eltdx.corporate.finance_batch` | 40+ 字段，**单位不统一**（见 §6） |
| F10 三表 | `eltdx.f10.finance_report` | 资产负债表为**万元/元混用**；银行股字段错位（见 P1-10） |
| 名称/PE/PB | 腾讯 `qt.gtimg.cn`（**已改 HTTPS** ✅） | `parts[39]` 实测为 TTM 口径 PE |
| LHB/股东户数 | 东财 datacenter | 可用 |

### 2.3 模块职责速查（仅列有结论的部分，状态为复审结论）

| 层 | 文件 | 结论 |
|---|---|---|
| 数据 | `data/eltdx_collector.py` | 重复映射表已删除 ✅，唯一真源为 `eltdx_financial_map` |
| 数据 | `data/eltdx_financial_map.py` | `undistr_profit` 已修正 ✅；`looks_like_financial_row` 逻辑恒假 ❌ |
| 数据 | `data/supplement_api.py` | 已改 HTTPS ✅ |
| 判断 | `core/judgment_chain.py` | 302/689 已补 ✅ |
| 判断 | `core/pillars/pillar5_decision.py` | `cap_of_gear` 单一真源 ✅；`life_line` 改真实前收 ✅；f-string 泄漏已修 ✅ |
| 判断 | `core/main_force_engine.py` | 换手率键名已修 ✅；`overhead_chip` 触发权仍在 ⚠️ |
| 判断 | `core/microstructure.py` | 仍为 K 线代理口径 ❌；注释中「collector 无 trades 封装」为假 ❌ |
| 判断 | `core/game_features.py` | 已加 `overhead_chip_basis` 口径标签 ✅ |
| 判断 | `core/youzi_personas.py` | 默认值造数已清除 ✅ |
| 判断 | `core/audit_engine.py` | 权益键名已修 ✅；行业门控已扩展 ✅ |
| 判断 | `core/derived_metrics.py` | **全仓库口径最扎实的模块**，应作为 P1-2 后续修复的范式 |
| 判断 | `core/derivation.py` | 参数硬编码，**未进入修复波次** |
| 筛选 | `screener/pipeline.py` | 宏观闸门已接线 ✅ 但见 N-1；排雷尾部补位 ✅；`mode` 仍只是标签 ❌ |
| 筛选 | `screener/market_gate.py` | **新增**，闸门语义与纪律完整 ✅ |
| 筛选 | `screener/filter_liquidity.py` | 一字板豁免收紧为真一字 ✅ |
| 筛选 | `screener/filter_audit.py` | 排雷限流 + 补位 ✅ |
| 筛选 | `screener/tracks.py` | 轨道 B 下限 ✅；轨道 D 年化口径见 N-2 ⚠️ |
| 筛选 | `screener/finance_batch.py` | 报告期字段已拆分 ✅，但逐股期次错配 🔴 |
| 筛选 | `screener/kline_batch.py` | **未加 `adjust="qfq"`** → 轨道 B/C 均线仍受除权污染 ❌ |
| 复盘 | `screener/tracker.py` | 口径重写完成 ✅；历史记录缺 `track` ⚠️ |
| 呈现 | `presentation/html_renderer.py` | 标签由 `gear+cap` 派生 ✅ |

---

## 3. 运行时复验：三大 P0 的复现 → 修复 → 再复验

### 3.1 换手率恒 0 → 主力阶段置信度虚增（已修）

**首审实测**：`get_realtime_quote` 返回的真实字典键为
`['amount','bps','circ_mv','close','eltdx_code','eps','float_share','high','low','name','open','pb','pct_chg','pe','pre_close','total_mv','total_share','ts_code','turnover_ratio','vol']`
→ **没有 `turnover` 键**，`quote.get("turnover", 0.0)` 恒得 0.0。

| 口径 | 主力阶段 | 置信度 |
|---|---|---|
| 首审：仓库现状（turnover=0） | `STAGE_1_ACCUMULATION`【🌱 低位隐蔽吸筹期】 | **72.5%** |
| 首审：修正后（turnover=7.99） | `STAGE_1_ACCUMULATION`【⚠️ 方向未定·多空过渡】 | **42.5%** |

**修复**：`core/main_force_engine.py:218` → `turnover = float(quote.get("turnover_ratio") or 0.0)`；同时 `core/main_force_engine.py:220` 起补齐了 STAGE_4/5/7 的换手率判据注释。

**复验**：2026-10-30 实跑 `analyze 001225` → 卡片首行显示「**换手: 7.99%**」，主力阶段输出「🔥 健康放量主升期 (趋势推升) (置信度: **61.0%** (⚠️多空过渡区))」。置信度与首审的 72.5% / 42.5% 均不同 —— 因复审时点行情数据已更新（001225 于 10-29 涨停后次日），**关键在于换手率已进入判据**，且不再出现「方向未定却给 72.5% 确定叙事」的组合。✅

**遗留判据**：STAGE_4「换手 ≥12% + 量比≥1.6 + 振幅≤1.5% + Amihud<0.0003」、STAGE_5「3%≤换手≤22%」、STAGE_7 换手分档 —— 现已可被触发 ✅。

### 3.2 Altman Z-Score 缺 RE 项（已修）

**首审实测**（茅台 600519 · 2025 年报）：RE 恒为 0，Z 分被抹掉 **0.8843** 分（22.4460 → 23.3302）。

**修复**：
- `data/eltdx_financial_map.py:123`、`:191` → `undistr_profit`（拼写修正，12/12 覆盖）；
- `core/audit_engine.py:474` → `re = _safe_float(b.get("undistr_profit"), 0)`；
- `core/audit_engine.py:483` → `te = _first_present(b, ("total_hldr_eqy_inc_min_int", "total_hldr_eqy_exc_min_int"))`（生产数据真实键），MV 兜底不再退化为 1.0；
- `core/audit_engine.py:550/555/623/1059` 同步改用真实权益键。

**复验**（茅台 600519 · 2026 半年报 `end_date=20260630`，实测）：

| 项 | 数值 |
|---|---|
| 资产总计 TA | 309,050,784,569.31 元 |
| 负债合计 TL | 46,954,432,394.95 元 |
| 未分配利润 RE | **199,683,216,816.2 元**（修复前恒为 0）✅ |
| 股东权益合计（含少数股东） | 262,096,352,174.36 元 |
| **Z（修复后）** | **6.0342** |
| Z（模拟旧实现：RE=0） | 5.1296 |
| **回归分值** | **+0.9046**（与首审量级一致） |

首审结论「偏误杀而非全面误杀」仍然成立：茅台这类极优质股无感，但**落在 1.81~2.99 灰区**的公司会被误判进危险区。修复方向正确 ✅。

**附带修复**：`tests/test_audit.py` 的 Altman 用例已改为生产真实键名（此前手写 `{"undistr_profit": -50.0, "total_equity": 10.0}` —— 生产数据永不产生 `total_equity`）。

### 3.3 不复权 K 线的量化污染（**部分修复**）

**首审实测**（工行 601398，2026-10-21 除权除息）：

| 序列 | 10-20 → 10-21 | 结论 |
|---|---|---|
| 不复权 | 8.58 → 8.45，**-1.52%** | **假跌 1.75%** |
| 前复权 | 8.43 → 8.45，**+0.24%** | 真实涨幅 |

60 根日 K 窗口偏差：MA20 **1.17%**、MA60 **1.67%**；10/20/60 日涨幅分别偏 **-1.86 / -2.03 / -2.02 pct**；20 日最低价（支撑位）偏高 **1.84%** → **止损线系统性偏高**。

**修复（部分）**：
- ✅ `core/analyzer.py:104` → `self.collector.get_daily(ts_code, count=60, adjust="qfq")` —— **单股深度链路的 MA / 支撑压力 / 波动率 / 涨幅已全部走前复权**；
- ✅ `core/analyzer.py:198-209` → `trade_date` 改用日线最后交易日；
- ✅ `screener/tracker.py:196` → `adjust=None` —— **账本收益核算刻意用不复权真实成交价**（这是正确的：复权价算收益等于用昨天的价格成交）；
- ❌ **`screener/kline_batch.py:142` 仍为 `client.bars.get(b, period="day", count=count)`，无 `adjust` 参数** → eltdx 默认 `adjust=None` → **轨道 B/C 的「多头排列 / 站稳 MA5 / 回踩不破 MA5」判据仍建立在不复权序列上**，除权日仍会产生假跌破/假跌破修复。

**残留影响面**：轨道 B「缩量回踩未破 MA5」、轨道 C「C_MA_NOT_BULLISH:40」—— 2026-10-30 实跑中轨道 C 有 40 只因均线不满足被淘汰，其中一部分可能是除权造成的假跌破。

---

## 4. P0 复审（逐条）

### P0-1　全市场筛选链路缺失大盘情绪硬闸门　⚠️ **代码已修，运行时失效**

**首审问题**：宏观引擎结果仅进入 `overview` 展示，不参与任何决策。2026-10-29 实跑同一屏内先打印「全市场广度量能【极端普跌冰点】上涨 781 家 / 下跌 4728 家」「⚠️ 谨防天地板踩踏补跌」，紧接着输出 6 只「🔥 主升做多（分批布局）· 20% 仓位」。

**已完成的修复**（本次新增文件 `screener/market_gate.py`，共 120+ 行）：

| 组件 | 实现 | 复审评价 |
|---|---|---|
| `single_name_cap_pct(macro_result)` | 闸门关闭 → `0.0`；投机期 → `MAX_SINGLE_POSITION/2`；放行 → 常规档；**未核验 → `None`** | ✅ 语义正确，缺值不兜底 |
| `apply_macro_gate(picks, macro_result)` | 就地改写 `picks`：`macro_gate_status` / `macro_single_name_cap_pct` / 关闭时 `action: "buyable" → "wait_macro_gate"` 且 `playbook = None` | ✅ 剧本置空是对的（闸门收紧时输出挂单区间自相矛盾） |
| `GATE_BLOCKED_ACTION = "wait_macro_gate"` | 新建市场级等待态，不复用 `wait_reseal` | ✅ 归因可区分 |
| `pipeline.py:226-228, 255` | 闸门结果进入返回体 `"macro_gate"` 字段 | ✅ |
| `pipeline.py:270` | 漏斗未通过时返回 `{"status": "UNVERIFIED", ...}` | ✅ |
| 呈现层 | `🚦 宏观情绪闸门 (市场级)` 面板 | ✅ |

**🔴 残余缺陷 N-1（可稳定复现）**：

`core/macro_regime.py` 的 `MacroRegimeEngine.evaluate()` **永远返回一个 `MacroRegimeResult`**（无早退分支），其输入只有三项：上证指数日线、全市场广度、连板梯子概览（权重 20%）。但 `screener/ladder_analyzer.py:88-100` 的**早退分支**在 `lad.rows` 为空时直接返回 `macro_regime_result=None` —— **早退发生在宏观评估代码块（`:227-253`）之前**。

于是：**只要涨停天梯接口返回空，宏观闸门就永久 `UNVERIFIED`，且这个状态与「大盘健康」在面板上难以区分。**

复审实测（2026-10-30 07:38 CST，盘前）：

```
╭──────────── 🚦 宏观情绪闸门 (市场级) ────────────╮
│ 闸门状态: UNVERIFIED                              │
│ 宏观闸门未核验（大盘 regime 缺失）：本次结果**未做**│
│ 市场级约束，严禁视为『已放行』…                   │
╰──────────────────────────────────────────────────╯
│ 600715 文投控股 │ +10.19% │ 首板 │ 【⏳ 次日竞价确认 (条件单)】 │ 10% │
│ 601658 邮储银行 │ +1.59%  │ 🏛️ 均线回踩右侧低吸 │ 25% │        │
│ 605338 巴比食品 │ +10.03% │ 🛡️ 安全边际左侧分批 │ 20% │        │
```

**同一份数据下，闸门本应关闭**（复审直接调用引擎验证）：

```
上证 2026-10-29 收盘 3651.43 (-0.82%)；上涨 781 / 下跌 4728 / 涨停 39 / 跌停 42
→ gate_open = False，label = 【大盘震荡分化与结构轮动】，score = 32.2
→ resonance = CHOPPY_ROTATION，spec = 震荡轮动试盘
→ single_name_cap_pct = 0.0     ← 引擎认为单票上限应为 0
```

即：**引擎有能力判定「今日不交易」，但它的可用性被绑在最易缺失的数据源（涨停天梯）上。** 盘前、非交易时段、接口抖动三种常见场景都会触发。

**建议（修复优先级 P0）**：
1. **把宏观评估从梯子早退分支中解耦**：把 `MacroRegimeEngine.evaluate(...)` 移到 `ladder_analyzer.analyze()` 的**最前面**（或独立成 `screener/macro_gate_service.py`），梯子为空时传 `None`/零值 overview 继续评估 —— 梯子只占 20% 权重，不该决定闸门可用性；
2. **UNVERIFIED 必须 fail-closed**：按 NFR-02「缺值不兜底」，`UNVERIFIED` 时单票上限应为 `0.0`（或至少把所有 `buyable` 降级为等待态），而不是「不做约束但保留 20~25% 仓位建议」；
3. **区分「UNVERIFIED」与「放行」在呈现层的视觉权重**：当前 UNVERIFIED 与 OPEN 在面板上同为一行提示，但后果差一个数量级；
4. **补一条单测**：mock 梯子接口返回空 → 断言 `macro_gate.status != "UNVERIFIED"` 或断言 `buyable` 数为 0。

**验收标准**：
- `ladder_analyzer` 返回空天梯时，`macro_gate.status` 仍为 `OPEN`/`CLOSED`（有 regime 结论）；
- `UNVERIFIED` 时 `final_top` 中 `action == "buyable"` 数量为 0；
- 盘前实跑 `screen` 面板显示「今日不交易」且所有标的仓位建议为 0。

### P0-2　AI 五节点绕过单向阀 + 覆写后不重算仓位　✅ **已修复**

**首审实证**（`reports/002273_SZ_20261029.html`）：「决断档位: 期权仓(小) | 建议仓位: 0%」+ 顶部标签「🔴 回避 / 空仓」+ 正文「【🤖 大模型裁定 · 期权仓(小)】」三者互相矛盾。

**修复**：
- `core/ai_coprocessor/guard.py` 新增 `apply_verdict_downgrade_only(...)`；`core/ai_coprocessor/__init__.py` 导出；
- `core/pillars/pillar5_decision.py:314-331` —— AI 覆写改为走 `apply_verdict_downgrade_only`（**只能降级，不能升级**）；
- `core/pillars/pillar5_decision.py:84-110` 新增 `cap_of_gear(decision_gear, mf_cap, mf_confidence, left_tail_depth_pct, *, is_micro_degraded, ni_is_verified)` —— **「档位 → 仓位上限」的唯一映射**；AI 改档后由 `cap_of_gear` 重算 `position_cap`；
- `cap_of_gear` 明确规定：除「核心仓 / 期权仓(小)」外一律 0 仓位 —— 观察/不追高/减仓/回避都是「不建议下注」，给非零仓位等于把三分结论写成假的；
- `core/pillars/pillar1_quality.py`、`pillar2_state.py`、`pillar3_odds.py`、`pillar4_path.py` 同步接入 guard。

**复验**（2026-10-30 实跑 `analyze 001225`）：

```
❺ 到底该怎么办？ (结论、能买多少、怎么买、错了怎么退) —— 【🤖 大模型裁定 · 回避】 (能买多少: 0%)
   • 三句话结论: [↓变差 | 买完完美未来 | 高尾险·不可承受]
   • 买方判定: 好公司? 【是】 · 好下注? 【否】 · 好价格? 【否】
```

档位（回避）、仓位（0%）、行动文案（严禁追高 / 逢高减仓）三者一致 ✅。

### P0-3　字段名错配导致核心指标静默恒 0　✅ **已修复**

| 原位置 | 原读取键 | 生产实际键 | 修复后 | 复验 |
|---|---|---|---|---|
| `main_force_engine.py:213` | `quote["turnover"]` | `quote["turnover_ratio"]` | `:218` 改读 `turnover_ratio` ✅ | 001225 显示「换手: 7.99%」✅ |
| `audit_engine.py:462` | `b["undistr_profit"]` | 原为 `undistr_porfit`（拼错） | `eltdx_financial_map.py:123,191` 改为 `undistr_profit` ✅ | 茅台 RE = 1996.83 亿 ✅ |
| `audit_engine.py:470,472` | `b["total_equity"]` | `total_hldr_eqy_inc_min_int` | `:483` `_first_present(...)` 兼容两键 ✅ | Z 6.0342（+0.90）✅ |
| `eltdx_collector.py:21-51` | 三份重复映射表 | — | 已删除，唯一真源为 `eltdx_financial_map` ✅ | — |

**建议仍待补（首审 §4.3 第 3 点未完全落地）**：建立**字段名契约测试** —— 从 `eltdx_financial_map` 生成期望键集合，断言 `audit_engine` / `derived_metrics` 中所有 `b.get("xxx")` 的 xxx 均在集合内。首审已证明：**当测试使用生产数据永不产生的键名时，测试全绿毫无意义**。当前新增的 `tests/test_audit_round2_fixes.py`、`tests/test_runtime_audit_fixes.py` 是按点修的，尚未形成通用契约。

### P0-4　实盘胜率账本口径错误　✅ **已修复（1 处残余）**

**首审问题**：收益基准用前一日收盘价；无涨跌停不可成交处理；无费用；无去重；只记录轨道 A。

**修复**（`screener/tracker.py` 重写）：
- `STATUS_UNFILLABLE = "UNFILLABLE"`；一字板（开盘即封死）剔出胜率分母；
- 收益基准改为**次日开盘价** `next_open`（`adjust=None` 不复权真实成交价）；
- `round_trip_fee_pct()`：双边佣金（万 2.5，单笔最低 5 元）+ 卖出印花税 0.05% + 双边过户费 0.001%；
- `_summarize` 分母只含 `COMPLETED`；
- `by_track` 分轨统计；`record_screen_picks(..., track=_tr)` 四轨统一入账；
- `open_gap_pct` 保留「与选出日收盘价的偏移」作为对照，不参与判胜负。

**复验**（`python3 cli.py track`，真实账本 389 条）：

```
│ 已跟踪总标的数                │ 389     │
│ 已测算样本 (T+1 可成交)       │ 77      │
│ 不可成交 (一字板·已剔出分母)  │ 18      │
│ 待 T+1 行情                   │ 294     │
│ 次日胜率 (T+1 win rate)       │ 50.6%   │
│ 次日平均净收益 (扣费后)       │ +0.08%  │
│ 次日平均毛收益 (未扣费)       │ +0.18%  │
│ 平均最大冲高 / 最大回撤       │ +3.78% / -3.64% │
│ 盈亏比 (均赢/均亏)            │ 1.05    │
★ 口径：T+1 开盘价买入、当日收盘价卖出，扣除双边佣金/印花税/过户费；
  一字板（开盘即封死无法成交）不计入胜率分母。
```

**残余**：账本 389 条中，274 条带 `track`（全部来自 2026-10-30 当日运行 → 尚无 T+1 结果），115 条为旧记录（无 `track` 字段）→ **当前 overall 胜率的 77 个样本 100% 落在「未标注」**，分轨胜率全为 0。这不是代码 bug（新入账记录已带 `track`），而是**账本需要至少一个交易日的历史才能出分轨结论**。建议：对 115 条旧记录做一次性回填（按 `mode`/`rank`/候选池来源反推轨道，或标记 `legacy`），否则 overall 胜率在混合期仍不可解释。

---

## 5. P1 复审（逐条）

### P1-1　轨道 B 的「弱」没有下限　✅ 已修

`config.py:250` 新增 `TRACK_B_MIN_PCT_CHG = -7.0`；`tracks.py:192-196`（轨道 B 主判定）与 `:229-233`（`apply_track_b_trend`）双向排除「跌幅过头属破位」。首审记录的「300539 横河精密 -9.74% 被当作弱转强反包」现已被排除 ✅。

### P1-2　轨道 D 的 PE / ROE 口径与阈值错配　🔴 **修复引入新错配（见 §7.2）**

**首审实测**：

| 标的 | 静态 PE（仓库，卡片显示） | 腾讯 PE（TTM） | 偏差 | 期间 ROE（卡片显示） | 年化后 |
|---|---|---|---|---|---|
| 605338 巴比食品 | 21.57 | 16.05 | **+34%** | 9.35% | ≈18.7% |
| 605319 无锡振华 | 20.82 | 14.64 | **+42%** | 11.38% | ≈22.7% |
| 600519 贵州茅台 | 38.07 | 20.79 | **+83%** | 17.72% | ≈35.4% |

**修复**：`screener/finance_batch.py` 引入 `FinanceSnapshot`（含 `ANNUALIZE_FACTOR = {0331:4.0, 0630:2.0, 0930:4/3, 1231:1.0}`）、`eps_annualized()`、`pe()`、`roe_pct()`、`pe_basis()`、`roe_basis()`；`tracks.py:538-580` 在年化不可核验时**放行并标记 UNVERIFIED**（不拿单期值误杀）；卡片新增 `pe_basis` / `roe_basis` / `valuation_unverified` / `report_period` / `report_period_source`。

**方向是对的，但引入了 N-2（新错配）** —— 详见 §7.2。核心问题：**年化系数必须逐股取，不能全局取。**

**仍未解决的首审诉求**：
1. **年化 ≠ TTM**：年化 PE 与市场行情软件口径的 TTM PE 仍不可比（尤其银行/保险，H1 集中确认收入 → 年化失真更严重）。首审建议「接入 `core/derived_metrics.py` 已有的 TTM 能力」尚未执行；
2. **阈值口径**：`TRACK_D_MAX_PE = 30` / `TRACK_D_MIN_ROE = 8` 仍是「年度」阈值，与年化值虽量纲接近但季节性偏差仍在；
3. **静态 PE vs TTM 的偏差表**需要用新口径重测一遍。

### P1-3　`report_date` 是数据更新日，不是报告期　⚠️ 部分修复

**已修**：`FinanceSnapshot` 拆出 `report_period`（真实报告期）、`report_date`（数据更新日）、`report_period_source`；`tracks.py:577-579` 同时输出 `report_period` 与 `data_updated_at`；卡片展示改为 `report_period or report_date` ✅。

**未修到位**：`report_period` 由 `_latest_report_period()` **全局取值**（`finance_batch.py:203-217`）—— 见 §7.2，**逐股不准**。

### P1-4　伪筹码 `overhead_chip_pct` 仍能触发清仓　⚠️ **仅加标签，触发权仍在**

**已修**：
- `core/game_features.py:70-74, 102` 增加口径标记 `overhead_chip_basis = "volume_proxy_60d"`，注释明确「实为 60 日量能代理，与真实筹码分布无关」；
- 呈现层已如实标注 —— 复审实跑 001225 输出：「**筹码分布 (口径: 60日量能代理, 非真实成本分布)**: 获利盘 49.2% / 上方套牢量占比 50.8%」✅。

**未修（核心诉求未达成）**：该值**仍作为决策触发器**：

| 位置 | 阈值 | 后果 |
|---|---|---|
| `core/main_force_engine.py:513` | `overhead_chips < 35.0` | 缩量洗盘判据（正向） |
| `core/main_force_engine.py:597` | `overhead_chips <= 35.0` | 主升判据（正向） |
| `core/main_force_engine.py:645` | `overhead_chips <= 30.0` | 浮盈判据（正向） |
| `core/main_force_engine.py:736-738` | `overhead_chips >= 60.0` / `>= 45.0` | **派发判据（负向）** |
| `core/main_force_engine.py:749` | `overhead_chips < 30.0` | 主力流入判据（正向） |
| `core/main_force_engine.py:1047` | 文本「上方沉淀解套抛压沉重」 | **直接写进用户可见文案** |
| `core/pillars/pillar4_path.py:143` | `overhead_chips >= 55.0` | **「高尾险·不可承受」→ 可触发清仓** |

首审原文建议是「**删除该指标及其触发路径，或明确降级为「价格分位」描述性字段并从清仓条件中移除**」。目前只做了「描述性字段 + 加标签」，**触发路径一条未删**。对长期下跌股，该值天然接近 100%（首审实测 001225 曾出现 73.7%），仍可据此把正确持仓判成「高尾险·不可承受」。

**建议**：把 `pillar4_path.py:143` 与 `main_force_engine.py:736` 的阈值改为「价格分位（60 日分位）」口径，或直接移除该触发项；文案改为「近 60 日价格分布上方的成交占比（量能代理，非真实筹码）」。

### P1-5　伪「主动买卖方向 / 聪明钱 Q」，而 SDK 早已提供真数据　❌ **未修**

**复审 grep 结果**（全仓，排除测试）：

```
grep -rn "get_depth|auctions\.|buy_sell_strength|\.trades\." --include=*.py .
→ 0 命中
```

项目只用了 `quotes.get_snapshots` 与 `quotes.legacy`。

**代码里还留着一处错误断言**（`core/microstructure.py:235-239`）：

> 「★ 20261029 审计 P1-5：`smart_buy_ratio` / `smart_sell_ratio` 的真实口径是「高效分钟里**上涨分钟的成交量占比**」…本项目当前未接入（**collector 无 trades 封装**）。两者在震荡分钟里差异极大…」

**复审实测 eltdx 3.3.0 的真实能力**：

```
eltdx.client.QuoteApi : ['drain_pushes','get_depth','get_snapshots','legacy','list_by_category','poll_push','refresh']
eltdx.client.MinuteApi: ['aux','buy_sell_strength','history','recent','sparkline','today','volume_comparison']
eltdx.client.AuctionApi: ['series']
eltdx.client.TradeApi : ['all_history','all_history_batch','all_today','all_today_batch','history',
                         'history_batch','opening_match_history','opening_match_today','today','today_batch']
```

→ **`trades` 封装是存在的**（首审记录的 `all_today` 分页异常只影响 `all_today`/`all_history`，不影响 `today` 与 `opening_match_today`）。**注释中的「collector 无 trades 封装」是把「封装难写」写成了「没有能力」**，这是能力宣称与实现落差的根源。

**影响未变**：README 宣称「L2 十档挂单 / 聪明钱 Q 因子」，实现是 5 分钟 K 线涨跌近似。复审实跑 001225 输出仍为「微观知情资金分钟口径买盘占比达 42.9%（★ 分钟 K 线口径，非逐笔主动买卖方向）」—— 标签诚实了，但**数据仍是假的**。

**建议（仍是低成本高收益）**：
- `data/eltdx_collector.py` 增加 `get_depth(code)` / `get_auction_series(code)` / `get_buy_sell_strength(code)` / `get_trades_today(code)` 四个薄封装；
- `core/microstructure.py` 的 `smart_buy_ratio` / `smart_sell_ratio` 改用 `minutes.buy_sell_strength`；集合竞价抢筹改用 `auctions.series`；`smart_q` 用 `quotes.get_depth` 的十档重算；
- 无数据时保持现有「弃权 + 标注代理」行为（当前这部分做得对 ✅）；
- README 的能力宣称同步更新。

### P1-6　竞价量门槛不可达　✅ 已修

`config.py:335-338`：`AUCTION_MIN_VOLUME_RATIO` 由 `0.15` 改为 **`0.03`**，注释写明「原 0.15 是拍脑袋的门槛」。首审实测 20 只样本竞价量占全天：最小 0.53% / 中位 **3.08%** / 最大 5.54% → 3% 门槛约 50% 可达 ✅。实跑文案已更新为「竞价量 ≥ 昨日全天 **3%**」。

### P1-7　执行剧本含不可执行指令　⚠️ **大修，1 处残余**

| 首审问题 | 状态 | 证据 |
|---|---|---|
| ① 一字板被豁免换手率/成交额门槛，主动送进 `buyable` | ✅ 已修 | `screener/filter_liquidity.py:137-149` 豁免条件收紧为「`board_level >= 2` **且 `high == low`**（全天只有一档价 = 真一字）」，并明确「不可核验 → 按常规门槛走，保守方向」 |
| ③ `life_line = price*0.98` 却写「昨日收盘价」 | ✅ 已修 | `core/pillars/pillar5_decision.py:168-175` 改用真实 `_pre_close`，`life_line_desc` 与计算同源；文案 `:207` 改为「以昨日收盘价 ({life_line_desc}) 为日内生命线」 |
| ② 「市价无条件止损」未考虑**一字跌停不可卖** | ❌ **未修** | `pillar5_decision.py:185/205/246/290` 与 `execution_playbook.py:187/202/270` 共 **7 处**「市价止损/市价清仓」文案，**无一处**追加「遇一字跌停无法成交，按排队卖出处理，损失可能显著超出计划」 |

**残余影响**：A 股一字跌停日，卖单排队基本无法成交 —— 系统却在这类标的的止损文案里写「市价无条件止损」「坚决市价止损出局」，**给出的是无法执行的指令**。

**建议**：在 `execution_playbook` 的止损/退出文案模板层统一追加免责句（不要逐处手改，避免漏改）。

### P1-8　游资画像默认值造数 + 假阳性　✅ 已修

`core/youzi_personas.py:183-193`：`leader_rank` / `breadth_pct` 缺失 → `None` 并在判据层弃权（`:223-227` 三元判断 `... if (has_theme and leader_rank is not None) else None`）；`cap_val` 不再 `price*1e8` 凭空造市值（`:193` 无值即 `None`）；`risk_off` / `sample_low` 改为函数入参（`:153-158`）✅。

### P1-9　Tier 2 排雷队列截断　✅ 已修

`screener/pipeline.py:493-534` `_cap_audit_queue`：阈值外置为 `config.UNIVERSE_MAX_AUDIT_QUEUE = 120`；截断写入归因矩阵 `REASON_AUDIT_QUEUE_TRUNCATED`；截断前按 `(board_level, amount)` 降序；**尾部不再丢弃** —— `pipeline.py:186-206` 在精选池未填满时用尾部补排雷补位，并用 `audit.rebate_drop()` 回冲截断计数，保证 `input = 队列截断 + 排雷否决 + output` 守恒 ✅。

复审实跑归因（2026-10-30）守恒无误：
```
T1_liquidity: 5005 进 → 34 出 (淘汰 4971)
T2_audit: 34 进 → 33 出 (淘汰 1)   AUDIT_VETO:1
T3_rank:  33 进 → 10 出 (淘汰 23)   RANK_TRUNCATED:23
```

### P1-10　金融业报表错位 + 行业门控　⚠️ **接线空转**

**已修**：
- `core/industry.py:50-55` 金融关键词补「人寿」「财险」「保险经纪」（首审指出「中国人寿」「中国财险」这类简称不含「保险」二字）✅；
- `core/industry.py:95/98` 双重判定入口；`core/audit_engine.py:452-459` Altman/Beneish 的 `_model_applicable("AltmanZ", industry)` 主动弃权 ✅（首审实测工商银行确实输出两条「主动弃权」ℹ️）；
- `core/analyzer.py:118-133` 把 `looks_like_financial_row` 接进生产路径（首审的「死代码」问题形式上解决）✅。

**🔴 但接线是空转的**：`data/eltdx_financial_map.py:337-348` 的判据是

```python
total = _num(row.get("T039"))              # 资产总计
detail = ("T010", "T016", "T020", "T038", "T053")   # 应收/存货/流动资产合计/非流动资产合计/流动负债合计
return all(not v for v in vals if v is not None)   # 要求这 5 项全为 0/None
```

**T020（流动资产合计）与 T038（非流动资产合计）不可能同时为 0** —— 只要公司有正常经营，资产总额必然大于 0。该函数因此**在任何标的上都返回 False**。

**复审实测**：

```
600519 茅台    looks_like_financial_row = False   (应 False ✓)
601398 工行    looks_like_financial_row = False   (应 True  ✗ 漏判)
600036 招行    False   002273 长城电器 False   601225 哈尔滨电气 False   601318 平安 False
```

工商银行 F10 行实测：`T039=7808.6亿`、`T010=4578.16亿`、`T016=16.23亿`、`T020=None`、`T038=None`、`T053=2520亿` —— `T010`（应收账款）对银行是贷款类科目，非 0，判据同样不成立。

**结论**：首审「银行/非银资产负债表在生产数据中是垃圾」这一**问题本身仍然存在**，只是现在多了一个**永不触发的检测器**。同时首审提出的「行业门控扩展到全部 14 个框架」也未完成 —— Piotroski / DuPont / Buffett / Sloan / 存贷双高 / CIP 排雷仍在银行股上跑。

**建议**：
1. 重写 `looks_like_financial_row` 的判据：金融业的真实特征是「流动资产/流动负债科目为 0 或与工商企业不可比」，应改为检查 **T010 应收账款 / T016 存货 / T026 固定资产 等工商业科目在 T039 总资产中的占比**，或直接用 `core/industry.py` 的名称/概念判定（更可靠），F10 反查只作兜底；
2. 接入 `check_identities` 作为**数据准入闸门**（恒等式不成立 → 该行数据不可用 → 相关模型弃权）；
3. 行业门控扩展到全部 14 个框架。

### P1-11　资金矩阵机构净买入恒 0 + 万元换算错 100 倍　✅ 已修（**首审误判更正**）

**已修**：`core/capital_matrix.py:86`、`:118-121` 的万元 → 亿元换算由 `/100` 改为 `/10000`（三处），注释写明「旧代码 /100 差 100 倍」✅。

**⚪ 更正首审误判（C-1）**：首审称「`core/capital_matrix.py:72-73` 机构买卖赋值相同 → 机构净买入恒 0」。**复核后不成立**：

```python
inst_buy  = sum(r.get("buy_amt",  0.0) for r in lhb_records if "机构专用" in r.get("seat_name",""))
inst_sell = sum(r.get("sell_amt", 0.0) for r in lhb_records if "机构专用" in r.get("seat_name",""))
inst_net_wan = (inst_buy - inst_sell) / 10000.0
```

两者取的是**不同字段**（`buy_amt` / `sell_amt`），净额本就可非零，且首审也未给出「恒 0」的实测证据。**真实存在的缺陷只有单位换算那一项，且已修复。** 首审原文「机构维度永远为 0」的表述应予撤回。

### P1-12　板块识别遗漏 302/689　✅ 已修

`core/judgment_chain.py:938`、`core/youzi_personas.py:199` 均改为 `startswith(("300","301","302","688","689"))`。

### P1-13　呈现层缺一致性校验　✅ 根因已修（校验器仍缺）

**已修（根因）**：`core/pillars/pillar5_decision.py:84-110` 的 `cap_of_gear` 使「档位 → 仓位」成为**单一真源**；`presentation/html_renderer.py:95` 的顶部标签由 `gear_display(gear, cap)` 派生（而非独立取字段）→ 三者不可能再各自漂移 ✅。

**未修（首审建议的独立校验器）**：仓库中**没有**一个「档位 ↔ 仓位 ↔ 标签 ↔ 行动文案」的一致性校验器（`lint/validator.py` 未进入修复波次，且 R6/R17 仍未实现）。当前靠「同源」保证一致，属**结构性正确**而非**可自检**。建议补一条断言：任何 `decision_gear` 落在「观察/减仓/回避/等证据」时，`position_cap` 必须为 0。

### P1-14　`mode` 只是标签，不是行为　❌ 未修

`cli.py:192` 的 `--mode {close,noon}` 在 `pipeline.py` 内仅出现于：`:106` 日志、`:236` 账本 `report_id`、`:256` 结果体字段。**筛选阈值、流程、判据对 close / noon 完全一致**。首审指出的「盘中 10:00 用 `--mode close` 跑得到一份『收盘复盘』标签但数据是 10:00 快照」风险仍在。复审实跑 `--mode close`（2026-10-30 07:38，盘前）拿到的是 10-29 收盘数据，标签却是「CLOSE 模式」—— **风险现场可复现**。

---

## 6. P2 复审

| 位置 | 问题 | 状态 | 复审证据 |
|---|---|---|---|
| `data/supplement_api.py:17` | 明文 HTTP | ✅ 已修 | `:20` 改 `https://qt.gtimg.cn`；东财接口亦为 HTTPS |
| `core/analyzer.py:178` | `trade_date` 取 `now()` | ✅ 已修 | `:198-209` 用日线最后交易日，缺失时回退自然日并告警 |
| `core/trap_detector.py:153` | 概念标签冒充舆情 | ✅ 已修 | `:153-166` 呈现层加口径免责「输入为概念题材标签而非真实舆情正文…不等于已完成舆情核验」 |
| `data/eltdx_financial_map.py:309` | 死代码 | ⚠️ 空转 | 见 P1-10 |
| `screener/funnel_audit.py` | 无 PIT | ❌ 未修 | 文件在修复波次被改（归因矩阵），但仍无「每层入池/出池原因码快照」 |
| `core/derivation.py` | 参数硬编码 | ❌ 未修 | 该文件 mtime 2026-10-28，**未进入修复波次** |
| `lint/validator.py` | R6/R17 未实现、阈值硬编码 | ❌ 未修 | 同上，未进入修复波次 |
| `.env` cpolar 隧道外发 | 合规 | ❌ 未修 | `AST_AI_API_BASE=https://token.vip.cpolar.cn/v1` —— 持仓/财务/研判文本外发至第三方隧道，**需用户决策** |
| `screener/finance_batch.py` | 应收口径/总负债自加总 | ❌ 未修 | `total_liabilities` 仍为 `_sum_liabilities(raw)` 自加总 |
| `core/audit_engine.py` | 阈值硬编码、行业门控仅金融 | ⚠️ 部分 | Altman/Beneish 已门控，其余 12 框架未扩展 |
| `cli.py` 单文件巨石 | — | ❌ 未修 | — |
| `screener/tracker.py` | `(report_id, code)` 去重 | ⚠️ 未见显式唯一约束 | — |
| `data/eltdx_collector.py:340-343` | float32 尾数 | ❌ 未修 | 影响可忽略 |

---

## 7. 本轮复审新发现（详述）

### 7.1 N-1　宏观闸门被绑在最易缺失的数据源上（P0-1 残余）— 详见 §4.1

复现路径：`ladder_analyzer.analyze()` → `lad.rows` 为空 → `:88-100` 早退 → `macro_regime_result=None` → `pipeline.py:226` `getattr(sentiment_overview, "macro_regime_result", None)` → `None` → `apply_macro_gate(..., None)` → `status="UNVERIFIED"`、**不做任何约束**。

触发条件（均常见）：**盘前**（本次复审即在 07:38 命中）、周末/节假日、接口抖动、限板数据服务异常。

**注意**：`market_gate.py` 自身的实现是**正确的** —— 它对 `macro_result is None` 明确选择「不约束但标注 UNVERIFIED」并写入告警日志（`logger.warning("宏观闸门未核验…")`）。问题在**上游**：引擎明明能独立判定（只需要指数日线 + 全市场广度，这两项在实盘中**都拿到了**：上证 2026-10-29 收盘 3651.43、上涨 781/下跌 4728/涨停 39/跌停 42），却被梯子数据的空值挡在门外。

### 7.2 N-2　报告期全局化导致年化系数错配（P1-2 修复引入的回归）🔴

**代码路径**：`screener/finance_batch.py:203-217`

```python
def _latest_report_period() -> str | None:
    from data.eltdx_financial import available_periods
    periods = available_periods()
    return str(periods[0]) if periods else None      # ← 全局最新期
```

`:299-323` 把这个**全局值**写进**每一只**股票的 `FinanceSnapshot.report_period`，再用 `ANNUALIZE_FACTOR[rp[4:]]` 计算年化系数。

**问题**：`available_periods()` 返回的是**财报档案服务器上最新的 zip 期**，而非「每只股票各自的最新已披露报告期」。复审实测：

```
available_periods() → ['20260930', '20260630', '20260331', '20251231', ...]（共 100+ 期）
本地档案 .cache/eltdx_fin/ 各期收录公司数：
  gpcw20260630.npz → 5578 行（全部有数据）
  gpcw20260930.npz → **1688 行**（三季报仅披露 1688 家）
```

即 **2026-10-30 时点，约 3890 家（72%）公司尚未披露三季报**，其最新报告期是 **2026-06-30（半年报，年化系数 ×2）**，但代码给它们套用了 **2026-09-30 的 ×4/3**。

**逐股验证**（本地档案交叉核对 + `finance_batch` 实取）：

| 标的 | 在 20260930 档案中 | 真实最新报告期 | 代码所用系数 | 正确系数 | `finance_batch` 实取 `updated_date` |
|---|---|---|---|---|---|
| 605338 巴比食品 | ❌ 不在 | 20260630 | ×4/3 | **×2** | 2026-10-28 |
| 601398 工商银行 | ❌ 不在 | 20260630 | ×4/3 | **×2** | 2026-08-29 |
| 600519 贵州茅台 | ❌ 不在 | 20260630 | ×4/3 | **×2** | 2026-08-15 |
| 688722 同益中 | ✅ 在 | 20260930 | ×4/3 | ×4/3 ✓ | 2026-10-23 |
| 600036 招商银行 | ❌ 不在 | 20260630 | ×4/3 | **×2** | — |
| 002273 长城电器 | ❌ 不在 | 20260630 | ×4/3 | **×2** | — |

**量化影响**（用实取数据计算）：

| 标的 | 代码算出的 ROE | 正确半年报年化 ROE | 偏差 | 后果 |
|---|---|---|---|---|
| 601398 工商银行 | **5.35%** | **8.03%** | **-33%** | **< `TRACK_D_MIN_ROE=8` → 被 `D_ROE_TOO_LOW` 一票否决** |
| 600519 贵州茅台 | 2.36% | 3.54% | -33% | — |
| 605338 巴比食品 | **12.47%**（卡片显示 12.5%） | **18.70%** | **-33%** | 估值双锚失真 |

PE 方向相反：EPS 被低估 33% → **PE 被高估 50%**（茅台 PE 由 19.03 → 25.38）。

**这直接解释了复审实跑的漏斗**：`D_ROE_TOO_LOW: 827` 是轨道 D 的第二大淘汰原因（`D_PE_TOO_HIGH: 1662` 为第一）—— **其中相当一部分是口径错配造成的误杀**，而不是公司真的不赚钱。

**根本问题**：年报化的**季报系数必须逐股取**，而报告期可以从本地财报档案**逐股反查**（每个 npz 就是某一期，收录了当期已披露的公司）。

**建议修复**：
1. 新增 `data/eltdx_financial.py:report_period_map(codes) -> dict[str, str]`：按 `available_periods()` 降序遍历各期 `FinancialPeriod`，用 `fields_of(code)` 判断该股在当期是否有数据，返回**逐股最新报告期**；
2. `finance_batch.py` 的 `_to_snapshot(raw, report_period=latest_period)` 改为**逐股查表**；查不到 → `report_period=None` → 走现有的「未核验 → 放行并标记 UNVERIFIED」路径（该路径已存在且正确 ✅）；
3. 顺带解决「年化 ≠ TTM」：对已有多期报告期的标的，用 `core/derived_metrics.py` 的 TTM 能力直接算 TTM PE / TTM ROE（该模块已实现报告期感知），年化仅作为回退；
4. **回归测试**：用「20260930 档案只含 1688 家」这一事实构造用例，断言 601398 的 `report_period == "20260630"`、`roe_pct() ≈ 8.03`、`roe_basis == "annualized_20260630"`。

### 7.3 N-3　f-string 漏写 `f`，占位符泄漏到用户可见文案 🟡

`core/pillars/pillar5_decision.py:255`（原为普通字符串）：

```python
action_tactic = (
    "• 持币者 (耐心等待): 严禁追高，耐心等待估值回踩至 SOTP 锚底座 ({sotp_ps:.2f}元) 企稳再做评估。\n"
    ...
)
```

复审实跑 001225 的真实输出：

```
│ • 持币者 (耐心等待): 严禁追高，耐心等待估值回踩至 分部估值底座 │
│ ({sotp_ps:.2f}元) 企稳再做评估。                              │
```

`core/main_force_engine.py:940` 同型缺陷（`risk_alert` 中的 `{smart_vwap:.2f}`）—— 该文案在 STAGE_3「缩量洗盘蓄势期」分支命中即泄漏。

**状态**：本轮**已修补**（两处补 `f` 前缀），修补后 `644 passed, 1 skipped`。
**建议**：补一条 lint 规则 —— 扫描「非 f-string 常量中含 `{标识符:格式}` 且该标识符在同作用域存在」的形态（`lint/validator.py` 的 R6/R17 恰好是空位）。

### 7.4 C-1　首审误判更正（资金矩阵机构净买入）— 详见 §5.11（P1-11）

---

## 8. 已确认做得好的部分（重构时不要破坏）

1. **`screener/pipeline.py`** 已把涨停天梯从 universe 唯一来源降级为增强源，L0 用证券代码表 —— 避免「涨停才选股」的循环论证。实跑覆盖率 100.00%（5225/5225）✅
2. **`screener/filter_liquidity.py`** 一字板豁免条件已收紧为真一字（`high == low`），并对「不可核验 → 按常规门槛走」的保守方向做了显式声明 ✅
3. **`screener/filter_audit.py`** 默认全量排雷、按输入顺序回填并发结果 ✅
4. **`screener/universe.py` / `profile_batch.py`** 严格区分「不可核验」与「不合格」，缺失用 `None` —— 这正是 `youzi_personas.py` 修复前违反的同一标准，说明仓库内部标准不统一，而非标准不存在 ✅
5. **`core/derived_metrics.py`** 实现了报告期感知、TTM、同期同比、单季差分 —— **全仓库口径最扎实的模块，应作为 P1-2 后续修复的范式** ✅
6. **`core/judgment_chain.py`** 已避免用中文子串判断「好公司」 ✅
7. **`core/ai_coprocessor/guard.py`** 的「降级单向、无证据即弃权」设计正确，且**本轮已真正接到 pillar1~5** ✅
8. **`core/industry.py`** 让审计模型对自己的校准域外主动弃权 ✅
9. **漏斗归因模块自报死规则**：实跑输出「⚠️ 死规则（声明了但本次零命中）: TrackC/C_PREFILTER_TRUNCATED」—— 自我审查机制在起作用 ✅
10. **`screener/funnel_audit.py` + `pipeline.py` 的漏斗守恒**：`record_input = record_drop + record_output`，尾部补位用 `rebate_drop` 回冲 —— **这是全仓最严谨的计数纪律** ✅
11. **`screener/market_gate.py` 的缺值纪律**：`macro_result is None` → 返回 `None` 而非默认档，并写 WARNING 日志 ✅
12. **`screener/finance_batch.py` 的「未核验 → 放行 + 标记」**：`valuation_unverified` / `roe_trend="UNVERIFIED"` —— 「宁可放过，不能误杀」的取舍正确 ✅
13. **`screener/tracker.py` 的分母纪律**：不可成交样本剔出分母、毛/净收益并列展示 ✅
14. **644 个单测全绿（120.18s）** —— 工程基线扎实，且本轮新增 53 个测试 ✅
15. **`screener/finance_batch.py:182` 的批大小硬上限 100** —— 注释里写明了事故形态 ✅

---

## 9. 建议修复顺序（第二轮）

### 🔴 第一优先｜直接改变实盘输出（建议 1~2 天）

1. **N-1　宏观闸门解耦 + UNVERIFIED fail-closed**（§4.1 / §7.1）
   —— 这是 P0-1 从「代码已修」到「真的生效」的最后一步；
2. **N-2　报告期逐股反查**（§7.2）
   —— `report_period_map()` + `finance_batch` 改逐股查表；顺带评估接入 `derived_metrics` 的 TTM；
3. **P1-5　接入真实盘口/竞价/逐笔**（§5.5）
   —— `get_depth` / `auctions.series` / `minutes.buy_sell_strength` / `trades.today` 四个薄封装，`microstructure` 换真数据；
4. **P1-4　移除 `overhead_chip_pct` 的清仓触发权**（§5.4）
   —— 只保留描述性字段与口径标签，删掉 `pillar4_path.py:143` 与 `main_force_engine.py:736` 的触发项。

### 🟡 第二优先｜消除残余风险（建议 2~4 天）

5. **P1-7 残　一字跌停不可卖免责**（§5.7）—— 在 playbook 文案模板层统一追加，避免逐处手改漏改；
6. **P1-10　重写 `looks_like_financial_row` 判据 + 接入 `check_identities` + 行业门控扩展到全部 14 个框架**（§5.10）；
7. **§3.3 残　`screener/kline_batch.py` 补 `adjust="qfq"`** —— 轨道 B/C 的均线判据改用前复权；
8. **P0-4 残　账本历史记录回填 `track`**，并加 `(report_id, code)` 唯一约束；
9. **P1-14　`mode` 变成真实行为**（noon 用盘中快照 + 不同的涨跌幅/量能阈值，或直接下线 `--mode`）；
10. **P1-13 残　补一致性校验器** —— 「非核心/期权档位 ⇒ `position_cap == 0`」的硬断言；
11. **P0-3 残　字段名契约测试**（通用化，而非逐点修复）；
12. **N-3 残　lint 规则**：捕获漏写 `f` 前缀的格式化占位符。

### 🟢 第三优先｜口径与架构

13. **P2 复权改造收尾**（`kline_batch` + `profile_batch` 的一致性）；
14. **P2 `lint/validator.py`** 补 R6/R17、阈值外置 config；
15. **P2 `core/derivation.py`** 参数入 config、输出敏感性区间；
16. **P2 `screener/funnel_audit.py`** 记录每层入池/出池原因码快照（PIT）；
17. **P2 `screener/finance_batch.py`** 统一应收口径与总负债来源；
18. **P2 `.env` cpolar 端点** —— 数据外发边界，需用户决策；
19. **P2 `cli.py`** 拆分为子命令模块；
20. **同步修订 `README.md` / `docs/ARCHITECTURE.md` 的能力宣称**（P1-5 的「L2 十档 / 聪明钱 Q」在真正接入前应改口径）。

---

## 附录 A｜复审所用命令

```bash
# ── 单测 ──
python3 -m pytest -q -p no:cacheprovider       # 644 passed, 1 skipped in 120.18s

# ── 端到端 ──
python3 cli.py analyze 001225                  # 单股全链路（含真实 LLM 节点）
python3 cli.py screen --mode close --top 10    # 全市场漏斗（母池 5225 只）
python3 cli.py track                           # 胜率账本复盘

# ── 运行时探针（本文数据来源）──
# 行情/财务字段核对
python3 -c "from data.eltdx_collector import EltdxCollector as C; print(C().get_realtime_quote('001225').keys())"
# 宏观引擎独立判定（绕过 ladder_analyzer 的早退）
python3 -c "
from data.eltdx_collector import EltdxCollector as C
from core.macro_regime import MacroRegimeEngine
coll=C(); df=coll.get_daily('sh000001', count=30); st=coll.get_market_breadth()
ov=type('O',(),{'space_board_level':3,'space_board_tickers':[],'total_limit_up_count':45,
    'total_limit_down_count':9,'total_broken_count':12,'broken_rate_pct':21.0})()
r=MacroRegimeEngine().evaluate(trade_date='20261029', index_daily_df=df, market_stat_dict=st, ladder_overview=ov)
print(r.is_gate_open, r.macro_regime_label, r.composite_score)"
# 财报档案逐股期次反查（N-2 证据）
python3 -c "
import numpy as np
for p in ('20260930','20260630'):
    d=np.load(f'.cache/eltdx_fin/gpcw{p}.npz', allow_pickle=True)
    print(p, len(d['codes']), '605338' in set(d['codes'].tolist()), '601398' in set(d['codes'].tolist()))"
# eltdx 真实能力盘点（P1-5 证据）
python3 -c "
import inspect, eltdx.client as m
for c in ('QuoteApi','MinuteApi','AuctionApi','TradeApi'):
    print(c, [n for n,_ in inspect.getmembers(getattr(m,c), predicate=inspect.isfunction) if not n.startswith('_')])"
# 金融行判据在真实数据上的表现（P1-10 证据）
python3 -c "
from data.eltdx_collector import EltdxCollector as C
from data import eltdx_financial_map as f
for code in ('600519','601398','600036','002273','601318'):
    raw=C().get_financial_reports(code)['balance_raw'][-1]
    print(code, f.looks_like_financial_row(raw))"
```

## 附录 B｜关键实测数据速查（复审版）

| 项 | 实测值 |
|---|---|
| 母池规模（2026-10-30） | 5225 只（覆盖率 100.00%）；L0 出 5026、L1 出 5005、T1 出 34、T2 出 33、T3 出 10 |
| 2026-10-29 市场 | 上证 3651.43 (-0.82%)；上涨 781 / 下跌 4728；涨停 39 / 跌停 42；炸板率 40.0% |
| **宏观引擎独立判定** | `is_gate_open=False`，`【大盘震荡分化与结构轮动】`，score **32.2**，`single_name_cap_pct=0.0` |
| **盘前实跑闸门状态** | **UNVERIFIED**（梯子数据为空 → 早退 → `macro_result=None`）→ 仍输出 25%/20% 仓位建议 |
| 轨道 D 淘汰归因（复审） | `D_PE_TOO_HIGH:1662 / D_AMOUNT_BELOW:1275 / D_ROE_TOO_LOW:827 / D_PB_TOO_HIGH:673 / D_OCF_WEAK:226` |
| 轨道 B/C 淘汰归因 | B: `B_PREFILTER_OUT:2300 / B_NO_RECENT_LIMIT_UP:2057 / B_TOO_WEAK_TODAY:389`；C: `C_MARKET_CAP_TOO_SMALL:3379 / C_MA_NOT_BULLISH:40` |
| 茅台 2026 半年报 Altman（修复后） | RE = 199,683,216,816.2 元；Z **6.0342**（旧口径 5.1296，**+0.9046**） |
| **20260930 财报档案覆盖** | **1688 / 5578 家**（20260630 期为 5578 家）→ 72% 公司的年化系数被错配 |
| **年化系数错配量化** | 工行 ROE 代码 5.35% vs 正确 8.03%（-33%，被 `D_ROE_TOO_LOW` 否决）；茅台 2.36% vs 3.54%；巴比 12.47% vs 18.70% |
| 巴比食品 PE（复审卡片） | 16.2（= 19.0 / (0.88 × 4/3)）；首审静态 21.57 / 腾讯 TTM 16.05 |
| 主力阶段（001225，修复后） | 「🔥 健康放量主升期」置信度 **61.0%**（⚠️多空过渡区）；换手 **7.99%** 已入判据 |
| 账本复盘（389 条） | 77 可成交 / 18 一字板剔出 / 294 待 T+1；胜率 50.6%；净 +0.08% vs 毛 +0.18%；盈亏比 1.05 |
| 账本分轨 | 274 条带 `track`（全部为 2026-10-30 新增，尚无 T+1）；115 条旧记录无 `track` → 占 overall 分母 100% |
| 竞价量占比（20 样本） | 最小 0.53% / 中位 3.08% / 最大 5.54%；≥15% 命中 0/20 → 阈值已改 3% |
| 工行不复权 vs 前复权（60 日） | MA20 偏差 1.17%；10/20/60 日涨幅偏差 -1.86/-2.03/-2.02 pct；除权日 2026-10-21 假跌 -1.52%（真实 +0.24%） |
| eltdx 3.3.0 未被使用的能力 | `quotes.get_depth` / `minutes.buy_sell_strength` / `auctions.series` / `trades.today` / `trades.opening_match_today` |
