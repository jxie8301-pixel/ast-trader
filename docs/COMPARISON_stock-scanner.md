# 对比分析报告：`DR-lin-eng/stock-scanner` vs `ast-trader`

> 取证基准：**以源码为准，不采信 README 自述**。双方均存在文档与实现漂移，文中已逐处标注。
> 外部项目版本：`main` 分支（91 commits，MIT，1.2k stars / 440 forks），取证时间 2026-10-29。
> 本地项目版本：`d:/workspace/ast-trader`，`requirements.txt` 锁定 `eltdx>=3.0.0`。

---

## 一、结论速览

**一句话差异**：`stock-scanner` 是「**多源数据抓取 + 指标罗列 + LLM 生成研报文章**」的通用工具；`ast-trader` 是「**会计审计排雷防守 + 游资盘口博弈进攻 + 闭环决断纪律**」的确定性投研系统。前者追求**覆盖面与交互体验**，后者追求**可审计性与执行闭环**。

| 维度 | `stock-scanner` | `ast-trader` | 判定 |
|:---|:---|:---|:---:|
| 输出物 | LLM 生成的 6 维度长文研报 | 结构化「买方决断卡」+ 双轨战术 + 仓位上限 | 结构性差异 |
| 时间尺度 | 隐含中长线（365 日线 + 财报） | 短线博弈为主 + 基本面排雷兜底 | 互补 |
| 决策可复现 | 弱（LLM `temperature=0.7`） | 强（纯确定性，AI 默认关闭且只能降级） | ast-trader |
| 数据深度 | HTTP 公开接口，无 L2/盘口/席位 | 通达信原生 + L2 十档 + 龙虎榜席位 + 公告 PDF | ast-trader |
| 上手门槛 | 低（pip 装 akshare 即用） | 高（依赖 eltdx 通达信数据环境） | stock-scanner |
| 指标体系广度 | 广（25 项财务 + OBV/ATR/KDJ/ROC） | 深（12 项审计模型 + 反向 DCF + Q 因子） | 各有胜场 |
| 风控与合规 | **缺失**（无止损/仓位/监管） | 完整（六档档位 + 左尾腰斩 + 异动余量） | ast-trader |
| 数据纪律 | 静默兜底（缺项置 0 后过滤） | Fail-Closed（缺失置 `None` + 强制声明） | ast-trader |
| 工程完备度 | 弱（无测试、无 CI、多版本目录并存） | 强（558 测试 + 16 条 Lint + Schema 契约） | ast-trader |

---

## 二、`stock-scanner` 个股分析方法拆解

### 2.1 分析逻辑：两条独立流水线

仓库内含 6 个版本目录（`1.0`、`2.0 win app`、`2.5 webapp`、`2.6 webapp`、`3.0 webapp`、`3.1 webapp`），核心实现有两套，**互不复用**（单股分析与全市场扫描是各自独立的代码路径）。

#### A. 单股增强分析 — `EnhancedStockAnalyzer.analyze_stock()`（`2.0 win app/stock_analyzer.py`）

```text
① get_stock_name()                     → ak.stock_individual_info_em（股票简称）
        ↓
② get_stock_data()                     → ak.stock_zh_a_hist(period="daily", adjust="qfq")
   └ 兼容 10/11/12/13 列四套列名格式（智能映射 + 位置兜底）
   └ close ≤ 0 或 NaN → raise ValueError（唯一硬校验）
        ↓
③ get_price_info()                     → 现价 / 涨跌幅 / 量比 / 20日收益波动率
        ↓
④ calculate_technical_indicators()     → MA / RSI / MACD / BOLL / 量能状态
        ↓
⑤ get_comprehensive_fundamental_data() → 8 大类基本面（见 2.2）
        ↓
⑥ get_comprehensive_news_data(days=30) → 新闻 50 / 公告 30 / 研报 20 / 行业 0
        ↓
⑦ calculate_advanced_sentiment_analysis() → 词典法情绪打分
        ↓
⑧ 加权综合 → generate_recommendation() → generate_ai_analysis()
   └ AI 失败则降级 _advanced_rule_based_analysis()
```

