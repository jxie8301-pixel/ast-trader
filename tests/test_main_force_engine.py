"""主力行为生命周期状态机与反伪装引擎深度测试用例。

全面覆盖：
1. 7 大生命周期阶段判定逻辑与量化阈值；
2. 7 大反伪装过滤检测与扣分惩罚机制 (对倒自成交、假突破、假破位、尾盘偷袭、算法拆单穿透等)；
3. 状态转移迟滞与熔断回退规则；
4. 生产级安全死锁：高标缩量加速期仓位上限锁定为 0% 且强制观察档位；
5. 缺失数据与边界异常优雅降级。
"""
from __future__ import annotations

import pandas as pd
import pytest

from core.main_force_engine import (
    AntiSpoofingAudit,
    MainForceDecision,
    MainForceStateEngine,
    StageCode,
)


@pytest.fixture
def engine():
    return MainForceStateEngine(persistence_window=2)


def test_stage_1_accumulation_detection(engine):
    """测试阶段 1: 低位隐蔽吸筹期识别。"""
    daily_records = []
    # 构造底部 60 日箱体收敛震荡，前期高点 12.0，前期低点 9.5，现价 9.95 处于底部 18% 分位且近 5 日振幅极度收敛
    for i in range(60):
        if i < 5:
            # 最近 5 日振幅极窄 (3%)
            daily_records.append({"high": 10.10, "low": 9.80, "close": 10.0, "vol": 10000.0})
        else:
            # 早期历史高低点
            daily_records.append({"high": 12.00 if i == 50 else 10.50, "low": 9.50 if i == 55 else 9.70, "close": 10.0, "vol": 10000.0})
    daily_df = pd.DataFrame(daily_records)

    micro = {
        "smart_q": 0.975,
        "smart_vwap": 9.90,
        "all_vwap": 10.05,
        "smart_buy_ratio": 62.0,
        "smart_sell_ratio": 38.0,
        "smart_phase": "ACCUMULATION",
        "apm_pattern": "PM_ABSORPTION",
        "tail_vol_ratio": 8.0,
    }
    mom = {
        "overhead_chip_pct": 25.0,
        "current_drawdown": -8.0,
        "is_bullish_ma": False,
        "ma5": 10.0,
        "ma20": 10.2,
    }
    quote = {"close": 9.95, "open": 9.90, "high": 10.10, "low": 9.85, "turnover_ratio": 2.5, "amount": 25000000.0}

    dec = engine.evaluate("000001.SZ", current_price=9.95, quote=quote, daily_df=daily_df, microstructure=micro, momentum=mom)

    assert dec.stage_code == StageCode.STAGE_1_ACCUMULATION
    assert "隐蔽吸筹" in dec.stage_name
    assert dec.suggested_pos_cap == 0.10
    assert dec.anti_spoofing.stealth_accumulation_detected is True


def test_stage_2_bear_trap_washout_detection(engine):
    """测试阶段 2: 假破位恐慌挖坑期 (空头陷阱) 识别。"""
    daily_records = []
    for i in range(25):
        daily_records.append({"high": 20.0, "low": 18.0, "close": 19.0, "vol": 20000.0})
    # 今日缩量跌破支撑
    daily_records[0]["vol"] = 8000.0  # 量比 0.4x 极度缩量破位
    daily_df = pd.DataFrame(daily_records)

    micro = {
        "smart_q": 0.990,
        "smart_vwap": 17.60,
        "all_vwap": 17.50,
        "smart_buy_ratio": 65.0,  # 微观机构逆势低吸承接
        "smart_sell_ratio": 35.0,
        "smart_phase": "NEUTRAL",
        "apm_pattern": "PM_ABSORPTION",  # 午后逆势承接
        "tail_vol_ratio": 12.0,
    }
    mom = {
        "overhead_chip_pct": 35.0,
        "current_drawdown": -12.0,
        "is_bullish_ma": False,
        "ma5": 18.2,
        "ma20": 18.5,  # 现价 17.5 破位 MA20
    }
    quote = {"close": 17.50, "open": 18.00, "high": 18.10, "low": 17.40, "pct_chg": -3.0, "turnover_ratio": 1.8, "amount": 35000000.0}

    dec = engine.evaluate("000002.SZ", current_price=17.50, quote=quote, daily_df=daily_df, microstructure=micro, momentum=mom)

    assert dec.stage_code == StageCode.STAGE_2_BEAR_TRAP_WASHOUT
    assert "挖坑" in dec.stage_name or "假破位" in dec.stage_name
    assert dec.anti_spoofing.fake_breakdown_detected is True
    assert dec.suggested_pos_cap == 0.10


