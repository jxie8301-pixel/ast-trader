# AST-Trader 未实施工作清单 (Unimplemented Worklist)

> **文档性质**：本文件是 AST-Trader 尚未实施工作的**权威状态表**，用于排期与跟进。
> 所有条目均经**代码实证核对**（文档声明不作为实现证据）。
> 条目状态变更须与代码同步更新，避免重演「文档宣称完成、代码未落地」的漂移。

**基线**：Git 工作区 · Python 3.13 · `pytest -q` **360 passed**（349 离线 + 11 `seednet`）
（⚠️ 本轮联网批次未跑批；离线 321 项已确认，真实连通性另经 `ping()` + 快照冒烟验证）

> **本轮变更（借鉴上游 Ashare-researchreport，2026-10-28）**：以 GitHub 上游
> **方法论与架构**为准（代码不回退 —— 实测 `origin/main` 是更旧的 v8.14，
> 本地 v8.25 领先 14 个提交，全部为 eltdx 迁移成果），补齐四层缺失能力：
>
> | 层 | 产出 | 状态 |
> |:---|:---|:---:|
> | 数据层 | `data/eltdx_client.py` 就绪门 + 异常归一；`data/degraded.py` 缺值集中声明 | ✅ |
> | 契约层 | `core/schemas/` 三份 Schema + `core/schema_validator.py` | ✅ |
> | 门控层 | 补齐 R1/R2/R3/R4'/R5/R14/R15/R16/R18（默认 warn） | ✅ |
> | 证据层 | `data/pdf_reader.py` + `data/announcement_corpus.py`（页码级引用） | ✅ |
> | 判断层 | `core/ai_coprocessor/`（降级守卫 + 单向阀提名池 + 5 份 prompt） | ✅ |
>
> **展示层通俗化 + 情景研判接入**：新增 `presentation/plain_language.py`（白话层）。
> ★ **只做展示翻译，绝不回写决断卡** —— 因此 16 条门控规则与既有回归全部不受影响。
> 三处可见改动：顶部「一句话结论」、五大支柱白话标题、底部按需术语速查；
> 并把此前只在内存里的 `scenario_note` 真正渲染进终端与 HTML（标注「不含价位」）。
> ★ 替换表经历了三轮真实报告的毒打，最终收敛出三条**硬规则**（均有测试守住）：
>   ① `TERMS`（速查用，释义可长）与 `SUBSTITUTIONS`（正文替换用，替换后 ≤12 字）
>      必须分开 —— 混用会把「竞价」展开成一整句，句子彻底读不通；
>   ② 替换必须**两遍 + 占位符**，否则替换结果会被后续规则二次改写
>      （真实事故：「知情均线」→「主力成本线」→「大资金成本线」）；
>   ③ **两字以内的中文词一律不得进替换表** —— 中文没有词边界，
>      「游资」命中「下**游资**本」，把「等待行业下游资本开支指引」毁成
>      「等待行业下短线活跃资金本开支」。两字词只做术语速查解释。
>
> **eltdx 主站节点可配置（附修一个真实 Bug）**：新增 `data/tdx_hosts.py`，
> 把 7709 主站补齐到与 7727 对称的四级可覆盖配置（显式参数 > `AST_TDX_HOSTS`
> 环境变量 > `tdx_servers.json` > 历史配置 > eltdx 内置 43 台池作故障转移尾巴）。
> ★ 顺带修掉 `open_client` 里 `TdxClient(host=, port=)` 的 `TypeError`
> —— **eltdx 的 `TdxClient` 没有 `port` 参数**，端口必须写在 host 串内，
> 这条路径此前一旦走到 `host and port` 分支必然抛错。
> ★ 严守红线：绝不从线上拉取主机名单（供应链风险），配置只来自本地。
>
> **A-1 已 5/5 全接线**：`moat`→`judgment_chain`①质地 Q3、`catalyst`→②状态「该等什么」、
> `governance`→`audit_engine.run_audit`、`theme_purity`→`cli` 红旗池、
> `tactic`→`execution_playbook.build`。三处上下文统一走 `ai_coprocessor/context.py`，
> 避免 cli 与决断链各拉一批公告导致结论互相打脸。
> ★ `tactic` 刻意**只写新增字段 `scenario_note`**，绝不覆盖 `entry_tactic` ——
> 后者含挂单价位，而 AI 被明令禁止输出价格，整体替换会抹掉价格单点真理。
**最近更新**：2026-10-28（第一批「验收补齐」实施完成）

---

## 0. 状态总览

| 类别 | 条目数 | 已完成 | 未实施 | 阻塞 |
|:---|:---:|:---:|:---:|:---:|
| A. 规划中的增强模块 | 4 | 1 | 3 | 0 |
| B. 增强模块集成点 | 5 | 0 | 5 | 5 |
| C. SRS 承诺未落地 / 未验收 | 7 | 3 | 4 | 1 |
| D. P0 修复后遗留 | 35 | 28 | 7 | 1 |
| E. 死配置与失效参数 | 4 | 4 | 0 | 0 |
| F. 文档漂移 | 8 | 8 | 0 | 0 |
| **合计** | **63** | **43** | **20** | **10** |

