"""Global configuration for AST-Trader."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "ast_trader.log"

CACHE_DIR = BASE_DIR / ".cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ─── 通达信行情服务器节点池 ───
DEFAULT_TDX_HOSTS = [
    ("119.147.212.81", 7709),   # 深圳行情主站
    ("114.80.63.12", 7709),     # 上海电信主站
    ("124.160.88.183", 7709),   # 杭州主站
    ("221.231.141.60", 7709),   # 南京电信
    ("180.153.39.51", 7709),    # 上海双线
]

# ─── 短线风控红线 ───
PLEDGE_FATAL_RATIO = 0.70        # 控股股东质押比例 > 70% 致命
BENEISH_M_FATAL_SCORE = -1.78   # Beneish M-Score > -1.78 判定高概率造假
SLOAN_ACCRUAL_FATAL_RATIO = 0.15 # 应计利润 / 总资产 > 15% 严重异象
FORECAST_DROP_FATAL_RATIO = -0.50 # 业绩预告扣非同比下滑 > 50% 或首亏

# ─── 全市场短线漏斗初筛阈值 ───
LIQUIDITY_MAIN_MIN_AMOUNT = 5.0e8   # 主板最低成交额 5.0 亿元
LIQUIDITY_GEM_MIN_AMOUNT = 3.0e8    # 双创板最低成交额 3.0 亿元
MOMENTUM_MIN_PCT_CHG = 4.5          # 最低涨幅 4.5%
MOMENTUM_MIN_TURNOVER_RATE = 7.0    # 换手率下限 7%
MOMENTUM_MAX_TURNOVER_RATE = 28.0   # 换手率上限 28% (过高防滞涨出货)

# ─── 仓位与博弈阈值 ───
MAX_SINGLE_POSITION = 0.20          # 短线单票最大仓位上限 20%
LEFT_TAIL_WARN_THRESHOLD = 0.25     # 左尾回撤 > 25% 仓位强制腰斩至 10%