def test_stage_3_quiet_washout_detection(engine):
    """测试阶段 3: 缩量洗盘蓄势期 (时间换空间) 识别。"""
    daily_records = []
    for i in range(25):
        daily_records.append({"high": 15.2, "low": 14.8, "close": 15.0, "vol": 20000.0})
    daily_records[0]["vol"] = 9000.0  # 缩量至 45%
    daily_df = pd.DataFrame(daily_records)

    micro = {
        "smart_q": 1.001,
        "smart_vwap": 15.0,
        "all_vwap": 15.0,
        "smart_buy_ratio": 51.0,
        "smart_sell_ratio": 49.0,
        "smart_phase": "NEUTRAL",
        "apm_pattern": "NEUTRAL",
        "tail_vol_ratio": 10.0,
    }
    mom = {
        "overhead_chip_pct": 20.0,
        "current_drawdown": -4.0,
        "is_bullish_ma": True,
        "ma5": 15.1,
        "ma20": 14.8,
    }
    quote = {"close": 15.0, "open": 15.0, "high": 15.1, "low": 14.9, "turnover_ratio": 2.0, "amount": 30000000.0}

    dec = engine.evaluate("000003.SZ", current_price=15.0, quote=quote, daily_df=daily_df, microstructure=micro, momentum=mom)

    assert dec.stage_code == StageCode.STAGE_3_QUIET_WASHOUT
    assert "时间换空间" in dec.stage_name or "缩量洗盘" in dec.stage_name
    assert dec.suggested_pos_cap == 0.15


def test_stage_4_healthy_markup_detection(engine):
    """测试阶段 4: 健康放量主升期识别。"""
    daily_records = []
    for i in range(25):
        daily_records.append({"high": 25.0, "low": 20.0, "close": 23.0, "vol": 20000.0})
    daily_records[0]["vol"] = 35000.0  # 放量 1.75 倍
    daily_df = pd.DataFrame(daily_records)

    micro = {
        "smart_q": 1.002,
        "smart_vwap": 23.80,
        "all_vwap": 23.50,
        "smart_buy_ratio": 64.0,
        "smart_sell_ratio": 36.0,
        "smart_phase": "NEUTRAL",
        "apm_pattern": "NEUTRAL",
        "tail_vol_ratio": 12.0,
        "auction_open_chg_pct": 1.8,
        "auction_open_amt_wan": 2500.0,
    }
    mom = {
        "overhead_chip_pct": 8.0,
        "current_drawdown": -2.0,
        "is_bullish_ma": True,
        "ma5": 23.5,
        "ma20": 21.0,
        "ma5_bias": 4.2,
    }
    quote = {"close": 24.50, "open": 23.80, "high": 24.80, "low": 23.60, "turnover_ratio": 8.5, "amount": 180000000.0, "pct_chg": 5.2}

    dec = engine.evaluate("000004.SZ", current_price=24.50, quote=quote, daily_df=daily_df, microstructure=micro, momentum=mom)

    assert dec.stage_code == StageCode.STAGE_4_HEALTHY_MARKUP
    assert "健康" in dec.stage_name or "主升" in dec.stage_name
    assert dec.suggested_pos_cap == 0.20
    assert dec.decision_gear_override is None


def test_stage_5_exhaustion_acceleration_lockdown(engine):
    """测试阶段 5: 缩量加速赶顶期硬核安全死锁 (针对上海九百等高标连板)。"""
    daily_records = []
    for i in range(60):
        daily_records.append({"high": 12.0, "low": 7.0, "close": 11.5, "vol": 20000.0})
    daily_df = pd.DataFrame(daily_records)

    micro = {
        "smart_q": 0.950,
        "smart_vwap": 8.20,  # 底部主力建仓成本 8.2 元，现价 12.0 元，浮盈超 45%
        "all_vwap": 11.90,
        "smart_buy_ratio": 50.0,
        "smart_sell_ratio": 50.0,
        "smart_phase": "NEUTRAL",
        "apm_pattern": "NEUTRAL",
        "tail_vol_ratio": 5.0,
    }
    mom = {
        "overhead_chip_pct": 0.0,
        "current_drawdown": 0.0,
        "is_bullish_ma": True,
        "ma5": 11.0,
        "ma20": 9.0,
        "ma5_bias": 12.5,
    }
    ladder = {
        "board_level": 5,  # 5 连板高标龙头 (如上海九百)
        "is_leader": True,
        "broken_count": 0,
    }
    quote = {
        "close": 12.00,
        "open": 12.00,
        "high": 12.00,
        "low": 12.00,
        "turnover_ratio": 6.8,  # 高位缩量加速
        "pct_chg": 10.0,
        "amount": 90000000.0,
    }

    dec = engine.evaluate("600838.SH", current_price=12.00, quote=quote, daily_df=daily_df, microstructure=micro, momentum=mom, ladder_info=ladder)

    assert dec.stage_code == StageCode.STAGE_5_EXHAUSTION_ACCELERATION
    assert "缩量加速赶顶" in dec.stage_name
    # ── 生产级安全死锁核心校验 ──
    assert dec.suggested_pos_cap == 0.0, "高标加速赶顶必须死锁仓位为 0%，绝对禁止给新买方开仓！"
    assert dec.decision_gear_override == "观察"
    assert "严禁追高" in dec.recommended_action or "严禁追高" in dec.stage_name