> ### ★ 标的口径声明（业务决策，非数据缺失）
>
> 本项目**只做沪深 A 股**（沪市 + 深市），**北交所为业务性永久排除**。
> 20261028 实测对账基准：`codes.a_share_count("sh")=2319` + `("sz")=2906` = **5225 只**。
>
> * 北交所在 L0 母池层产出**显式**剔除码 `BSE_OUT_OF_SCOPE`，**不靠成交额门槛隐式排掉**
>   （隐式排除会让对账表永远少一行，将来无法回答"为什么少了这些票"）；
> * 代码表若混进北交所标的会触发防御告警；
> * `helpers.market_stat()` 的 `total_count` 实测为 **55760**（口径是"全部证券"，含
>   基金/债/指数/北交所），与 A 股分母**不可比**，只作信息记录，绝不参与闸门判定。
>
> ### ★ 沪深 A 股代码表实测取值域（20261028 全量 5225 只）
>
> * `category`：恒为 `a_share`；
> * `board`：仅 4 值 —— `sse_main_board`(1700) / `sse_star_market`(619) /
>   `szse_main_board`(1495) / `szse_chinext`(1411)；
> * 代码前缀分布中出现 **`689`**（科创板 CDR）与 **`302`**（深市新代码段），
>   二者均**不在**改造前的 `is_gem_star` 前缀表内 —— 这说明**前缀表会过期**，
>   板块判定一律以 `board` 为准，前缀仅兜底。
>
> ### ★ 数据源成本实测（决定架构，不是设计偏好）
>
> | 通道 | 实测成本 | 结论 |
> |:---|:---|:---|
> | `helpers.stock_profile_table` | 200 只 0.32s | ✅ 可全市场（26 批）；换手率/市值/上市日期一次拿全 |
> | `corporate.finance_batch` | 100 只 0.03s（**静默截断在 100**） | ✅ 可全市场（须切批）；轨道 D 的估值/ROE/现金流全靠它 |
> | `bars.get` | **26ms/只，与根数无关**（count=6 与 70 同为 200 只 ~5.3s） | ❌ **不可全市场**（5225 只 ≈130s）；必须先由免费字段压缩候选 |
> | `helpers.shortline_indicators` | **63ms/只**（首调含 zhb.zip 6.3s），且连板字段大量为 None | ❌ 不可全市场；仅用于存活集 |
> | `f10.valuation` / `finance_diagnosis` | 前者只返回分页计数、后者 0 行 | ❌ 无 PE/PB/ROE，改用 `finance_batch` 自算 |
> | `f10.ranking_detail` | `scpmdela` 有市场排名 `pm`；`hypmdela`/`hypm` **返回空** | ⚠️ 行业排名不可得，降级；市值分位改为对全池自算 |
| `f10.finance_report` | 一次返回 **32~114 个报告期**（`rq`），268ms/只 | ✅ **多期财报拐点可核验**（纠正 D-26 的误判） |
| `CWServ.tdxf10_gg_gdyj`+`ltgd` | **10 名股东 × 18 期**，`lb` 类别 + `cgs` 持股数，293ms/只 | ✅ **机构持股可核验**（纠正 D-27 的误判） |
| `CWServ.tdxf10_gg_zbyz`+`gqzy` | 3 表：公司累计质押 / 各股东质押 / 质押流水 | ✅ **股权质押可核验**（通道一直存在，缺陷是 D-30 的口径错配） |
>
> ### ★ 四轨分流实测产出（20261028 CLOSE，母池 5225 / 活跃 5026）
>
> | 轨道 | 存活 | 主要淘汰归因 |
> |:---|:---:|:---|
> | A 超短连板接力 | Top 5 | `AMOUNT_BELOW_BOARD:4078 / TURNOVER_OUT_OF_RANGE:676 / PCT_OUT_OF_RANGE:129` |
> | B 弱转强/首阴反包 | **20** | `B_PREFILTER_OUT:1919 / B_NO_RECENT_LIMIT_UP:1570 / B_NOT_WEAK_TODAY:1352` |
> | C 产业中军 | **8** | `C_MARKET_CAP_TOO_SMALL:3346 / C_AVG_AMOUNT_BELOW:242 / C_MA_NOT_BULLISH:150` |
> | D 价值成长 | **109** | `D_PE_TOO_HIGH:2085 / D_AMOUNT_BELOW:1266 / D_ROE_TOO_LOW:778 / D_TREND_DETERIORATING:43` |
>
> 轨道 C 已按**机构持股占比**降序排列（中国核电 49.0% → 邮储银行 3.9%）；
> 轨道 D 每只标注**边际拐点档位**（由负转正 / 加速 / 平稳 / 未核验）。

---

## A. 规划中的增强模块（阶段二/三）— 全部未启动

来源：`docs/FUTURE_OPTIMIZATION_SPECIFICATIONS.md` §2~§5、`§6.2` 三步走计划
依赖：B 类集成点

| ID | 内容 | 计划模块 | 状态 | 未实施原因 / 阻塞 |
|:---|:---|:---|:---:|:---|
| A-1 | 本地轻量 AI 语义协处理器（买方导读润色 / 年报附注挖掘 / 红蓝对抗证伪） | `core/ai_coprocessor/` | 🟨 **部分完成** | ✅ **已完成（5/5 接线）**：`provider`/`cache`/`guard`/`context`/5 份 prompt，三条硬边界（只能降级 / 只能加风险 / 失败即弃权）已实装并测试。接线点：`moat`→`judgment_chain`①质地 Q3、`catalyst`→②状态「该等什么」、`governance`→`audit_engine.run_audit(ai=)`、`theme_purity`→`cli._merge_theme_nominations`、`tactic`→`execution_playbook.build(ai=)`（仅新增 `scenario_note` 字段）。★ 提名级别双重封顶（`parse_payload` + `nominations_to_flags`），AI 永远无法触发致命封顶。⚠️ 默认 `AI_ENABLED=False`，需显式开启；单股 analyze 实测约 100s |
| A-2 | 行业板块相对强弱轮动矩阵 `SectorRSMatrixEngine`（RS 三维度评分 + 四阶段 + 仓位乘数） | `core/sector_rs.py` | ⬜ 未实施 | 依赖 B-1 板块行情采集；阶段二 Week1 未排期 |
| A-3 | 龙虎榜席位协同与游资胜率跟踪 `LHBSynergyTracker`（`KNOWN_SEAT_PERSONAS` + 4 类协同模式） | `core/lhb_synergy.py` | ⬜ 未实施 | 阶段二 Week2 未排期；现存 `seat_matcher.py` 仅有静态中文映射，无属性标签 |
| A-4 | 实盘账本多日回测与收益归因 `TrackerBacktestEngine`（胜率/盈亏比/最大回撤/夏普） | `screener/backtester.py` | ⬜ 未实施 | 🚧 需实盘账本积累足够样本；现有 `tracker.py` 仅 T+1 单日复盘 |

---

## B. 增强模块集成点 — 全部未打通

| ID | 内容 | 位置 | 状态 | 说明 |
|:---|:---|:---|:---:|:---|
| B-1 | 采集层扩充 `get_sector_bars()` / `get_sector_money_flow()` | `data/eltdx_collector.py` | ⬜ 未实施 | 该文件 9 个公开方法无任何板块级接口；阻塞 A-2 |
| B-2 | Tier 3 引入板块 RS 加权，退潮期扣 10 分 | `screener/rank_composite.py` | ⬜ 未实施 | 依赖 A-2、B-1 |
| B-3 | `_decide_gear` 中 `final_pos_cap *= sector_rs_multiplier` | `core/judgment_chain.py` | ⬜ 未实施 | 依赖 A-2 |
| B-4 | 席位属性驱动集合竞价挂单区间 | `core/execution_playbook.py` | ⬜ 未实施 | 依赖 A-3 画像库（本批 E-4 已用 `SEATS.style` 做**降级版**接线） |
| B-5 | `python cli.py backtest` 子命令 | `cli.py` | ⬜ 未实施 | 依赖 A-4；现有子命令仅 `analyze`/`screen`/`track` |