#### B. 全市场扫描 — `TopStockScanner`（`全部股票分析推荐1.py`）

```text
① get_all_stocks()      → ak.stock_info_sh_name_code("主板A股") ∪ ak.stock_info_sz_name_code("A股列表")
        ↓
② 分批 batch_size=20，ThreadPoolExecutor(max_workers=20)
   └ 批间 sleep(random.uniform(3,5)) 限速；单股失败重试 3 次，退避 sleep(random.uniform(2,5))
   └ ValueError（如不足 60 根 K 线）直接跳过
        ↓
③ calculate_indicators() → EMA 系 MA(5/20/60) / RSI / MACD / BOLL / ATR / OBV+MA10 / %K %D / ROC / 量比
        ↓
④ calculate_score()      → 满分约 110 的加减分制
        ↓
⑤ 硬过滤 score ≥ min_score(85)
        ↓
⑥ 按 10 元价格区间分组落盘 scanner/price_XX_YY.txt + summary.txt
```

> ⚠️ **重要发现**：全市场扫描**完全不含基本面与情绪分析**，是纯技术面流水线。这与 README 宣称的「25 项财务指标 + 综合新闻情绪」形成落差分野 —— 那套只在单股分析路径里。

### 2.2 数据来源：akshare 单一依赖

`get_stock_data()` 与其余方法内部均为 `import akshare as ak`（函数级延迟导入），全项目**无第二个数据源**。

| 用途 | akshare 接口 | 上游站点 |
|:---|:---|:---|
| 基本信息 / 股票简称 | `stock_individual_info_em` | 东方财富 |
| 日线行情（前复权） | `stock_zh_a_hist` | 东方财富 |
| 财务摘要（按报告期） | `stock_financial_abstract_ths` | 同花顺 |
| 财务分析指标 | `stock_financial_analysis_indicator` | — |
| 现金流量表 | `stock_cash_flow_sheet_by_report_em` | 东方财富 |
| 估值指标（PE/PB/PS） | `stock_a_indicator_lg` | 乐咕乐股 |
| 业绩报表 | `stock_yjbb_em` | 东方财富 |
| 分红配股 | `stock_fhpg_em` | 东方财富 |
| 行业板块名称 / 排名 | `stock_board_industry_name_em` / `stock_rank_em` | 东方财富 |
| 股东户数 | `stock_zh_a_gdhs` | 东方财富 |
| 机构持股明细 | `stock_institutional_holding_detail` | 东方财富 |
| 全市场代码表 | `stock_info_sh_name_code` / `stock_info_sz_name_code` | 上交所 / 深交所 |
| 公司新闻 | `stock_news_em` | 东方财富 |
| 公司公告 | `stock_zh_a_alerts_cls` | 财联社 |
| 研究报告 | `stock_research_report_em` | 东方财富 |

**缓存策略**：三个进程内 `dict`（`price_cache` / `fundamental_cache` / `news_cache`），TTL 分别 1h / 6h / 2h（可在 `config.json` 的 `cache` 段配置）。
→ **无持久化、无跨进程共享、进程退出即失效**。

**异常处理范式**：`try/except` + `logger.warning` 后写入空容器 `{}/[]` 或默认值兜底。没有健康度追踪、没有缺口声明、没有向上穿透机制。

### 2.3 指标选取

#### 技术面（单股版，`calculate_technical_indicators`）

| 指标 | 参数 | 离散化输出 |
|:---|:---|:---|
| 均线 MA | 5 / 10 / 20 / 60 | 多头排列 / 空头排列 / 震荡整理 |
| RSI | 14（SMA 平滑） | 数值 0~100 |
| MACD | 12 / 26 / 9 | 金叉向上 / 死叉向下 / 横盘整理 |
| 布林带 | 20, 2σ | 位置 `bb_position ∈ [0,1]` |
| 成交量 | 20 日均量 | 放量上涨 / 放量下跌 / 缩量调整 / 温和放量（阈值 1.5× / 0.5×） |

> 注：MA 用 `rolling().mean()`（SMA）而非 EMA，与全市场版（EMA）不一致。

