---
name: 对比分析 stock-scanner 与 ast-trader
overview: 基于已抓取的 GitHub 项目 DR-lin-eng/stock-scanner 源码（2.0 win app/stock_analyzer.py、全部股票分析推荐1.py、3.1 webapp）与本地 ast-trader 代码库的调研结果，输出一份结构化的中文对比分析报告：先拆解 stock-scanner 的个股分析方法（逻辑/数据/指标/决策），再与 ast-trader 逐项对比（目标、流程、技术、数据），最后给出双方优缺点总结。
todos:
  - id: collect-stock-scanner
    content: 抓取并固定 stock-scanner 取证材料：仓库首页、2.0 win app/stock_analyzer.py、全部股票分析推荐1.py、3.1 webapp 目录
    status: completed
  - id: collect-ast-trader
    content: 用 [subagent:code-explorer] 梳理 ast-trader 分析方法：定位、双链路、数据通道、指标模型、决策规则、未实施项
    status: completed
  - id: cross-verify
    content: 交叉核验双方文档与代码的口径漂移，确定「以代码为准」的对比基准
    status: completed
    dependencies:
      - collect-stock-scanner
      - collect-ast-trader
  - id: write-report
    content: 按七章结构撰写结构化中文对比报告，含总览表与四维对照表
    status: completed
    dependencies:
      - cross-verify
  - id: persist-doc
    content: 经确认后落盘为 docs/COMPARISON_stock-scanner.md并建立 docs 索引引用
    status: completed
    dependencies:
      - write-report
---

## 用户原始需求

分析 GitHub 项目 https://github.com/DR-lin-eng/stock-scanner.git 对个股的分析方法，包括**分析逻辑、数据来源、指标选取、决策规则**；再与当前项目（ast-trader）**逐项对比**，明确两者在**分析目标、处理流程、技术实现、数据获取**四个维度上的异同；最后**总结双方各自的优点与不足**。要求**结构化输出、保持中文**。

## 需求补全与约束澄清

- **交付形态**：一份结构化中文对比分析报告（Markdown 表格为主），直接在对话中输出；经确认后可选落盘为 `docs/COMPARISON_stock-scanner.md`。
- **对比基准**：必须**以代码为准、而非 README 自述**——双方项目均存在文档与实现漂移，报告中需显式标注此类差异。
- **边界**：仅做只读调研与文档产出，**不修改任何现有代码**。
- **证据要求**：每一项对比结论需可追溯到具体文件与行号（外部项目：文件 + 函数名；本地项目：`文件:行号`）。

## 报告章节结构（计划产出）

1. **结论速览**：一句话定位差异 + 总览对照表
2. **stock-scanner 个股分析方法拆解**

- 分析逻辑：单股 `EnhancedStockAnalyzer.analyze_stock()` 8 步流水线 / 全市场 `TopStockScanner` 6 步流水线
- 数据来源：akshare 单一依赖与 8 类接口清单、进程内 dict 缓存
- 指标选取：技术面（单股版 5 类 / 全市场版含 ATR、OBV、Stochastic、ROC）、基本面 25 项五分类
- 决策规则：权重 0.4/0.4/0.2、基准 50 分加减分表、两套建议映射阈值
- 实现级局限：25 项指标静默置 0 后被过滤、行业新闻函数恒空、情绪词典子串匹配、无风控/无回测

3. **四维逐项对比**：分析目标 / 处理流程 / 技术实现 / 数据获取（各附对照表）
4. **ast-trader 的优点**
5. **stock-scanner 的优点**
6. **双方不足**（含 ast-trader 自查清单中的诚实短板）
7. **互补与迁移建议**（可选）

## 调研方法论（非代码实现的执行框架）

本任务为**只读对比分析**，不涉及代码改动。技术部分定义取证路径与对比口径，确保结论**可核验、可复现、无臆造**。

### 1. 取证来源

| 侧 | 来源 | 已取得内容 |
| --- | --- | --- |
| 外部 | `https://github.com/DR-lin-eng/stock-scanner`（main，91 commits，MIT） | 仓库首页 README、目录结构（1.0 / 2.0 win app / 2.5 / 2.6 / 3.0 / 3.1 webapp） |
| 外部 | `2.0 win app/stock_analyzer.py`（raw） | `EnhancedStockAnalyzer` 完整源码：配置加载、缓存、行情、25 项财务、新闻、词典法情绪、技术指标、三套打分、建议映射、AI prompt 与降级 |
| 外部 | `全部股票分析推荐1.py`（raw） | `StockAnalyzer` + `TopStockScanner`：`TechnicalParams`、EMA/RSI/MACD/BOLL/ATR/OBV/Stochastic/ROC/量比、20 线程分批并发、3 次重试退避、≥85 分过滤、按价格区间分文件落盘 |
| 外部 | `3.1 webapp/`（目录页 + README） | 确认多市场（A/港/美）、AI 流式、自定义提示词等新特性取向 |
| 本地 | `d:/workspace/ast-trader` | 由 `code-explorer` 子代理完成全量梳理，含行号级引用（见下） |


### 2. 对比口径（四维矩阵）

