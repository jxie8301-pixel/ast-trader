# A股短线量化投研系统（AST-Trader）
# 需求规格说明书与系统架构设计文档（Baseline v1.0 冻结版）

---

## 1. 目标与范围 (Goals & Scope)

### 1.1 项目目标
针对 A 股短线及波段交易场景，构建一套兼具“买方穿透式审计防守”与“游资博弈题材进攻”的本地化短线投研与选股系统。
解决传统短线策略“重 K 线轻排雷导致频踩黑天鹅”、“蹭概念假题材被套无法自拔”、“买入前无死锁退出线”、“网络爬虫频繁反爬被封”四大致命痛点。

### 1.2 系统范围 (Scope Boundaries)
* **包含范围 (In-Scope)**:
  1. **个股深度穿透分析 (Single-Stock Analysis)**: 涵盖 11 会计审计扫雷、短线题材去伪、一线游资席位匹配、杀猪盘 8 维雷达、五节点闭环判断链（质地/状态/赔率/路径/决策）、质量门控与决断卡生成。
  2. **全市场短线漏斗筛选 (Market Screener)**: 盘中（11:30）与盘后（15:05）在 15 秒内完成全市场 5300+ 标的三层漏斗收敛（流动性初筛 -> 审计排雷一票否决 -> 主线题材合力排序），输出 Top 5~10 观察池与交易剧本。
  3. **数据底层**: 基于 `eltdx` 协议引擎，提供毫秒级行情、分笔、财务快照与板块数据。
* **排除范围 (Out-of-Scope)**:
  1. 证券经纪商柜台自动下单（非自动化交易执行端）。
  2. 可转债、期权、股指期货等衍生品。
  3. 3~5 年期 DCF 现金流贴现、LBO 杠杆收购等脱离 A 股短线实际的投行模型。

---

## 2. 功能需求清单 (Functional Requirements Matrix)

| 需求 ID | 功能名称 | 详细规则与技术要求 | 优先级 | 交付模块 |
|:---|:---|:---|:---:|:---|
| **FR-01** | eltdx 数据统一适配 | 实现通达信网络 TCP 协议连接池管理；秒级提取日 K 线、实时分时五档、分笔大单流向（`main_net_wan`）、分批财务数据与板块归属。数据单位严格对齐（金额除以 1000 换算为千元/万元），缺失值严格置 `None`。 | P0 | `data/` |
| **FR-02** | 11 会计审计排雷引擎 | 严格实现 11 经典审计模型：Beneish M-Score（财务操纵 $M>-1.78$ 拦截）、Piotroski F-Score（健康度评分 0-9）、Altman Z-Score（破产预警）、Sloan（高应计异象）、Buffett（现金流背离）、主营业务侵蚀、大股东高比例质押（$>70\%$ 拦截）、股东户数变动、业绩预告变脸、长期股权投资敞口、历史高估值透支。 | P0 | `core/audit_engine.py` |
| **FR-03** | 短线博弈与题材画像 | 建立一线游资席位库（`seat_db`）与资金容量射程匹配；近 30 天龙虎榜真实席位反查与属性标注（善庄/量化/游资）；概念纯度计算；8 维短线杀猪盘舆情特征匹配。 | P0 | `core/seat_matcher.py`<br>`core/trap_detector.py` |
| **FR-04** | 五节点闭环判断链 | 按因果链条依次生成：①质地（真实成色与造假概率） -> ②状态（催化剂实锤与临界点） -> ③赔率（业绩底与情绪溢价） -> ④路径（左尾量化到具体价格与席位属性） -> ⑤决策（档位/仓位上限/唯一退出线）。 | P0 | `core/judgment_chain.py` |
| **FR-05** | 质量门控与机检（Lint） | **16 条**机器硬规则（R1~R5、R7~R16、R18；R6/R17 按形态取舍刻意不移植）：命中 🔴 致命红旗强制封顶为“回避”且阻断推荐；仓位建议仅允许在第 ⑤ 节点出现；数值换算执行算术闭合机检（半 ULP 动态容差）。硬编码 fail 级 7 条（R7~R13），其余默认 warn，由 `config.LINT_RULE_SEVERITY` 控制。 | P0 | `lint/validator.py` |
| **FR-06** | 全市场三层漏斗筛选 | Tier 1 流动性初筛（成交额 $\ge 5$ 亿、涨幅 $4.5\% \sim 10\%$、换手率 $8\% \sim 25\%$）；Tier 2 审计扫雷一票否决；Tier 3 题材板块共振与大单合力打分排序，输出 Top 5~10。 | P0 | `screener/` |
| **FR-07** | 双模表现层输出 | CLI 终端 Rich 彩色卡片输出；自包含单文件响应式 HTML 报告导出（支持暗色模式、ECharts 与红标反查）。 | P1 | `presentation/` |

---

## 3. 非功能需求 (Non-Functional Requirements)

* **NFR-01 性能要求 (Performance)**:
  * 全市场 5300+ 标的三层漏斗总耗时 $\le 15.0$ 秒。
  * 单股全套深度体检与研报装配总耗时 $\le 2.0$ 秒。
  * 进程常驻内存 $\le 500\text{MB}$。