#### 技术面（全市场版，`calculate_indicators`，指标更丰富）

EMA 系 `MA5/MA20/MA60`、RSI(14, EWM)、MACD(12/26/9)、BOLL(20,2)、**ATR(14)**、**OBV + OBV_MA10**、**Stochastic %K/%D (14,3)**、**Volume_MA20 + Volume_Ratio**、**ROC(10)**。参数集中在 `TechnicalParams` dataclass 中。

#### 基本面「25 项」（`_calculate_core_financial_indicators`）

| 类别 | 指标 |
|:---|:---|
| 盈利能力（5） | 净利润率、净资产收益率、总资产收益率、毛利率、营业利润率 |
| 偿债能力（5） | 流动比率、速动比率、资产负债率、产权比率、利息保障倍数 |
| 营运能力（5） | 总资产周转率、存货周转率、应收账款周转率、流动资产周转率、固定资产周转率 |
| 发展能力（5） | 营收同比增长率、净利润同比增长率、总资产增长率、净资产增长率、经营现金流增长率 |
| 市场表现（5） | 市盈率、市净率、市销率、PEG 比率、股息收益率 |

### 2.4 决策规则

**综合权重**（`config.json` 的 `analysis_weights`，可配）：

$$\text{comprehensive} = 0.4 \cdot T + 0.4 \cdot F + 0.2 \cdot S$$

**① 技术面打分**（基准 50，clamp `[0,100]`）

| 条件 | 分值 |
|:---|:--:|
| 多头排列 / 空头排列 | +20 / −20 |
| RSI ∈ [30,70] / <30 / >70 | +10 / +5 / −5 |
| MACD 金叉向上 / 死叉向下 | +15 / −15 |
| BB 位置 ∈[0.2,0.8] / <0.2 / >0.8 | +5 / +10 / −5 |
| 放量上涨 / 放量下跌 | +10 / −10 |

**② 基本面打分**（基准 50）

| 条件 | 分值 |
|:---|:--:|
| 有效指标数 ≥ 15 | **+20**（且仅在此分支内才计算下列三项） |
| ROE >15 / >10 / <5 | +10 / +5 / −5 |
| 资产负债率 <30 / >70 | +5 / −10 |
| 营收增长 >20% / >10% / <−10% | +10 / +5 / −10 |
| 有估值数据 | +10 |
| 有业绩预告 | +10 |

> ⚠️ **逻辑缺陷**：ROE / 负债率 / 成长性三项被包在 `if len(indicators) >= 15` 分支内。**指标缺失越多，反而越不参与这三项扣分**，缺失标的的基本面分不会因"数据不可用"而降级，只会在"数据丰富"时才体现分化。

**③ 情绪打分**

$$\text{score} = (\text{sentiment} + 1) \times 50 + \text{confidence} \times 10 + \min(\tfrac{\text{count}}{100}, 1) \times 10$$

- 情绪值：词典子串匹配，`(pos − neg) / (pos + neg)`，无匹配记 0
- 来源权重：公告 1.2 / 公司新闻 1.0 / 研报 0.9 / 行业新闻 0.7
- 置信度：`min(条数 / 50, 1.0)`

> ⚠️ **系统性偏高**：情绪完全中性（0）时基础分已是 50，再加上置信度与新闻量各 10 分，新闻充足的标的**中性情绪也能拿 ~70 分**，经 0.2 权重后白送约 14 分。情绪项实际是"参与度奖励"而非"观点方向"。

**④ 建议映射（单股版）**

| 综合分 | 附加条件 | 建议 |
|:--:|:---|:---|
| ≥ 80 | 技术 ≥75 **且** 基本面 ≥75 | 强烈推荐买入 |
| ≥ 80 | 否 | 推荐买入 |
| ≥ 65 | 情绪 ≥60 | 建议买入 |
| ≥ 65 | 否 | 谨慎买入 |
| ≥ 45 | — | 持有观望 |
| ≥ 30 | — | 建议减仓 |
| < 30 | — | 建议卖出 |

**⑤ 建议映射（全市场版，阈值不同）**：≥80 强烈推荐买入 / ≥60 建议买入 / ≥40 建议观望 / ≥20 建议卖出 / 否则强烈建议卖出。