---

## C. SRS 承诺未落地 / 未验收

来源：`ARCHITECTURE_AND_SRS.md`。M1~M3 里程碑文档标记为已交付，但下列验收项未完成。

| ID | 需求 | 位置 | 状态 | 说明 |
|:---|:---|:---|:---:|:---|
| C-1 | FR-05「12 条机器硬规则」 | `lint/validator.py` | ✅ **本轮扩至 16 条** | 既有 fail 级 7 条（R7~R13）＋本轮补齐 R1/R2/R3/R4'/R5/R14/R15/R16/R18（**默认 warn**，改 `config.LINT_RULE_SEVERITY` 即可转 fail）。⚠️ **更正历史结论**：此前写「R1~R6 在任何文档中均无内容定义」经核对**不成立** —— 上游 `lint_v8.py` 的 R1~R6 均有实现（R1 :169 / R2 :202 / R3 :260 / R4 :306 / R5 :521 / R6 :626），是移植遗漏而非上游未定义。★ 刻意不移植：R6（外链引用，无 md 互引形态）、R11（散文密度，上游自认无阻断力）、R17（已兑现倍数，无对应产物，风控意图已由 R12 覆盖） |
| C-2 | FR-03 席位「善庄/量化/游资」属性标注 + 胜率跟踪 | `core/seat_matcher.py` | ⬜ 未实施 | 取数侧已真实联网（`supplement_api.fetch_lhb_seats`，东方财富 `RPT_DAILYBILLBOARD_DETAILS`，近 30 天过滤）；但无 `persona/tag` 属性与胜率 |
| C-3 | §8.1 已知造假样本 100% 触发致命红旗 | `tests/test_audit.py` | 🟨 部分完成 | 本批新增 5 项合成造假样本用例（Beneish 致命 + Sloan + Buffett 应收/存货 + 三框架交叉印证 + 健康对照）。**真实公司样本待数据接入**（见 D-7 同类阻塞） |
| C-4 | §8.3/§8.4 性能验收（screen ≤15s、analyze ≤2s、内存 ≤500MB） | `pytest.ini` / `tests/` | ⬜ 未实施 | 无任何耗时断言；需联网基准，未纳入 CI |
| C-5 | NFR-02「缺失置 None，严禁填 0」 | `core/audit_engine.py` | 🟨 **第一批已完成** | ✅ 已清理 **22 行 / 23 处** `or 0.0`：Piotroski 3、DuPont 8、Buffett 质量 10、投资收益侵蚀 2（1 行 2 处）。改为缺失置 None + 上游 `is None` 判据 + 模型弃权；新增 `_first_present()` 消除 `or` 把真实 0.0 误判为缺失的副作用。✅ 已先建测试围栏（`tests/test_audit_missing_fields.py`）再改造。★ 实测：Beneish / Altman / Sloan / 治理 / 估值等**本就无** `or 0.0`，不在范围。⚠️ 更正历史结论：`_safe_float` 的默认参数**本来就是 None**（符合纪律），显式 `_safe_float(x, 0.0)` 调用为 **0 处**（旧记录里命中于 :724 的注释文字）。⚠️ R10 仍保持只校验枚举取值域：**0 本身是合法财务取值**（如「无商誉」） |
| C-6 | §8.2 门控机检须「抛出异常」 | `lint/validator.py` | ✅ **已裁决（以代码为准）** | **冲突已解除**：`ARCHITECTURE_AND_SRS.md` §8.2 已改为「以纠代抛：降级为 `等证据临界(观察)` / `回避` + `position_cap` 清零」。`LintError` 标注 `.. deprecated::` 保留兼容语义，全仓仍从不 raise。理由：抛异常会让 `screen` 全市场跑批因单票异常整体中断 |
| C-7 | FR-06 换手率 8%~25% | `config.py` | ✅ 本批完成 | `MOMENTUM_MIN/MAX_TURNOVER_RATE` 由 7.0/28.0 改为 **8.0/25.0**，对齐 SRS |

---

## D. P0 修复后遗留（来自真实数据跑批）

来源：`docs/SEED_VALIDATION_REPORT.md` §5。P0-1~P0-4 已于 2026-10-28 修复（见该文档 §6）。