def test_stage_6_distribution_detection(engine):
    """测试阶段 6: 对倒派发出货期识别。"""
    daily_records = []
    for i in range(60):
        daily_records.append({"high": 35.0, "low": 20.0, "close": 32.0, "vol": 20000.0})
    daily_df = pd.DataFrame(daily_records)

    micro = {
        "smart_q": 1.028,
        "smart_vwap": 34.20,
        "all_vwap": 33.10,
        "smart_buy_ratio": 32.0,
        "smart_sell_ratio": 68.0,  # 微观高效率出逃
        "smart_phase": "DISTRIBUTION",
        "apm_pattern": "AM_PUMP_PM_DUMP",  # 早盘拉高诱多，下午狂砸
        "tail_vol_ratio": 15.0,
    }
    mom = {
        "overhead_chip_pct": 40.0,
        "current_drawdown": -8.0,
        "is_bullish_ma": False,
        "ma5": 33.5,
        "ma20": 31.0,
    }
    ladder = {"board_level": 2, "broken_count": 3}  # 日内多次炸板
    quote = {"close": 32.50, "open": 34.00, "high": 35.20, "low": 32.00, "pct_chg": -1.5, "turnover_ratio": 22.0, "amount": 550000000.0}

    dec = engine.evaluate("000006.SZ", current_price=32.50, quote=quote, daily_df=daily_df, microstructure=micro, momentum=mom, ladder_info=ladder)

    assert dec.stage_code == StageCode.STAGE_6_DISTRIBUTION
    assert "出货" in dec.stage_name or "派发" in dec.stage_name
    assert dec.suggested_pos_cap == 0.0
    assert dec.decision_gear_override == "回避"


def test_stage_7_passive_drift_detection(engine):
    """测试阶段 7: 无抵抗阴跌出清期识别 (如深跌机构股)。"""
    daily_records = []
    for i in range(60):
        daily_records.append({"high": 120.0, "low": 80.0, "close": 85.0, "vol": 10000.0})
    daily_df = pd.DataFrame(daily_records)

    micro = {
        "smart_q": 1.015,
        "smart_vwap": 92.00,
        "all_vwap": 85.00,
        "smart_buy_ratio": 38.0,
        "smart_sell_ratio": 62.0,
        "smart_phase": "PASSIVE_FALL",
        "apm_pattern": "PASSIVE_DRIFT",
        "tail_vol_ratio": 8.0,
    }
    mom = {
        "overhead_chip_pct": 78.0,  # 套牢盘高达 78%
        "current_drawdown": -28.0,
        "is_bullish_ma": False,
        "ma5": 87.0,
        "ma20": 95.0,
    }
    quote = {"close": 84.50, "open": 86.00, "high": 86.50, "low": 84.00, "pct_chg": -2.2, "turnover_ratio": 0.8, "amount": 60000000.0}

    dec = engine.evaluate("002850.SZ", current_price=84.50, quote=quote, daily_df=daily_df, microstructure=micro, momentum=mom)

    assert dec.stage_code == StageCode.STAGE_7_PASSIVE_DRIFT
    assert "无抵抗阴跌" in dec.stage_name
    assert dec.suggested_pos_cap == 0.0


def test_anti_spoofing_wash_trading_penalty(engine):
    """测试反伪装过滤器：对倒自成交虚假放量惩罚 (Amihud 非流动性与换手背离)。"""
    daily_records = []
    for i in range(25):
        daily_records.append({"high": 10.5, "low": 9.5, "close": 10.0, "vol": 10000.0})
    daily_records[0]["vol"] = 25000.0  # 爆量 2.5 倍
    daily_df = pd.DataFrame(daily_records)

    micro = {"smart_q": 1.000, "smart_vwap": 10.0, "all_vwap": 10.0, "smart_buy_ratio": 50.0, "smart_sell_ratio": 50.0}
    mom = {"overhead_chip_pct": 10.0, "is_bullish_ma": True, "ma5": 10.0, "ma20": 9.5}
    # 换手高达 18%，但涨幅仅 +0.2%，对倒自成交
    quote = {"close": 10.02, "open": 10.00, "high": 10.10, "low": 9.95, "pct_chg": 0.2, "turnover_ratio": 18.0, "amount": 150000000.0}

    dec = engine.evaluate("000008.SZ", current_price=10.02, quote=quote, daily_df=daily_df, microstructure=micro, momentum=mom)

    assert dec.anti_spoofing.wash_trading_detected is True
    assert dec.anti_spoofing.wash_trading_penalty >= 25.0