**⑥ AI 层**：把 25 项指标、前 10 条新闻标题、情绪分数拼进 prompt，要求 LLM 输出 6 维度分析。`temperature=0.7`、`max_tokens` 4000~6000，主备三厂商自动切换（OpenAI / Claude / 智谱），失败降级到规则模板。

### 2.5 实现级局限（源码级取证）

| # | 问题 | 证据 |
|:--:|:---|:---|
| 1 | **「25 项」实为透传**：全部指标由 `safe_get('中文指标名')` 从下游接口返回字典里取值，取不到即置 0；末尾 `valid_indicators` 再把 0 值过滤掉。有效项数常远低于 25，且**是否被剔除完全取决于上游字段命名** | `_calculate_core_financial_indicators` |
| 2 | **行业新闻恒为空**：`_get_comprehensive_industry_news()` 函数体只有 `industry_news = []` 与一条日志，**注释明确写着"目前返回一个示例结构"** | `_get_comprehensive_industry_news` |
| 3 | **情绪用子串匹配而非分词**：`sum(1 for word in positive_words if word in text)` —— 代码里甚至留了 `# 简化版分词` 与 `words = list(text)` 的未使用变量。否定句（"不会下跌"）、反讽、"减持计划完成" 均会误判 | `calculate_advanced_sentiment_analysis` |
| 4 | **派生指标二次兜底**：净利率 / ROA / ROE 为 0 时才用「营业收入/净利润/总资产/股东权益」重算，但这些基础字段同样来自不确定命名 | 同上 |
| 5 | **列名靠猜**：10/11/12/13 列四套硬编码映射 + 位置兜底，是 akshare 版本兼容的补丁式写法 | `get_stock_data` |
| 6 | **无风控闭环**：无止损/止盈、无仓位、无监管异动检查、无会计审计排雷、无主力资金/盘口/席位、无回测 |
| 7 | **工程化程度低**：仓库内 6 个版本目录并存（作者自述「3.1 出现大量 bug，回退」）、无测试文件、无 CI 之外的质量门控 |

---

## 三、四维逐项对比

### 3.1 分析目标

| 对比项 | `stock-scanner` | `ast-trader` |
|:---|:---|:---|
| 核心命题 | 把分散的公开数据汇总成一份「看起来专业」的分析 | 同时对抗两类失效：只看财报不看盘口 / 只看 K 线不排雷（README:10-12） |
| 输出形态 | LLM 生成的 6 维度长文（财务/技术/情绪/价值/策略/风险） | 结构化决断卡：五支柱正文 + 六档档位 + 持币者/持股者双轨战术 |
| 呈现端 | PyQt6 桌面 GUI + Flask Web（SSE 流式） | Rich 终端（`presentation/terminal_view.py`）+ 单文件离线 HTML（`presentation/html_renderer.py`） |
| 时间尺度 | 隐含中长线（365 日线 + 定期报告） | 短线博弈为主，基本面审计作防守底线 |
| 是否有仓位/止损 | **无** | **有**：上限 0.20 / 极端档 0.25（置信度 ≥90）/ 左尾回撤 >25% 腰斩至 10%（`config.py:327-331`） |
| 是否有合规约束 | **无** | **有**：近 10 日严重异动 100% 监管安全垫余量 |
| 是否有回测 | **无** | 账本 `screener_tracker.jsonl` 已落盘，回测引擎 A-4 **未实施** |

### 3.2 处理流程