| ID | 内容 | 位置 | 状态 | 说明 |
|:---|:---|:---|:---:|:---|
| D-1 | P1-1 估值与审计红旗联动（命中财务操纵致命红旗 → 赔率置未核验） | `_build_pillar_3_odds` | ⬜ 未实施 | 平安银行曾出现「财务操纵高风险」却判「便宜」 |
| D-2 | P1-2 北交所独立成交额档位 `LIQUIDITY_BSE_MIN_AMOUNT` | `config.py`、`filter_liquidity.py:49` | ⬜ 未实施 | 现仅 MAIN/GEM 二选一；同文件 `:66` 已有 `is_bse` 判定，属自相矛盾 |
| D-3 | P1-3 Tier 2 覆盖全部候选 | `screener/filter_audit.py`、`screener/pipeline.py` | ✅ **已完成** | 原 `top_audit_count=15` 无条件截断，第 16 名后不排雷即进 Tier 3。现默认 `None`=全量排雷；**同时**把 `as_completed` 改为按输入索引保序回填（原实现输出是线程完成序，会让 `rank_composite(top_n=)` 截取不可复现）。回归见 `tests/test_screener.py` |
| D-4 | P1-4 买入路径注入式回归 | `tests/` | ⬜ 未实施 | 10 只种子 100% 零仓位，买入分支从未被真实触发 |
| D-5 | P2 声明 `screen` 适用域 | `docs/ARCHITECTURE.md` | ⬜ 未实施 | 需澄清「短线题材接力」vs「买方深度投研」定位 |
| D-6 | P0-4 残留：重资产科技/制造业 Altman 误报 | `audit_engine.py`、`config.AUDIT_MODEL_INDUSTRY_BLOCKLIST` | ⬜ 未实施 | 中芯国际 🔴「破产高危」、宁德时代 🟠「财务状况脆弱」仍存在；本轮准入仅覆盖金融业 |
| D-7 | 股权质押真实数据源接入 | `data/eltdx_collector.py` | ✅ **已完成** | 接入通达信 F10 资本运作网关 (`CWServ.tdxf10_gg_zbyz` section="gqzy" 或 `f10.equity_pledge`)，真实解析主要股东质押率 (t021) 与全公司累计质押，彻底打通大股东高质押排雷与质地五问 Q4 实证核验，解开历史死锁 |
| D-8 | 物种分流兜底误判「机构趋势与产业中军」 | `core/judgment_chain.classify_stock_track` | ✅ **已完成** | 非连板、未达市值门槛、换手 <6% 且无概念标签时原无条件兜底成 B 轨，导致 58.7 亿市值的永安行及微盘股被冠以「产业中军」；而 B 轨在弱市享有「情绪防守」豁免，等于开了拿核心仓档位的后门。现新增第三轨 `TRACK_UNVERIFIED` 并纳入 `TRACK_DEFENSIVE_ON_ICE`（B 轨刻意不在内）。回归见 `tests/test_judgment_enhancement.py` |
| D-9 | 反向 DCF `implied_margin` 硬编码 16.5% | `core/derivation.py` | ✅ **已完成** | 既无数据源也无推导过程，属**凭空捏造的默认值**，违反 SRS §6.3。现置 `None` 并附 `implied_margin_basis` 标注未核验；同函数魔数 `15.0 / (1/5) / 25.0 / 1.2 / 35.0 / 20.0` 已具名化为 `REVERSE_DCF_*` 常量；锚点非正时 `implied_cagr` 亦置 `None`（不再兜 25.0）。回归见 `tests/test_derivation_discipline.py` |
| D-10 | 质地五问 Q4 把质押率 `or 0.0` 兜底 | `core/judgment_chain._build_pillar_1_quality` | ✅ **已完成** | 兜成 0.0 会断言「质押率 0.0% 处于安全线内」，把「通道不可得」伪装成「确认无质押」。现新增 `_normalize_pledge_pct()` 保持 None 透传并归一分数制/百分数制口径，未核验时 Q4 显式标注。回归见 `tests/test_derivation_discipline.py` |
| D-11 | **候选池根本不是全市场**（名不副实） | `screener/pipeline.py`、`screener/ladder_analyzer.py` | ✅ **已完成** | 候选池唯一来源是 `f10.limit_board_ladder()` 的当日封板行 —— 「谁能参选」由第三方涨停事件流决定。20261028 实测：涨停 71 只 / 沪深 A 股 **5225** 只 = **1.4%**，98.6% 的标的连被任何规则评估的资格都没有。现新增 `screener/universe.py` 用 `codes.a_shares(sh/sz)` 自主建池，`limit_board_ladder` 降级为「轨道 A 连板身位与题材增强源」。实测：扫描 5225 / 预期 5225，覆盖率 100%，活跃母池 5026（剔除 ST 194 / 停牌 4 / 退市 1） |
| D-12 | **Tier 1 换手率门槛是死代码** | `screener/filter_liquidity.py`、`screener/pipeline.py` | ✅ **已完成** | `pipeline._fetch_quotes_map` 只装 `{close, pre_close, pct_chg, amount}` 四个键，而 `filter_liquidity` 读 `turnover_ratio` —— 恒 0.0，`if turnover > 0.0` 恒 False，**8%~25% 这条规则从未拦下过任何一只票**。根因是 `QuoteSnapshot` 根本没有该字段。现改用 `helpers.stock_profile_table` 提供真实 `turnover_rate`。20261028 实跑：该规则本次淘汰 **676** 只（此前恒为 0） |
| D-13 | **首板涨停死锁：非涨停不选、涨停了又不让买** | `screener/rank_composite.py` | ✅ **已完成** | `if pct_val >= 7.0 and not leader: wait_pullback` 把所有首板涨停（占涨停池 88.7%）判成追高并清零仓位，而 Tier 0 又规定非涨停不得入池 ⇒ 精选池恒为 0% 看戏（20261028 实测 5 只全部 `仓位 0% /【观察】`）。现新增第五态 `wait_auction`：当日不建仓，给出次日 9:25 可客观验证的竞价条件（高开≥2% 且竞价量≥昨日全天 15%）与试错仓。实跑后 Top5 出现 **4 只 buyable / 20% 仓位** |
| D-14 | 板块判定漏 `689` / `302`，误用主板阈值 | `screener/filter_liquidity.is_gem_star` | ✅ **已完成** | 原只认 `300/301/688`。20261028 全量实测发现科创板 CDR **689**（1 只）与深市新代码段 **302**（1 只），会被当主板用错涨跌幅上限（10.5% vs 20.5%）与成交额门槛（5亿 vs 3亿）。现以代码表 `board` 为准（实测取值域仅 `sse_main_board / sse_star_market / szse_main_board / szse_chinext`），前缀仅兜底；未见过的新 board 只告警不剔除 |
| D-15 | 终端渲染把真实判定掩盖成默认值 | `presentation/terminal_view.py` | ✅ **已完成** | `card = item.get("card", {})` 在 screen 流程恒取到 `{}`（pick 里没有该键）⇒ 梯队身位恒定显示「首板/潜伏」、决断档位恒「观察」、仓位恒 `0%`。用户据此得出「5 只全是首板」的误判（账本证明其中 2 只为连板走 `wait_reseal`）。现已从 pick 自身取数；另修 10 列固定宽 112 > 终端 83 列导致每列被截成「…」的问题（改为 `overflow="fold"` 折行） |
| D-16 | 游资画像输入被伪造（量比恒 1.5 / 治理风险恒 False / 硬事件恒 True） | `screener/rank_composite.py`、`core/youzi_personas.py` | ✅ **已完成** | `momentum_proxy={"volume_ratio": 1.5}` 是凭空捏造、恒为定值的假量比，与 `derivation.py` 硬编码 16.5 属同类数据纪律问题；它使「连板股匹配不到画像 → wait_reseal → 0 仓位」长期无法归因。现量比改传 `None`（`extract_tape_features` 已改为可缺失、判据弃权），治理风险改由 Tier 2 真实违规计数驱动，硬事件改为 `bool(concepts)` |
| D-17 | Tier 2 前 15 名无声物理截断 → Tier 2 队列限流无声 | `screener/pipeline.py` | ✅ **已完成（本批再修）** | 上一批已把硬编码 `top_audit_count=15` 改为全量。母池放开到 5026 只后，Tier 1 存活集可达数百只，逐只调 F10 会把跑批拖到分钟级。现新增 `config.UNIVERSE_MAX_AUDIT_QUEUE=120` 显式限流，**且截断写入归因矩阵**（`AUDIT_QUEUE_TRUNCATED`），并按（连板身位, 成交额）降序截断 —— 与旧版「按天梯原始顺序无声丢掉 15 名之后」有本质区别 |
| D-18 | 无「证明真跑了全市场」的机制 | `screener/universe.py`、`screener/funnel_audit.py`、`presentation/terminal_view.py` | ✅ **已完成** | 新增覆盖率闸门（`scanned / expected < 0.98` 拒绝出结果；分母取 `codes.a_share_count(sh)+a_share_count(sz)`，不可得即 Fail-Closed）与逐层淘汰归因矩阵（`input == Σ dropped_by_reason + output` 守恒断言 + **死规则检测**：声明了却零命中的判据自动告警 —— D-12 的死代码正是靠这条机制才能暴露）。终端新增「沪深全市场母池对账与漏斗归因」面板 |
| D-19 | 炸板/烂板行被物理丢弃 ⇒ 池子里没有"弱"，何来弱转强 | `screener/ladder_analyzer.py` | ✅ **已完成** | `analyze()` 此前只返回封板行，`broken_rows` 算完情绪统计即丢弃。按 20261028 炸板率 49.6% 反解约 **70 只**/日被白白丢掉 —— 而"弱转强"必须以"弱"为前提，纯封板池在物理上不存在弱转强的逻辑条件。现 `analyze()` 返回 4 元组并导出 `raw_broken_rows`，作为轨道 B 的「弱」之来源 |
| D-20 | 无轨道 B（弱转强/首阴反包） | `screener/tracks.py`、`screener/kline_batch.py` | ✅ **已完成** | 新增轨道 B 准入：近 3 日曾涨停 + 今日走弱 + 缩量（量/昨量 ≤0.8）+ 未破 MA5 + 未大幅低于均价。★ 硬约束：日 K 实测 **26ms/只**（与根数无关），全市场 5225 只 ≈130s 不可扫 ⇒ 必须先用免费字段（炸板/收阴+成交额）把候选压到数百只再懒加载。实跑存活 20 只，剔除归因 `B_PREFILTER_OUT:1919 / B_NO_RECENT_LIMIT_UP:1570 / B_NOT_WEAK_TODAY:1352 / B_VOLUME_NOT_SHRUNK:132 / B_BELOW_MA5:10` |
| D-21 | 无轨道 C（产业中军），中军永远选不出 | `screener/tracks.py` | ✅ **已完成** | 判据：市值分位（**对全池自算**，实测 `ranking_detail` 的 `hypmdela/hypm` 行业排名 section **返回空**）+ 均线多头（`Close>MA5>MA20>MA60`）+ 20 日日均成交额 ≥8 亿 + 换手分档。★ 「机构持股占比 ≥15%」无数据通道，显式标 `UNVERIFIED` 不参与准入（用户裁决） |
| D-22 | **轨道 C 换手率门槛会误杀全部大市值中军** | `config.py:TRACK_C_TURNOVER_BANDS` | ✅ **已完成** | 实测美的集团(000333，市值约 5800 亿)当日换手仅 **0.345%**。用户原方案「换手 1.5%~5%」会把所有大市值中军整体误杀 —— 而它们正是轨道 C 的目标。改为**按市值分档**：≥1000 亿 0.2%~3.0%、100~1000 亿 0.5%~5.0%。修复后轨道 C 由 2 只升至 8 只 |
| D-23 | 无轨道 D（困境反转/价值成长） | `screener/tracks.py`、`screener/finance_batch.py` | ✅ **已完成** | ★ 实测 `f10.valuation` 只返回分页计数（`num/total_num`）**无 PE/PB**、`f10.finance_diagnosis` 返回 **0 行** ⇒ 估值双锚与 ROE/现金流全部改由 `corporate.finance_batch` 自算（单位：金额千元 / 股本万股，已用贵州茅台交叉验证 `净资产/总股本 = BVPS 200.99`）。该接口 100 只仅 0.03s ⇒ 轨道 D 是**唯一能近乎免费全市场扫描**的轨道（5225 只 ≈2s），实跑存活 152 只 |
| D-24 | **`corporate.finance_batch` 静默截断在 100 只** | `screener/finance_batch.py` | ✅ **已完成** | 请求 300 只**只返回 100 只且无任何告警**。若不强制切批，轨道 D 会在完全无声的情况下丢掉 2/3 标的 —— 又一个"静默缩小母池"事故。现批大小硬上限 `FINANCE_BATCH_SIZE=100`，且以返回记录的 code 建索引，绝不假设"请求 N 只回来 N 只" |
| D-25 | 预筛把多个判据合并成一个 reason_code ⇒ 内部判据结构上恒为 0 | `screener/tracks.py:prefilter_*` | ✅ **已完成** | 首跑复现 9 条死规则误报：`C_MARKET_CAP_TOO_SMALL` / `C_TURNOVER_OUT_OF_RANGE` 等判据因被合并进 `C_PREFILTER_OUT`，在归因矩阵里**永远为 0**。改为预筛**逐判据**归因后误报清零。★ 教训：任何"合并记账"都会让死规则检测失去意义 |
| **D-26** | **误判「ROE 边际拐点不可得」—— 实为用错通道** | `screener/f10_deep.py` | ✅ **已纠正** | 此前断言"`finance_batch` 只给单期快照 ⇒ 拐点不可核验"。**这条是错的**：`CWServ.tdxf10_gg_cwfx`（`f10.finance_report`）一次返回 **32~114 个报告期**（美的 57、茅台 103、格力 114），每行带 `rq`。现已实现真·拐点：归母净利润 `T030` 同比 + 边际变化（**用同比而非环比**：A 股财报是累计口径，环比会与季节性混淆出伪信号），净资产用恒等式 `T039 - T053`（不猜"归母权益"是哪个 T 字段）。★ 用户质疑促成此纠正 |
| **D-27** | **误判「机构持股无数据通道」—— 实为用错 Entry** | `screener/f10_deep.py` | ✅ **已纠正** | 此前断言"eltdx 不给前十大流通股东"。**这条也是错的**：`CWServ.tdxf10_gg_gdyj` + `section="ltgd"` 的 `tables[1]` 返回 **10 名股东 × 18 个报告期**，每行带 `lb` 类别标签（实测：基金/保险/QFII/券商/社保/北上资金/资管计划/私募证券投资基金/特殊法人/一般法人/自然人）与 `cgs` 持股数。★ 关键口径：**一般法人（控股股东/产业资本）不计入机构** —— 美的控股占十大流通股东 48.6%，若计入则任何有大股东的公司都会虚假地"机构重仓" |
| D-28 | 不可核验项被同时记入"淘汰"与"输出" ⇒ 归因不守恒 | `screener/tracks.py:apply_track_d_trend` | ✅ **已完成** | 首跑 `TrackD ⚠️不守恒(差额 -6)`。根因：`D_TREND_UNVERIFIED` 的标的**保留在输出里**却被同时记进 `dropped`，造成重复计数。修复：不可核验只作**第三个返回值**用于日志与面板，**绝不进归因矩阵**；它也不登记进 `TRACK_RULES`（它不是判据而是数据质量标记）。已新增回归用例 `test_track_d_trend_unverified_must_not_be_counted_as_dropped` |
| **D-30** | **股权质押口径错配：`t021`（占其持股）被当成质押率去比占总股本阈值** | `data/eltdx_collector.py:parse_pledge_response`、`screener/filter_audit.py` | ✅ **已完成** | 用户指出质押数据**实际可获取**（`CWServ.tdxf10_gg_zbyz` + `params=["gqzy", code, ""]`，返回 3 表）。查证后真缺陷**不是通道缺失而是口径错配**：旧实现优先取 `t021`（占其所持股份%）赋给 `pledge_ratio`，再与 `PLEDGE_FATAL_RATIO=0.70`（**占总股本**口径）比较。实测后果：格力 000651 旧 1.0000→新 0.1535（控股股东满仓质押但仅占总股本 15.35%，**白马被误杀**）、立讯 002475 0.3783→0.1418、宁德 300750 0.1475→0.0068（夸大 21 倍）。现两个口径分离存储，且「占其持股」否决需叠加绝对规模门槛（`PLEDGE_OWN_FATAL_MIN_TOTAL=0.20`）——大股东满仓质押但持股仅占总股本 5% 时，强平冲击有限，不足以一票否决 |
| **D-32** | **质押流水明细累加虚高 ⇒ 低置信度值触发误杀** | `data/eltdx_collector.py:parse_pledge_response`、`screener/filter_audit.py` | ✅ **已完成** | 用户质疑「是不是只针对科达利这一只改的」⇒ 做 **800 只随机采样**验证通用性，结果暴露第二层问题：① **「有累计无明细」组合实测 0 例**（table1/table2 总是同时有/无，`holder` 来源恒为 0，因为只要有 table1 就必有 table2）；② 「有明细无累计」高达 **159/800（20%）**，其中 43 只有真在押；③ 明细累加会因**部分解押留下多条记录**而虚高 —— `002269` 美邦服饰 91 条明细、22 笔在押累加出 **109.86%**（物理上不可能）。修复：明细来源截断到 100%（`pledge_detail_truncated` 标记），且 `pledge_source=="detail"` **不参与一票否决**（只警示）—— 精度不足以支撑不可逆决定；真正的高质押风险股都有汇总表（采样中 company 来源 317 只全覆盖，其中 4 只超阈值照常否决）。修复后 800 只**越界 0 只** |
| **D-33** | **质押流水明细里"已解押"记录未剔除 ⇒ 累加出 109.86%** | `data/eltdx_collector.py:parse_pledge_response` | ✅ **已完成** | 用户再次用 002269 截图指出"里面有个实际解押日你没用，已解押的不能算进去"。查证：明细表有 **3 个**解押相关字段，旧判据只看 `T011`（实际解押日）+`T012`（解押股数），而 002269 有 20 笔**老记录这两个字段都是空的**（起始日 2012~2018），只有 `T010`（解除日/截止日）填了 2017~2019 的过期日期 ⇒ 被误当在押，累加 `T007` 得 109.86%。修正为**三判据**：`T011`/`T012` 有值→已解押；`T010` 有值且早于今天→已到期；其余才算在押。修正后交叉验证：宁德明细回溯 **0.68% = 官方汇总 0.68%**、格力 **15.35%=15.35%**、立讯 **14.18%=14.18%**（三只完全吻合，证明判据正确）。剩余 16 笔三字段全空的老记录 ⇒ 加**两重自洽校验**（① 占总股本累加 >100%；② 同一股东"占其持股%"累加 >100%，后者更灵敏且不依赖任何日期假设）⇒ 判 `detail_inconsistent` 返回 `None`（不可核验），绝不截断成"质押 100%"这种荒谬值 |
| **D-34** | **结论确定性分层缺失：日内切片被固化成刚性指令、估值自称「合理价」** | `core/judgment_chain.py`、`presentation/plain_language.py` | ✅ **已完成（P0 批次）** | 第三方评审指出研报「把某一时间切片的微观交易信号以过高确定性固化为行动指令」。代码核查确认三条均指向真实缺口：① **时效性**——`MicrostructureProfile`/`MainForceDecision` 无 `as_of` 字段（四核心文件检索 0 命中），不确定性提示**仅在数据降级时出现**（`judgment_chain.py:630`），导致 96% 置信度的「无抵抗阴跌出清期」是裸断言；② **框架傲慢**——`divergence_note`（`derivation.py:391`）生成后从未渲染，三张假设表 import 后无调用点（死代码），支撑假设是裸魔数；③ **语义弱化**——`plain_language.py:148` 把「证伪线」替换成「退出底线」，丢掉可推翻性。本批次**零计算改动**（不断言改阈值/公式），只改表达：新增 `_build_valuation_assumption_note`（假设前提+口径差异+显式排除项）与 `_build_signal_freshness_banner`（时效声明恒非空），「合理价区间」→「条件锚点」，「证伪线」→「判断错了就退」。规格见 `docs/SPEC_CONCLUSION_CERTAINTY_LAYERING.md`，用例 15 项。**第二批次（L2 时效治理）亦已完成**：F-11 STAGE_6/7 反向解禁（含修复规则 2 fallback 把熔断**永久卡死**的缺陷：候选转 STAGE_4/5 时 `fallback=...else prior_stage` 会回落回 STAGE_6）、F-10 指令失效机制（`build()` 新增 `main_force_stage`，资金面触发的 AVOID/REDUCE 附"信号反转即作废"，财务红旗否决不受影响）、F-9 信号 TTL（跨 1~2 日待复核、≥3 日宣告失效，不引入交易日历以免新增失败模式），并将此前**只在单测中被断言、从未进入报告**的 `transition_note` 接入支柱④。用例累计 30 项 |
| **D-35** | **报告内部自相矛盾：文案与被描述的数值解耦** | `core/main_force_engine.py`、`core/judgment_chain.py` | ✅ **已完成（自洽层）** | 用科达利实跑暴露三处硬伤：① **价格关系模板硬编码**——`_get_stage_metadata` 的 STAGE_7 行为描述无条件写「现价显著跌破知情均线」，而 STAGE_7 判定中该条件只是 15 分加分项、非必要条件；科达利靠「套牢盘 64.1%」(+30分) 达标，现价 162.98 **高于**知情均线 148.52，报告却写「显著跌破」，与同段数字直接冲突。② **方向两套真值源**——反伪装模块按 `smart_buy_ratio > smart_sell_ratio` 判「中位加速接力」(59.8% vs 40.2%，买方占优)，决断卡却硬编码「主力处于对倒派发出货期」，两个相反结论同屏展示。③ **阶段语义错配**——STAGE_6/STAGE_7 被合并进同一 `elif` 分支，文案只写了 STAGE_6 的说法，导致科达利顶部标签是「无抵抗阴跌出清期」、决断卡却说「对倒派发」。另修 ④ **置信度倒挂**：49.5%(抛硬币) 与 96% 走同一分支、输出同一套「坚决一股不买」措辞，现按置信度 <70 降级为「暂缓介入·待确认」。修复方式**不是改用 AI**，而是让文案**从数值派生**并取**单一真值源**；仓位上限维持 0.0 不变（不动风控边界）。用例 6 项。**⚠️ 未解决（属判定层，非表达层）**：科达利当日 +7.44%、买盘占优、站上主力成本线，仍被判 STAGE_7——根因是 STAGE_7 评分基准 20 分 + 套牢盘 30 分即可胜出，未把当日价格动能与资金方向纳入。修复后报告会**如实自曝**该张力（「这与定性存在张力，须以次日数据复核确认」），但判定逻辑本身待改 |
| D-29 | F10 深度取数串行太慢 | `config.py:F10_DEEP_MAX_WORKERS` | ✅ **已完成** | F10 走 HTTP 7615 无状态，单线程 268~293ms/只。实测 150 只：并发 8 → 14.4s（96ms/只）；**并发 16 → 8.7s（58ms/只）**（采用）；只调利润表可再降到 6.2s。每线程独立 `F10Client` 避免共享 session |
| **D-31** | **只看 table1/table2 判「确认无质押」⇒ 把有质押的票当无质押放行** | `data/eltdx_collector.py:parse_pledge_response` | ✅ **已完成** | 用户对比宁德 300750 与科达利 002850 的界面后追问「不同股票格式好像不一样」。**列名其实完全固定**，差异在**填充程度**：格力/宁德三级表全有数据；**科达利 table1 `0 行`、table2 全 `None`，只有 table0 有 32 条明细（其中 7 条未解押、合计占总股本 2.03%）**；美的 table0 有 12 条但**全是已解押**记录。旧实现以「table1 空 且 table2 无值」判 0.0，科达利即被误判为"确认无质押"——**这是比误杀更糟的方向：排雷直接失效**。现改**三级回退** `table2.zzgb → table1.t016 → table0 未解押求和`，并用 `pledge_source`（company/holder/detail/none）标明来源；「未解押」判据为 `T011`（实际解押日）与 `T012`（解押股数）皆空。交叉校验：格力明细 4 条在押合计 15.15%，与 table2 的 15.35% 吻合 |

