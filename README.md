# AST-Trader: A股买方穿透审计与微观主力博弈量化投研系统

> **兼具「买方穿透式基本面审计防守」与「游资微观盘口博弈进攻」的确定性本地量化投研系统**  
> 毫秒级取数 · 100% 数学闭环 · 零 Token 成本 · 零大模型幻觉 · 严禁静默阻断

---

## 🎯 系统定位与核心价值

A股市场具备鲜明的本土资金博弈生态与政策监管约束。传统投研工具往往走向两个极端：
1. **纯学术/古典机构流派（如传统研报/大模型生成器）**：仅看静态财报，不看盘口、挂单、筹码与游资合力，耗时数十分钟且缺乏短线可操作性，频踩连板监管高压线；
2. **纯技术/概念题材流派**：仅凭 K 线技术指标与突发消息追涨杀跌，缺乏财务基本面去伪存真与会计审计排雷，频踩造假暴雷与在途减持大坑。

**AST-Trader** 融合了成熟买方机构的“五维因果判断链”与 A 股本土一线游资的“盘口微观与主力行为特征”，完全基于 **Python 本地确定性量化引擎**，在 1~2 秒内完成全维度穿透分析。

---

## ⚡ 核心能力矩阵

| 核心模块 | 机制与特色 | 输出与呈现 |
| :--- | :--- | :--- |
| **首页「赚不赚钱」数据看板** | 精选毛利/净利、造血能力（OCF/净利）、资本回报（5期ROE趋势）、主营侵蚀度及自由现金流（FCF），绘制紧凑 Sparklines 走势。 | 终端走势字符 + HTML 仪表盘 |
| **支柱 ❶ 是不是好公司？** | **质地五问 · 铁门筛选**：生意赚钱吗 / 质量真吗 / 护城河在吗 / 管理层可信吗 / 财务底子稳吗。筛选信号不进估值乘法。 | 三态评定（✓/⚠️/✗）与最硬核证据 |
| **支柱 ❷ 在变好吗？** | **状态跃迁 $\lambda$ 引擎**：识别生产函数突变，区分“实锤证据”（财报/订单）与“回声传闻”（研报/情绪），确立全链唯一「该等什么」。 | 身份定位 P1~P4 与临界等待锚点 |
| **支柱 ❸ 贵不贵？** | **$P=F+N$ 叙事溢价拆解**：反向 DCF 逆推市场隐含增速与利润率赌注；严格构建 $[SOTP, DCF]$ 估值双锚区间，执行 10 项算术闭环自检。 | 泡沫倍数、安全边际与底座折价 |
| **支柱 ❹ 主力行为与路径承载** | **Main Force 7阶段生命周期状态机**（试盘/吸筹/锁仓/主升/高位震荡/出货/冰点）；L2 聪明钱高频 $Q$ 因子穿透算法拆单；获利盘与左尾底座深度。 | 主力阶段置信度、操盘透视、反伪装 |
| **支柱 ❺ 实战决断与执行战术** | **六档实战档位**；**持币者/持股者双轨实操指引**；9:25 集合竞价挂单策略；T+1 铁律止损线；近 10 日严重异动 100% 监管安全垫余量。 | 双轨战术卡片与硬锁死纪律 |
| **全市场天梯与宏观大盘水温** | 涨停天梯晋级率、主线题材聚合、高度板龙头；大盘基准动量、市场广度涨跌比与投机情绪闸门联动。 | 市场全景面板 + 漏斗精选池 |
| **全通道数据健康度追踪** | 建立 `DataHealthTracker`，**严禁静默 pass**。记录全通道（TDX行情/L2/三表/F10/龙虎榜）成功、空集与失败异常栈，显性化披露信息缺口。 | 终端审计状态栏 + HTML 审计表格 |

---

## 🛠️ 快速上手

### 1. 环境准备
* Python 3.11+
* Windows / Linux / macOS
* 安装依赖：
  ```bash
  pip install -r requirements.txt
  ```

### 2. 命令行执行

#### ① 单股深度穿透分析与研报生成
```bash
# 终端即时输出买方决断卡
python cli.py analyze 600838

# 同时导出离线交互式独立 HTML 研报 (保存在 ./reports 目录)
python cli.py analyze 600838 --html
```