| 对比项 | `stock-scanner` | `ast-trader` |
|:---|:---|:---|
| 单股链路步数 | 8 步（顺序执行，无门控） | 16 步（`core/analyzer.py:91-207`） |
| 全市场漏斗 | 1 层：全量并发 → `score ≥ 85` 过滤 | 5 层：L0 母池 → L1 画像 → T1 流动性 → T2 排雷 → T3 打分 → 四轨分流 |
| 缺失数据处理 | 静默 `{}` / `[]` / 0 兜底 | Fail-Closed：置 `None` + 强制声明原因（`data/degraded.py`） |
| 硬阻断机制 | 仅「收盘价 ≤ 0」与「不足 60 根 K 线」两条 | ① 日K/快照任一为空 → `return None` ② 覆盖率 <0.98 → `blocked`，`picks` 恒空（`config.py:169`） |
| 门控/校验 | 无 | Lint 16 条（R7~R18）+ JSON Schema Draft 2020-12 契约校验 |
| 归因审计 | 无 | `FunnelAudit`：守恒断言 `input == Σ dropped_by_reason + output` + **死规则检测** |
| 缺口向上穿透 | 无 | **有**：如减持取数失败 → 质地五问 Q4 由 ✓ 强制降为 ⚠️ 并在证据串显式披露 |
| AI 角色 | **核心**：结论由 LLM 生成（temperature=0.7） | **可选且封死**：默认关闭（`config.py:31`），三条硬边界——只能降级 / 只能加风险 / 失败即弃权，且**禁止输出价格** |
| 历史连续性 | 无状态 | 主力状态机多日持久化（`.cache/mainforce_history_state.json`，`persistence_window=2`） |

### 3.3 技术实现

| 对比项 | `stock-scanner` | `ast-trader` |
|:---|:---|:---|
| 核心依赖 | `akshare`、`pandas`、`numpy`、`flask`、`PyQt6`、`openai`/`anthropic`/`zhipuai` | `eltdx>=3.0.0`、`pandas`、`numpy`、`rich`、`jsonschema`、`pypdf` |
| 数据协议 | HTTP REST（第三方站点封装） | 通达信原生 TCP 二进制协议 + Rust 扩展 |
| 并发模型 | `ThreadPoolExecutor(20)`，`batch_size=20` | `ThreadPoolExecutor`，按通道分级：5 / 5 / 16（F10 深度）/ 3（AI） |
| 限速策略 | 批间 `sleep(uniform(3,5))`；失败退避 `sleep(uniform(2,5))` | TCP 连接池 + 主站四级优先级故障转移（`data/tdx_hosts.py`） |
| 参数可配置性 | 高（`config.json`：权重、缓存 TTL、新闻条数、技术周期、流式开关） | 中高（`config.py`：权重、阈值、超时、并发、仓位上限，集中具名常量化） |
| 确定性 | 低：LLM 生成 + 随机 sleep | 高：全流程本地确定性计算；`AI_TEMPERATURE=0.0` |
| 测试覆盖 | **无测试文件** | **558 passed**（537 离线 + 21 `seednet` 联网种子） |
| 质量门控 | 无 | `lint/validator.py` 16 条规则 + Schema 契约，"以纠代抛"（失败→降级观察+清零仓位） |
| 超时与预算 | 无显式控制 | `ELTDX_TIMEOUT=30`、重试 3 次指数退避封顶 8s、`AI_TOTAL_BUDGET=150s`（`config.py:99-103`） |
| 错误处理范式 | `except` + warning + 默认值 | 异常分级：`EltdxUnavailable`（降级不重试）/ `EltdxFetchError`（可降级）/ `EltdxFormatError`（不可重试）（`data/eltdx_client.py:47-65`） |

### 3.4 数据获取