---

## E. 死配置与失效参数 — 本批全部完成 ✅

| ID | 内容 | 位置 | 状态 | 处置 |
|:---|:---|:---|:---:|:---|
| E-1 | `MAX_SINGLE_POSITION=0.20` 零引用；`judgment_chain.py:612` 硬编码 0.25；`execution_playbook.py:61` `max_pos=25` | `config.py`、`judgment_chain.py`、`execution_playbook.py` | ✅ 完成 | 引入**双档上限**：`MAX_SINGLE_POSITION=0.20` 常规 + `MAX_SINGLE_POSITION_EXTREME=0.25` 极端（需置信度 ≥ `POSITION_EXTREME_MIN_CONFIDENCE` 且主力建议仓位 ≥ `POSITION_EXTREME_MIN_STAGE_CAP`）。新增 `_resolve_position_cap()` 收敛全部裸数字；剧本仓位改由入参 `position_cap` 换算并封顶 |
| E-2 | `LEFT_TAIL_WARN_THRESHOLD=0.25` 零引用 | `config.py`、`judgment_chain.py` | ✅ 完成 | 在 `_resolve_position_cap` 接线：左尾深度 > 25% 时仓位腰斩至 10%。新增 `_left_tail_depth_pct()` 处理 `depth_to_sotp` 的**量纲换算**（配置小数 vs 字段百分比） |
| E-3 | `FORECAST_DROP_FATAL_RATIO=-0.50` 零引用 | `config.py`、`audit_engine.py` | ✅ 完成（规则） | `_check_forecast_anomaly` 接入量化判据并做去重（预告类型已判致命时不叠加）。⚠️ **数据源状态**：eltdx F10 无公司业绩预告通道，规则处于**待数据源**空转，已在源码与 config 显式标注 |
| E-4 | `build(matched_personas)` 参数声明后从未使用 | `core/execution_playbook.py` | ✅ 完成 | 按 `youzi_personas.SEATS.style` 识别「砸盘/一日游/散户拥挤」席位 → 挂单区间下移 + 禁止 9:25 抢筹 + 收紧退出线。关键词收敛至 `config.PLAYBOOK_DUMP_RISK_STYLE_KEYWORDS` |