* **NFR-02 安全与风控 (Safety)**:
  * 一票否决机制：命中任何致命红旗（质押率 $>70\%$、立案调查、Beneish 判定造假），系统绝对禁止输出“买入”建议。
  * 真实性原则：缺失字段严格置 `None`，严禁填充默认值 `0`，缺失特征的规则自动弃权，不伪装成有效信号。
* **NFR-03 可维护性与可测试性 (Maintainability)**:
  * 核心排雷算法与博弈特征计算模块实现 100% 单元测试覆盖。
  * 数据层与业务中台严格解耦，`eltdx` 接口变动不影响上层审计与判断链。
* **NFR-04 跨平台兼容性 (Compatibility)**:
  * 支持 Windows、macOS 与 Linux，Python 运行环境固定为 Python 3.11+。

---

## 4. 关键约束与假设 (Constraints & Assumptions)

1. **交易制度约束**：假设执行 A 股现行现货交易规则（T+1 交易制度、主板 10% 涨跌幅限制、双创板 20% 涨跌幅限制）。
2. **数据源约束**：系统数据底座依赖通达信网络主站或本地协议通道，不使用商业付费 Token；龙虎榜与外部杀猪盘舆情作为次要增强源，若抓取超时自动降级为“未检测到席位/舆情”，主流程不阻断。
3. **模型假设**：假定通过公开财务报表附注、分笔大单流向与龙虎榜能够识别主力资金的合力与真实风险敞口。

---

## 5. 架构分层与模块划分

```
ast-trader/
├── config.py                 # 全局参数 (质押红线、流动性阈值、eltdx 节点池)
├── cli.py                    # 统一终端入口: analyze (个股) / screen (选股)
│
├── data/                     # 统一数据底层 (收敛至 eltdx)
│   ├── tdx_hosts.py          # 7709 主站四级优先级解析 (参数 > AST_TDX_HOSTS > json > 内置池)
│   ├── eltdx_client.py       # TCP 协议底层通信与连接池就绪门、代码归一化
│   ├── eltdx_collector.py    # 行情、K线、分笔分时、分批财务快照标准化
│   ├── eltdx_financial*.py   # 财务科目映射与单位换算
│   ├── supplement_api.py     # 龙虎榜席位与外部舆情轻量接口
│   ├── pdf_reader.py         # 定期报告/临时公告 PDF 抓取与页码级引文
│   ├── announcement_corpus.py# 公告语料库
│   ├── data_health.py        # 通道健康度审计
│   └── degraded.py           # 缺失值缺省标记统一声明
│
├── core/                     # 核心分析与计算中台
│   ├── audit_engine.py       # 12 个会计审计扫雷模型 (Beneish, Piotroski, Altman, DuPont 等)
│   ├── red_flags.py          # 红旗聚合、归家、Top3 提炼与红标映射
│   ├── types.py              # 核心类型定义
│   ├── industry.py           # 行业准入识别器 (当前仅区分「金融 / 未分类」，见 F-2)
│   ├── derivation.py         # 估值双锚 [SOTP, DCF] 与反向 DCF
│   ├── derived_metrics.py    # 「赚不赚钱」看板
│   ├── main_force_engine.py  # 主力 7 阶段状态机 (含 STAGE_UNVERIFIED 与磁盘迟滞)
│   ├── microstructure.py     # L2 高频微观结构与 Q 因子
│   ├── macro_regime.py       # 大盘情绪闸门
│   ├── seat_matcher.py       # 游资席位数据库 (seat_db) 与资金容量射程匹配
│   ├── youzi_personas.py     # 24 大一线游资战法画像
│   ├── trap_detector.py      # 杀猪盘 8 维舆情特征探测器
│   ├── game_features.py      # 短线博弈量价计算器 (量比、换手率、题材共振)
│   ├── capital_matrix.py     # 资金矩阵雷达
│   ├── investor_panel.py     # 投资者结构面板
│   ├── execution_playbook.py # T+1 作战剧本 (持币/持股双轨战术)
│   ├── judgment_chain.py     # 五节点判断链 (6 个独立装配方法)
│   ├── ai_enrichment.py      # AI 增强结果的数据契约
│   ├── ai_coprocessor/       # AI 语义协处理器 (单向阀；默认关闭，见 §4)
│   ├── schemas/              # JSON-Schema 契约 (decision_card / ai_enrichment / common)
│   └── schema_validator.py   # Draft202012Validator 跨文件校验
│
├── screener/                 # 全市场漏斗筛选模块
│   ├── pipeline.py           # 三层漏斗执行控制器
│   ├── filter_liquidity.py   # Tier 1: 5亿成交额、换手率、涨幅初筛
│   ├── filter_audit.py       # Tier 2: 审计红旗硬核一票否决
│   └── rank_composite.py     # Tier 3: 主线题材共振与大单合力打分排序
│
├── lint/                     # 质量门控与算术闭合机检
│   └── validator.py          # 致命红旗强制封顶回避、推导算术闭合、唯一出处自检
│
└── presentation/             # 输出呈现层
    ├── terminal_view.py      # 终端富文本表格美化 (Rich 库驱动)
    ├── plain_language.py     # 纯展示层白话翻译 (只读，绝不回写决断卡)
    └── html_renderer.py      # 自包含单文件响应式 HTML 研报渲染器
```