| 通道 | `stock-scanner` | `ast-trader` |
|:---|:---|:---|
| 日/分钟 K 线 | ✅ 日线（前复权） | ✅ 60 根日 K + L2 微观 |
| 实时快照 | ✅ | ✅（`get_realtime_quote`） |
| **L2 十档盘口** | ❌ | ✅（`get_microstructure`） |
| **逐笔/分时** | ❌ | ✅ |
| 财务三表 | ⚠️ 经由 akshare 拼装，字段命名不确定 | ✅（`eltdx_financial` + 字段映射表） |
| 多期财报 | ❌ 仅取最新一期 | ✅ 一次 32~114 个报告期（268ms/只） |
| 估值指标 | ✅ `stock_a_indicator_lg` | ✅ 行业估值中位数**现场自算** |
| 业绩预告 | ✅ `stock_yjbb_em` | ⚠️ **eltdx 无此通道，规则空转** |
| 股权质押 | ❌ | ✅（`CWServ.tdxf10_gg_zbyz` + `gqzy`） |
| 股东结构 | ✅ 股东户数 + 机构持股 | ✅ 十大流通股东 × 18 期，带类别标签（293ms/只） |
| **龙虎榜席位** | ❌ | ✅（`supplement_api.fetch_lhb_seats`，东财，近 30 天） |
| 新闻/公告/研报 | ✅ | ⚠️ 仅用于杀猪盘 8 维舆情探测 |
| **公告原文 PDF** | ❌ | ✅ 页码级引用（`data/pdf_reader.py`） |
| 全市场天梯/广度 | 部分（行业排名） | ✅ 涨停/炸板/跌停 + 指数动量 + 涨跌家数 |
| 缓存持久化 | ❌ 进程内 dict | ✅ `.cache/` 目录 + 状态机持久化 |
| 健康度追踪 | ❌ | ✅ 四态 + 异常栈（`data/data_health.py:11-21`） |
| 市场覆盖 | A 股（3.x 宣称港美股，作者自述受限） | A 股（含北交所 920xxx 歧义处理） |

---

## 四、`ast-trader` 的优点

**1. 数据纪律可执行化（最强的差异化优势）**
`data/degraded.py` 把「缺失置 `None`，严禁填 0」这条血律变成代码：`missing(field, reason)` **强制要求给出原因，否则 `raise ValueError`** —— 让"忘记声明"比"声明"更麻烦。全库已系统性清理 23 处 `or 0.0` 兜底。对比 `stock-scanner` 缺项静默置 0 后再过滤的做法，这是**根本性的方法论差异**。

**2. 三层可审计性**
① `DataHealthTracker` 四态记录（SUCCESS / EMPTY / FAILED / DEGRADED，含异常栈）→ ② `FunnelAudit` 归因守恒 + 死规则检测 → ③ Lint 16 条门控。三层叠加使"系统为什么给出这个结论"可完整回溯。

**3. Fail-Closed 失败语义**
覆盖率 <0.98 → `picks` 恒空（"残缺的全市场比没有更危险"）；致命红旗 → 档位重写「回避」+ 仓位 0.0；Lint 失败 → 降级「观察」+ 清零。**所有失败路径都收敛到"不出手"**，而非"给个差不多的答案"。

**4. 会计审计排雷深度**
12 项实装模型（Piotroski / Beneish / Altman / DuPont / Buffett / Sloan / 治理 / 股东流 / 预告异常 / 估值 / 关联方 / 投资收益侵蚀），且有**行业适用性准入主动弃权**机制（虽当前仅覆盖金融业）。`stock-scanner` 此维度为 0。

**5. A 股本土地化洞察**
主力 7 阶段状态机（含迟滞 + 多日持久化 + 反伪装 7 项审计）、L2 聪明钱 Q 因子（$s = ret/\sqrt{vol}$，取累计量前 20%）、24 大游资战法画像、龙虎榜席位容量射程、杀猪盘 8 维、投机情绪闸门（跌停 ≥15 家收紧）。这些是 `stock-scanner` 完全不具备的维度。

**6. AI 边界设计克制**
AI 默认关闭、只能降级不能升级、只能加风险不能减、失败即弃权、禁止输出价格、提名级别双重封顶。把 LLM 定位为"只读语义协处理器"而非"数值生成者"。

**7. 工程质量**
558 测试（537 可离网执行）、16 条 Lint、JSON Schema 契约、单点真理原则（五个问题各归其位）、保序回填修复、具名常量化（魔数已消除）。

**8. 性能约束驱动架构**
`bars.get` 26ms/只 的实测硬约束直接塑造了「免费字段预筛 → 懒加载日 K」的两段式漏斗；F10 并发 16 → 58ms/只。

---

## 五、`stock-scanner` 的优点

**1. 上手门槛极低**
`pip install -r requirements.txt` 即可跑，akshare 无需任何本地数据环境；`ast-trader` 强依赖 `eltdx`（通达信原生 TCP + Rust 扩展），部署成本高一个数量级。