---

## F. 文档漂移

| ID | 内容 | 位置 | 状态 | 处置 |
|:---|:---|:---|:---:|:---|
| F-1 | 测试数量过时（称 74 项，实际 124 项） | `README.md`、`docs/ARCHITECTURE.md` | ✅ 完成 | 改为 124 并注明构成（111 离线 + 11 seednet + 2 聚合） |
| F-5 | **测试数量再次漂移**（124 → 实测 **387**） | `README.md`、`docs/ARCHITECTURE.md`、`docs/ROADMAP_AND_AI_EVOLUTION.md`、`docs/FUTURE_OPTIMIZATION_SPECIFICATIONS.md` | ✅ 完成 | 统一为 **387 = 376 离线 + 11 seednet**。★ 教训：测试数量是**高频漂移字段**，四处文档三处不同数字（166 / 56 / 74），建议 CI 校验或改为不写死数字 |\n| F-8 | **测试数量第三次漂移**（387 → 实测 **447**） | 同上 4 处 | ✅ 完成 | 统一为 **447 = 436 离线 + 11 seednet**。新增 `tests/test_universe.py`、`tests/test_profile_batch.py` 与 `test_screener.py` 扩充共 60 项 |
| F-6 | 门控规则数漂移（7 条 / 12 条 → 实测 16 条） | `docs/ARCHITECTURE.md` §6.3、`ARCHITECTURE_AND_SRS.md` FR-05 | ✅ 完成 | 统一为 16 条（R1~R5、R7~R16、R18），并更正「R1~R6 无定义」的旧结论 |
| F-7 | 审计模型数（SRS 11 → 实测 12，多 DuPont）、判断链装配方法数（5 → 实测 6） | `ARCHITECTURE_AND_SRS.md` §8.1、`docs/ARCHITECTURE.md` §6.3 | ✅ 完成 | 统一为 12 个 `_check_*` 与 6 个装配方法 |
| F-2 | 目录索引缺漏 10+ 文件 | `README.md` | ✅ 完成 | 补齐 `core/industry.py`、`investor_panel.py`、`types.py`、`seat_matcher.py`、`trap_detector.py`、`game_features.py`、`data/eltdx_units.py`、`eltdx_financial.py`、`eltdx_financial_map.py` 与 `tests/` 新增文件 |
| F-3 | SRS 换手率与 config 冲突 | `ARCHITECTURE_AND_SRS.md` vs `config.py` | ✅ 完成 | config 对齐 SRS（8%~25%） |
| F-4 | `scripts/` 空目录无说明 | `scripts/` | ✅ 完成 | 经核查无任何文档要求填充；`data/eltdx_financial_map.py:50` 注释引用的 `scripts/tests/...` 为上游项目路径残留，非本仓库待办 |

