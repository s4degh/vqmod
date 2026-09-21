import sys
import types

# Allow testing pure strategy helpers on systems without the Windows MT5 package.
mt5 = types.SimpleNamespace(TIMEFRAME_H1=1, TIMEFRAME_M30=2, TIMEFRAME_M15=3, TIMEFRAME_M5=4, TIMEFRAME_M1=5)
sys.modules.setdefault("MetaTrader5", mt5)

import pandas as pd
from bot import MT5Scalper, StrategyConfig


def frame(rows):
    data = pd.DataFrame(rows)
    data["ema20"] = data["ema20"] if "ema20" in data else data.close
    data["ema50"] = data["ema50"] if "ema50" in data else data.close
    return data


def test_bullish_bias_with_structure_break():
    rows = [{"open": 10, "high": 11 + i / 10, "low": 9, "close": 11 + i / 10, "ema20": 10, "ema50": 9} for i in range(8)]
    frames = {name: frame(rows) for name in ("H1", "M30", "M15")}
    assert MT5Scalper(StrategyConfig()).market_bias(frames) == "buy"


def test_closed_ignores_active_candle():
    data = frame([{"open": 1, "high": 1, "low": 1, "close": 1}, {"open": 2, "high": 2, "low": 2, "close": 2}])
    assert MT5Scalper.closed(data).close == 1