def test_anti_spoofing_fake_breakout_penalty(engine):
    """测试反伪装过滤器：假突破长上影与高位派发诱多惩罚。"""
    daily_records = []
    for i in range(60):
        daily_records.append({"high": 20.0, "low": 15.0, "close": 18.0, "vol": 15000.0})
    daily_df = pd.DataFrame(daily_records)

    micro = {
        "smart_q": 1.018,
        "smart_vwap": 20.80,
        "all_vwap": 19.80,
        "smart_buy_ratio": 40.0,
        "smart_sell_ratio": 60.0,
        "apm_pattern": "AM_PUMP_PM_DUMP",
    }
    mom = {"overhead_chip_pct": 12.0, "is_bullish_ma": True, "ma5": 19.0, "ma20": 17.5}
    # 冲高 21.50 元创 60 日新高，但收盘大幅回落至 19.80 元留长上影线
    quote = {"close": 19.80, "open": 19.50, "high": 21.50, "low": 19.40, "pct_chg": 1.5, "turnover_ratio": 10.0, "amount": 120000000.0}

    dec = engine.evaluate("000009.SZ", current_price=19.80, quote=quote, daily_df=daily_df, microstructure=micro, momentum=mom)

    assert dec.anti_spoofing.fake_breakout_detected is True
    assert dec.anti_spoofing.fake_breakout_penalty >= 30.0


def test_anti_spoofing_tail_pump_penalty(engine):
    """测试反伪装过滤器：尾盘半小时突击偷袭拉抬惩罚。"""
    daily_records = []
    for i in range(25):
        daily_records.append({"high": 12.0, "low": 11.0, "close": 11.5, "vol": 10000.0})
    daily_df = pd.DataFrame(daily_records)

    # 尾盘半小时成交量占比高达 35% 偷袭拉抬
    micro = {
        "smart_q": 1.002,
        "smart_vwap": 11.80,
        "all_vwap": 11.60,
        "smart_buy_ratio": 52.0,
        "smart_sell_ratio": 48.0,
        "tail_vol_ratio": 35.0,
        "apm_pattern": "NEUTRAL",
    }
    mom = {"overhead_chip_pct": 15.0, "is_bullish_ma": True, "ma5": 11.5, "ma20": 11.0}
    quote = {"close": 11.85, "open": 11.50, "high": 11.90, "low": 11.45, "pct_chg": 3.0, "turnover_ratio": 4.5, "amount": 40000000.0}

    dec = engine.evaluate("000010.SZ", current_price=11.85, quote=quote, daily_df=daily_df, microstructure=micro, momentum=mom)

    assert dec.anti_spoofing.tail_pump_detected is True
    assert dec.anti_spoofing.tail_pump_penalty >= 20.0


def test_state_machine_persistence_and_instant_circuit_breaker(engine):
    """测试状态机迟滞机制与出货 1 日快速熔断。"""
    ticker = "000011.SZ"
    engine.reset_state(ticker)

    # 第 1 步：处于蓄势洗盘期
    q_dict = {"close": 10.0, "open": 10.0, "turnover_ratio": 2.0}
    dec1 = engine.evaluate(ticker, current_price=10.0, quote=q_dict)
    assert dec1.stage_code == StageCode.STAGE_3_QUIET_WASHOUT

    # 第 2 步：若突发遭遇高位派发出货，买方风控 1 日瞬时熔断切换至 STAGE_6
    dist_micro = {
        "smart_q": 1.030,
        "smart_sell_ratio": 75.0,
        "smart_phase": "DISTRIBUTION",
        "apm_pattern": "AM_PUMP_PM_DUMP",
    }
    dist_quote = {"close": 9.5, "open": 10.5, "pct_chg": -5.0, "turnover_ratio": 15.0, "amount": 80000000.0}
    dec2 = engine.evaluate(ticker, current_price=9.5, quote=dist_quote, microstructure=dist_micro)

    assert dec2.stage_code == StageCode.STAGE_6_DISTRIBUTION
    assert "快速熔断" in dec2.transition_note


def test_empty_and_corrupt_data_robustness(engine):
    """测试数据缺失或极端边界条件下的防御性降级，确保永不抛异常崩溃。"""
    # 全空参数评估
    dec = engine.evaluate(
        ticker="000012.SZ",
        current_price=0.0,
        quote=None,
        daily_df=None,
        microstructure=None,
        momentum=None,
        ladder_info=None,
    )
    assert isinstance(dec, MainForceDecision)
    assert dec.confidence >= 15.0
    assert dec.suggested_pos_cap >= 0.0