---

## 1. 阻塞项（无法自行推进）

| 阻塞 | 影响条目 | 所需外部条件 |
|:---|:---|:---|
| ~~eltdx F10 无股权质押通道~~ | D-7 | ✅ 已接入通达信 F10 资本运作 `gqzy` 通道解决 |
| eltdx F10 无公司业绩预告通道 | E-3 生效 | 结构化预告数据源 |
| 实盘账本样本不足 | A-4 | 历史行情与 `screener_tracker.jsonl` 积累 |
| 无真实历史造假财报 | C-3 完整验收 | 康美药业等历史三表数据 |

## 2. 待确认问题

| # | 问题 | 影响 | 状态 |
|:---:|:---|:---|:---|
| ~~1~~ | ~~Lint 门控是「抛异常」（SRS §8.2）还是「降级清零」（ARCHITECTURE §5）？~~ | C-6 | ✅ **已裁决**：以代码为准，「以纠代抛」降级清零；SRS §8.2 已反向修订（见 C-6 行） |
| 2 | `screen` 定位是纯短线题材接力（接受排除大盘股）还是需按市值分档阈值？ | C-7 延伸、D-5 | ⬜ 待裁决 |
| 3 | 是否引入真实历史造假样本数据？ | C-3 | ⬜ 待裁决 |