| 维度 | 对比要点 |
| --- | --- |
| **分析目标** | 输出物形态（研报文章 vs 决断卡）、时间尺度（中长线基本面 vs 短线博弈）、是否有仓位/止损/合规 |
| **处理流程** | 单股链路步数、全市场漏斗层级、是否有门控/守恒审计/降级链 |
| **技术实现** | 依赖库、并发模型与 workers、参数可配置性、测试覆盖、错误处理范式（兜底 vs Fail-Closed） |
| **数据获取** | 底层协议、通道数量、微观/盘口/席位深度、缓存持久化、健康度追踪 |


### 3. 已核实的本地项目关键事实（供撰写时引用）

**定位与红线**（`README.md:1-4`）：确定性本地量化投研系统，五条红线——毫秒级取数 / 100% 数学闭环 / 零 Token 成本 / 零大模型幻觉 / 严禁静默阻断。

**依赖与数据源**（`requirements.txt:1-13`）：`eltdx>=3.0.0` 通达信原生（Python + Rust 扩展），TCP 连接池；主站四级优先级 `data/tdx_hosts.py`；**全库无 akshare**。

**单股链路**（`core/analyzer.py:91-207`，16 步）：代码归一（含北交所 920xxx 歧义）→ 日K 60 根 + 实时快照（任一空则 `return None` 硬阻断）→ `GameFeatureExtractor` → F10 治理与概念 + 三表 + 行业估值中位数现场自算 → [可选 AI] → `AuditEngine`（12 个 `_check_*`）→ `LadderAnalyzer`（连板天梯）→ 资金流 + 微观结构 + `MainForceStateEngine`（7 阶段）→ 龙虎榜 `SeatMatcher` → `TrapDetector`（杀猪盘 8 维）→ 游资画像 → `JudgmentChainRunner`（五维中枢，入参 18 字段，含 `data_health`）→ `LintValidator`（16 条）→ JSON Schema 校验 → `PlaybookBuilder` → 终端/HTML 渲染。

**全市场链路**（`screener/pipeline.py:95`）：L0 `universe.build_universe()`（覆盖率 <0.98 → `blocked`，`picks` 恒空）→ L1 `profile_batch` + 剔次新(<60 交易日) → 天梯增强 → T1 `filter_liquidity` → T2 `filter_audit`（队列上限 120，workers=5）→ T3 `rank_composite`（workers=5）→ 四轨 A/B/C/D → 账本落盘 → 归因守恒审计（`input == Σ dropped + output` + 死规则检测）。

**核心模型与阈值**：Piotroski F-Score 9 项（≤3 警示 / ≥7 优秀）；Beneish M-Score 8 变量（`M > -1.78` → FATAL）；Altman Z（`Z<1.81` FATAL，`1.81~2.99` HIGH）；Sloan 应计 `|应计/TA| > 0.15`；商誉/净资产 >50% FATAL；质押占总股本 >70% FATAL、占其持股 >95% FATAL / >80% HIGH；反向 DCF 与 $P=F+N$（泡沫倍数 $N/P>70\%$）+ 10 项算术闭环自检（容差 ≤ 半个 ULP）；主力 7 阶段状态机（含迟滞、多日持久化 `persistence_window=2`、反伪装 7 项审计）；L2 聪明钱 Q 因子（$s=ret/\sqrt{vol}$，取累计量前 20% 为高效分钟，$q=VWAP_{smart}/VWAP_{all}$，阈值 0.985 / 1.015 与买卖占比 52%）；宏观闸门（跌停 ≥15 家或退潮期收紧）；仓位上限 0.20 / 极端档 0.25（需置信度 ≥90）/ 左尾 >25% 腰斩至 10%。

**关键技术约束**：`bars.get` 实测 **26ms/只** 是全市场漏斗的硬约束（5225 只 ≈130s），直接决定了「先用免费字段压缩候选 → 再懒加载日K」的两段式设计。

### 4. 撰写纪律（防止失真）

- 外部项目的**数值判据一律取自源码**，不采信 README 宣传语（如「25 项指标」「支持港美股」）。
- 本地项目**凡文档与代码冲突者，以代码为准**，并在报告中标注漂移（已知 3 处：README 六档命名 vs `pillar5_decision.py` 实际分支命名；README「11 项 seednet」vs ARCHITECTURE「21 项」；README「$Q>0.8$」vs `microstructure.py` 中 $q$ 为 VWAP 比值围绕 1.0 波动）。
- 优缺点总结需**双向诚实**：ast-trader 的不足引用其自查清单（`docs/UNIMPLEMENTED_WORKLIST.md`，63 项 / 已完 43 / 未实施 20 / 阻塞 10），stock-scanner 的优点亦如实给出（上手门槛低、指标覆盖面广、多端交互、可配权重）。

## Agent Extensions

### SubAgent

- **code-explorer**
- 用途：在撰写阶段复核 ast-trader 侧的指标阈值、决策分支与未实施项清单，确保引用行号与数值准确；必要时补全 `docs/PILLARS_AND_METHODOLOGY.md`、`docs/ARCHITECTURE.md` 中尚未确认的口径。
- 预期产出：返回带 `文件:行号` 引用的事实清单，可直接嵌入对比表；不修改任何文件。