> **尚未实施的能力线（架构图留白，勿误认为已落地）** —— 详见 `docs/UNIMPLEMENTED_WORKLIST.md`：
> * **行业/板块相对强弱**：`core/sector_rs.py`（A-2）与 `data/eltdx_collector.get_sector_bars()`（B-1）均未实施，`core/industry.py` 目前**仅是金融业准入识别器**，不含全行业分位建模；
> * **龙虎榜协同**：`core/lhb_synergy.py`（A-3）未实施，现存 `seat_matcher.py` 仅有静态中文映射，无席位属性标签；
> * **实盘回测**：`screener/backtester.py`（A-4）与 `python cli.py backtest`（B-5）未实施，现有 `screener/tracker.py` 仅 T+1 单日复盘；
> * **板块 RS 加权**：Tier 3 板块加权（B-2）与 `_decide_gear` 仓位乘数（B-3）依赖 A-2，一并待排期。
>
> **数据源限制（排雷规则已就绪但通道不可得，严禁视为已生效）**：
> * 控股股东质押率 —— eltdx F10 **无股权质押通道**（已全量探测 governance / stock_info / valuation / company_info 均无该字段），`pledge_ratio` 恒为 `None`，`PLEDGE_FATAL_RATIO` 判据在真实跑批中恒定不触发，走「未核验降权」通道；
> * 公司业绩预告 —— eltdx F10 无业绩预告通道，`gov["forecast"]` 无生产者，`FORECAST_DROP_FATAL_RATIO` 判据同样空转。

---

## 6. 核心数据模型与接口契约

### 6.1 核心数据结构定义
* **RedFlagItem**: `id`, `framework`, `level` (🔴/🟠/🟡/🟢), `title`, `value`, `threshold`, `evidence`, `node`
* **SingleStockContext**: `ticker`, `name`, `trade_date`, `quote`, `financials`, `concept_blocks`, `audit_flags`, `youzi_matched`, `trap_score`
* **DecisionCard**: `ticker`, `name`, `trade_date`, `quality_verdict`, `state_verdict`, `odds_verdict`, `path_verdict`, `decision_gear` (买入/观察/回避), `position_cap`, `invalidation_line`, `top3_risks`
* **ScreenerCandidate**: `ticker`, `name`, `theme`, `tier`, `rank_score`, `main_net_flow`, `turnover`, `trigger_plan`, `stop_loss_line`

---

## 7. 错误处理与日志策略

1. **协议重连**: `eltdx_client` 遇网络闪断执行指数退避重试（3 次，0.5s、1.0s、2.0s）。
2. **优雅降级**: 补充数据（龙虎榜、杀猪盘搜索）失败时只记录 Warning，填充默认空特征，主流程照常运转；财务指标单项缺失置 `None`，对应规则自动弃权。
3. **日志输出**: 采用标准日志系统，统一落盘至 `logs/ast_trader.log`。

---

## 8. 测试与验收标准

1. **算法单元测试**: Beneish、Piotroski、Altman 等 **12 个**审计模型针对已知财务造假样本（如康美药业历史财报）100% 触发 🔴 致命红旗。
2. **门控机检测试**: 针对构造的“命中致命红旗但决策判定为买入”的反向测试用例，`validator.py` 必须 100% 拦截并**以纠代抛**——将决断档位降级为 `等证据临界(观察)`（存在 🔴 时降级为 `回避`）、`position_cap` 清零，并把降级结果同步回 ⑤决策节点。
   > ★ **C-6 裁决（已闭环，见 `docs/UNIMPLEMENTED_WORKLIST.md`）**：本节原文要求“抛出异常”，与 `docs/ARCHITECTURE.md` §5 的“以纠代抛降级清零”冲突。**以代码实现为准**：生产环境一律“以纠代抛”，`LintError` 保留为兼容语义但从不 raise。理由：抛异常会让 `screen` 全市场跑批因单票异常整体中断，与无人值守稳健性要求相悖。
3. **全市场性能验收**: `screen` 命令在 15 秒内完成全市场扫描并输出格式化表格。
4. **单股端到端验收**: `analyze` 命令在 2 秒内完成指定股票的全套分析并打印决断卡。

---

## 9. 交付里程碑

* **M1（数据底座与审计引擎）**: 完成 `data/` 与 `core/audit_engine.py`，单测通过率 100%。
* **M2（个股穿透与判断链）**: 完成 `core/judgment_chain.py`、`lint/validator.py` 与单股终端卡输出。
* **M3（全市场漏斗与双模呈现）**: 完成 `screener/` 与 `presentation/`，完成全链路验证。