#### ② 全市场短线三层漏斗筛选
```bash
# 盘后模式筛选 (默认取 Top 10)
python cli.py screen --mode close --top 10

# 午盘模式快速扫描
python cli.py screen --mode noon --top 5
```

#### ③ 实盘选股收益与胜率复盘账本
```bash
python cli.py track
```

---

## 📂 项目架构与目录索引

```text
ast-trader/
├── cli.py                         # 统一入口命令行工具 (analyze / screen / track)
├── config.py                      # 系统全局配置参数
│
├── core/                          # 核心中台与量化因果决断引擎
│   ├── judgment_chain.py          # 买方五维闭环决断链中枢
│   ├── derived_metrics.py         # 衍生财务指标与「赚不赚钱」数据看板
│   ├── derivation.py              # P=F+N 叙事溢价拆解、反向 DCF 与双锚清算
│   ├── main_force_engine.py       # 主力行为生命周期 7 阶段状态机
│   ├── microstructure.py          # Level-2 聪明钱高频 Q 因子与微观挂单反伪装
│   ├── macro_regime.py            # 多维宏观大盘与全市场投机情绪闸门
│   ├── audit_engine.py            # 11 经典本土会计审计扫雷引擎 (Beneish, Piotroski等)
│   ├── execution_playbook.py      # 实盘双轨战术与仓位执行手册
│   ├── capital_matrix.py          # 四维资金博弈雷达
│   ├── youzi_personas.py          # 11 位一线知名游资风格契合度画像
│   └── red_flags.py               # 审计与治理红旗聚合与 Top3 提炼
│
├── data/                          # 统一数据采集底层 (通达信 eltdx 引擎)
│   ├── eltdx_collector.py         # 行情、K线、L2微观、三表、F10、全市场指标
│   ├── eltdx_client.py            # TCP 连接池管理
│   ├── supplement_api.py          # 龙虎榜席位与外部补充通道
│   └── data_health.py             # 数据通道健康度审计与信息缺口追踪器
│
├── screener/                      # 全市场短线漏斗筛选系统
│   ├── pipeline.py                # 三层漏斗调度流水线
│   ├── filter_liquidity.py        # Tier 1 流动性与涨幅初筛
│   ├── filter_audit.py            # Tier 2 财务排雷一票否决
│   ├── rank_composite.py          # Tier 3 题材合力打分排序
│   └── ladder_analyzer.py         # 连板天梯、题材主线与晋级率分析器
│
├── presentation/                  # 结果呈现层
│   ├── terminal_view.py           # Rich 终端买方决断卡与天梯看板渲染
│   └── html_renderer.py           # 离线单文件响应式 HTML 研报渲染器
│
├── lint/                          # 质量门控与机检
│   └── validator.py               # 算术闭合、致命红旗硬锁死与单点真理机检
│
├── tests/                         # 自动化测试套件 (56+ 单元与集成测试)
└── docs/                          # 系统深度设计与演进文档
    ├── ARCHITECTURE.md            # 系统架构设计与数据流转规格
    ├── PILLARS_AND_METHODOLOGY.md # 五大支柱与投研量化方法论
    └── ROADMAP_AND_AI_EVOLUTION.md# 终局演进思路与双引擎融合架构
```

---

## 🧪 自动化测试验证

系统所有核心排雷模型、微观盘口拆单算法、五维因果推导与接口健康度均配备了严格的自动化测试用例：
```bash
pytest tests/
# 56 passed in 3.63s (100% 绿色通过)
```

---

## 📚 详细文档索引

* 🏗️ **[系统架构与数据流转规格说明 (`docs/ARCHITECTURE.md`)](docs/ARCHITECTURE.md)**：详细阐述系统各模块交互、数据流时序与接口契约。
* 🧠 **[五大投研支柱与量化方法论 (`docs/PILLARS_AND_METHODOLOGY.md`)](docs/PILLARS_AND_METHODOLOGY.md)**：质地五问、状态跃迁 $\lambda$、反向 DCF、主力 7 阶段与双轨实战战术的数学实现。
* 🚀 **[终局演进思路与双引擎架构 (`docs/ROADMAP_AND_AI_EVOLUTION.md`)](docs/ROADMAP_AND_AI_EVOLUTION.md)**：深入探讨确定性量化引擎与大语言模型（LLM）的优劣边界，规划未来「量化底座 + AI 语义协处理器」的融合演进方案。