**2. 指标覆盖广度更优（技术面）**
全市场版含 **ATR / OBV + OBV_MA10 / Stochastic %K %D / ROC(10)**，这些在 `ast-trader` 中并无直接对应实现。

**3. 参数可配置性强**
`config.json` 把权重（0.4/0.4/0.2）、缓存 TTL、新闻条数、技术周期、流式开关、自定义 prompt 全部外置，非程序员也能调；`ast-trader` 依赖 `config.py` 常量，改动需动代码。

**4. 多端交互体验更好**
PyQt6 桌面 GUI + Flask Web（SSE 流式推理实时展示思考过程）+ Docker 一键部署 + Nginx 反代配置，产品化程度高于 `ast-trader` 的 CLI + HTML。

**5. 语义层的"可读性"**
对非专业用户，LLM 生成的连贯研报比结构化决断卡更易读；`ast-trader` 为此专门补了 `presentation/plain_language.py` 白话翻译层，正说明原生输出门槛偏高。

**6. 基本面字段面宽**
一次性抓取 8 大类（基本信息/25 项指标/估值/业绩预告/分红配股/行业/股东/机构持股），信息面覆盖比 `ast-trader` 更"宽而浅"。

**7. 社区验证度高**
1.2k stars / 440 forks，说明其定位击中了"想快速得到一份个股分析"的普遍需求。

---

## 六、双方不足

### 6.1 `stock-scanner` 的不足

| # | 不足 | 影响 |
|:--:|:---|:---|
| 1 | **25 项财务指标名不副实**（取值依赖上游字段命名，缺项静默置 0 后过滤） | 实际有效项数不可控，评分基础不稳定 |
| 2 | **行业新闻恒空** | 「综合情绪」少一个维度且不披露 |
| 3 | **情绪用子串匹配、无分词无否定处理** | "不会下跌"、"减持完成" 会反向误判 |
| 4 | **情绪分系统性偏高**（中性也给 ~70 分） | 情绪项退化为"新闻量奖励"，失去方向性 |
| 5 | **基本面分逻辑倒置**（只有指标 ≥15 项才参与 ROE/负债/成长扣分） | 数据缺失的标的反而不会被扣分 |
| 6 | **全市场扫描无基本面/情绪**，与 README 宣传不符 | 选股结果实为纯技术面排序 |
| 7 | **完全无风控闭环**（无止损、仓位、合规、回测） | 输出无法直接用于实盘 |
| 8 | **LLM temperature=0.7 生成结论** | 同一标的两跑两次结论可能不同，不可复现 |
| 9 | **无测试、无 CI 门控**；6 个版本目录并存 | 作者自述「3.1 出现大量 bug，回退」 |
| 10 | **依赖第三方站点接口** | akshare 上游接口变更即失效，需持续打补丁（四套列名映射即证据） |
| 11 | 随机 `sleep` 限速 | 扫描耗时不可预测、不可复现 |

### 6.2 `ast-trader` 的不足（引用其自查清单 `docs/UNIMPLEMENTED_WORKLIST.md`）

**基础设施/依赖层**

| # | 不足 | 说明 |
|:--:|:---|:---|
| 1 | **强依赖 `eltdx` 与通达信数据环境** | 部署门槛远高于 `pip install akshare`；离线/内网环境不可用 |
| 2 | **无新闻全文分析通道** | 仅用于杀猪盘 8 维探测，未做系统性的新闻/公告/研报情绪量化 |
| 3 | **无业绩预告数据源** | `forecast_anomaly` 规则**恒定空转**（E-3） |

**模型正确性层**

| # | 不足 | 说明 |
|:--:|:---|:---|
| 4 | **Altman Z 行业误报（D-6）** | 中芯国际 🔴「破产高危」、宁德时代 🟠「财务状况脆弱」；行业准入仅覆盖金融业 |
| 5 | **STAGE_7 判定未纳入当日动能（D-35 子项）** | 科达利当日 +7.44%、买盘占优仍判 STAGE_7；目前只能"自曝张力"而不能修正判定 |
| 6 | **估值与审计红旗未联动（D-1）** | 平安银行曾出现「财务操纵高风险」却判「便宜」 |
| 7 | **北交所无独立成交额档位（D-2）** | `filter_liquidity.py:49` 仅 MAIN/GEM 二选一，同文件 `:66` 已有 `is_bse` 判定，自相矛盾 |