## 3. 建议排期

| 批次 | 内容 | 状态 |
|:---|:---|:---|
| **第一批（验收补齐）** | E-1~E-4、C-1、C-3、C-7、F-1~F-4 | ✅ **已完成** |
| 第二批（遗留 P1） | D-1~D-5、C-5 系统性清理 0 兜底 | 🟨 C-5 第一批已完成（23 处）；D-1~D-5 ⬜ 待排期 |
| **沪深全市场改造第一批** | D-11~D-18：真全市场母池 + 覆盖率闸门 + 归因矩阵 + 轨道 A 解首板死锁 | ✅ **已完成**（20261028 实跑验收：5225/5225 覆盖率 100%，Top5 由 5 只 0% 变为 4 只 buyable/20%） |
| **沪深全市场改造第二批** | 轨道 B：弱转强 / 首阴反包池（`ladder_analyzer` 的 `broken_rows` 已识别但因只取 `limit_up_rows` 被弃，约 70 只/日；需近 3 日 K 线比对「曾涨停今日收阴」） | ✅ **已完成**（D-19/D-20） |
| **沪深全市场改造第三批** | 轨道 C 产业中军 + 轨道 D 困境反转 | ✅ **已完成**（D-21~D-24） |
| 第三批（确定性增强） | A-2 + B-1/B-2/B-3，A-4 + B-5，A-3 + B-4 | ⬜ 待排期（**注意：轨道 C 的「行业 RS」与 A-2/B-1 重叠，需合并推进**） |
| 第四批（外部依赖） | D-6、C-2、C-4 (D-7已完成) | ⬜ 进行中 |
| **本轮（借鉴上游补齐四层）** | 数据层 + 契约层 + 门控层 + 证据层 + 判断层基础设施 | ✅ **已完成**（A-1 接线 **5/5**，与 `:74` 口径一致；其余 A-2/A-3/A-4 按第三批排期） |

---

## 4. 核对方法

本清单的每一项均以代码实证为准，复核方式：

```powershell
# 离线全量（376 项）
python -m pytest -m "not seednet" -q

# 全量含联网种子跑批（387 项）
python -m pytest -q
```

新增能力均有专属回归入口：
* P0 修复 → `tests/test_p0_fixes.py`（39 项）
* 第一批验收补齐 → `tests/test_batch1_backfill.py`
* 真实数据种子 → `tests/test_seed_universe.py`（`seednet` 标记）