**验证层（最需警惕）**

| # | 不足 | 说明 |
|:--:|:---|:---|
| 8 | **买入路径从未被真实触发（D-4）** | 10 只种子跑批 **100% 零仓位** —— 意味着核心仓/期权仓分支在真实数据下从未被验证过 |
| 9 | **性能验收完全缺失（C-4）** | `analyze ≤2s` / `screen ≤15s` / 内存 <500MB 三项承诺**无任何耗时断言**，未纳入 CI |
| 10 | **造假识别未经真实样本验收（C-3）** | 仅 5 项合成样本；康美药业等真实三表数据缺失 |
| 11 | **文档与代码漂移 3 处** | ① README 六档命名 ≠ `pillar5_decision.py` 实际分支命名 ② seednet 数量 11 vs 21（537+21=558 ✓）③ README「$Q>0.8$」≠ 代码中 $q = VWAP_{smart}/VWAP_{all}$（围绕 1.0 波动） |

**规划但未实施层**

| # | 不足 | 阻塞 |
|:--:|:---|:---|
| 12 | A-2 板块相对强弱轮动矩阵 | 依赖 B-1（采集层无板块级接口） |
| 13 | A-3 龙虎榜席位协同与胜率跟踪 | 阶段二 Week2 未排期 |
| 14 | A-4 实盘账本多日回测与归因 | 🚧 需账本样本积累 |
| 15 | B-1~B-5 五个集成点全未打通 | — |
| 16 | `screen` 定位未裁决（D-5） | 纯短线题材接力 vs 按市值分档，尚未定论 |

> 总账：63 项工作清单中 **43 项已完成、20 项未实施、10 项阻塞**。

---

## 七、互补与迁移建议

### 7.1 `ast-trader` 可向 `stock-scanner` 借鉴

| 方向 | 具体内容 | 理由 |
|:---|:---|:---|
| 技术面指标补齐 | 引入 **ATR**（波动率自适应止损基准）、**OBV**（量价背离）、**Stochastic %K/%D**、**ROC** | ast-trader 目前无 ATR，而 ATR 恰是止损位设定的天然标尺，与既有 `execution_playbook.py` 的止损纪律直接互补 |
| 参数外置 | 把 `config.py` 中的阈值外置为 JSON/YAML 配置层 | 降低非程序员调参门槛（现有 63 项清单中的大量"阈值待裁决"问题会更容易收敛） |
| 交互与部署 | 参考其 Docker + Nginx SSE 配置 | 提升产品化交付能力 |

### 7.2 `stock-scanner` 应向 `ast-trader` 借鉴

| 方向 | 具体内容 |
|:---|:---|
| 缺失数据纪律 | 用 `data/degraded.py` 范式替代 `safe_get(..., 0)` 静默兜底 |
| 情绪算法 | 子串匹配 → 分词 + 否定词/程度副词处理；修正"中性也给 70 分"的基线偏移 |
| 基本面评分 | 解耦"指标可用性"与"指标质量"，避免缺数据反而不扣分 |
| 风控闭环 | 至少补：止损位、单票仓位上限、监管异动检查 |
| 可复现性 | 去掉随机 `sleep` 与 `temperature=0.7`，或把随机性显式参数化 |

### 7.3 结论

两者**并非同类竞品**：

- `stock-scanner` 解决的是「**我没有数据工程能力，但想快速看一只股票的综合画像**」；
- `ast-trader` 解决的是「**我要一个能被审计、能给出明确仓位与止损、且不会在数据缺失时糊弄我的决策系统**」。

若做融合，合理的架构是：**以 `ast-trader` 的确定性引擎为底座（负责数值、排雷、仓位），叠加 `stock-scanner` 式的 LLM 语义层（负责可读性与新闻归因）**——这与 `docs/ROADMAP_AND_AI_EVOLUTION.md` 中已规划的「量化底座 + AI 语义协处理器」双引擎架构方向一致。
