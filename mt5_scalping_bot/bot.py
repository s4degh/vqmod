"""Multi-timeframe MT5 scalping template. Run in DRY_RUN mode until validated."""
from __future__ import annotations

import json
import logging
import math
import os
import signal
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import MetaTrader5 as mt5
import pandas as pd
import requests
from dotenv import load_dotenv

UTC = timezone.utc
TIMEFRAMES = {
    "H1": mt5.TIMEFRAME_H1,
    "M30": mt5.TIMEFRAME_M30,
    "M15": mt5.TIMEFRAME_M15,
    "M5": mt5.TIMEFRAME_M5,
    "M1": mt5.TIMEFRAME_M1,
}


@dataclass(frozen=True)
class StrategyConfig:
    symbol: str = "EURUSD"
    lot: float = 0.05
    magic: int = 26092026
    dry_run: bool = True
    poll_seconds: int = 5
    max_spread_points: int = 20
    daily_loss_limit: float = 100.0
    news_url: str = ""
    news_currencies: tuple[str, ...] = ("USD", "EUR")
    news_before: int = 30
    news_after: int = 15
    # Choose safety over availability when a configured calendar cannot be reached.
    fail_closed_on_news_error: bool = True

    @classmethod
    def from_environment(cls) -> "StrategyConfig":
        """Read settings after ``load_dotenv`` has populated the environment."""
        return cls(
            symbol=os.getenv("SYMBOL", "EURUSD"),
            lot=float(os.getenv("LOT", "0.05")),
            magic=int(os.getenv("MAGIC", "26092026")),
            dry_run=os.getenv("DRY_RUN", "true").lower() == "true",
            poll_seconds=int(os.getenv("POLL_SECONDS", "5")),
            max_spread_points=int(os.getenv("MAX_SPREAD_POINTS", "20")),
            daily_loss_limit=float(os.getenv("DAILY_LOSS_LIMIT", "100")),
            news_url=os.getenv("NEWS_URL", ""),
            news_currencies=tuple(x.strip().upper() for x in os.getenv("NEWS_CURRENCIES", "USD,EUR").split(",") if x.strip()),
            news_before=int(os.getenv("NEWS_BLOCK_BEFORE_MINUTES", "30")),
            news_after=int(os.getenv("NEWS_BLOCK_AFTER_MINUTES", "15")),
        )


class MT5Scalper:
    def __init__(self, config: StrategyConfig) -> None:
        self.cfg = config
        self.running = True
        self.last_news_check = datetime.min.replace(tzinfo=UTC)
        self.news_blocked = False

    def connect(self) -> None:
        kwargs = {k: v for k, v in {
            "login": int(os.environ["MT5_LOGIN"]) if os.getenv("MT5_LOGIN") else None,
            "password": os.getenv("MT5_PASSWORD"),
            "server": os.getenv("MT5_SERVER"),
            "path": os.getenv("MT5_PATH"),
        }.items() if v is not None}
        if not mt5.initialize(**kwargs):
            raise RuntimeError(f"MT5 initialization failed: {mt5.last_error()}")
        if not mt5.symbol_select(self.cfg.symbol, True):
            raise RuntimeError(f"Cannot select {self.cfg.symbol}: {mt5.last_error()}")
        logging.info("Connected to MT5; symbol=%s dry_run=%s", self.cfg.symbol, self.cfg.dry_run)

    def candles(self, name: str, count: int = 250) -> pd.DataFrame:
        rates = mt5.copy_rates_from_pos(self.cfg.symbol, TIMEFRAMES[name], 0, count)
        if rates is None or len(rates) < 60:
            raise RuntimeError(f"Insufficient {name} candle data: {mt5.last_error()}")
        frame = pd.DataFrame(rates)
        frame["time"] = pd.to_datetime(frame["time"], unit="s", utc=True)
        frame["ema20"] = frame["close"].ewm(span=20, adjust=False).mean()
        frame["ema50"] = frame["close"].ewm(span=50, adjust=False).mean()
        return frame

    @staticmethod
    def closed(frame: pd.DataFrame) -> pd.Series:
        """MT5's final row is the active candle; never base a signal on it."""
        return frame.iloc[-2]

    def market_bias(self, frames: dict[str, pd.DataFrame]) -> Optional[str]:
        h1, m30, m15 = (self.closed(frames[x]) for x in ("H1", "M30", "M15"))
        bullish = all(c.close > c.ema20 > c.ema50 for c in (h1, m30, m15))
        bearish = all(c.close < c.ema20 < c.ema50 for c in (h1, m30, m15))
        # Confirm M15 price action: latest completed swing closes beyond preceding range.
        structure = frames["M15"].iloc[-8:-2]
        if bullish and m15.close > structure.high.iloc[:-1].max():
            return "buy"
        if bearish and m15.close < structure.low.iloc[:-1].min():
            return "sell"
        return None

    def entry_signal(self, side: str, frames: dict[str, pd.DataFrame]) -> Optional[tuple[float, float]]:
        m5, m1 = self.closed(frames["M5"]), self.closed(frames["M1"])
        # Rejection/pullback at M5 EMA20 plus M1 breakout confirmation.
        if side == "buy":
            rejected = m5.low <= m5.ema20 and m5.close > m5.open and m5.close > m5.ema20
            confirmed = m1.close > m1.open and m1.close > frames["M1"].iloc[-3].high
            return (float(m5.low), float(m1.close)) if rejected and confirmed else None
        rejected = m5.high >= m5.ema20 and m5.close < m5.open and m5.close < m5.ema20
        confirmed = m1.close < m1.open and m1.close < frames["M1"].iloc[-3].low
        return (float(m5.high), float(m1.close)) if rejected and confirmed else None

    def event_window_active(self) -> bool:
        if not self.cfg.news_url:
            return False
        now = datetime.now(UTC)
        if (now - self.last_news_check).total_seconds() < 60:
            return self.news_blocked
        self.last_news_check = now
        try:
            response = requests.get(self.cfg.news_url, timeout=8)
            response.raise_for_status()
            events = response.json()
            if not isinstance(events, list):
                raise ValueError("calendar response is not a list")
            for event in events:
                currency = str(event.get("currency", "")).upper()
                impact = str(event.get("impact", event.get("importance", ""))).lower()
                is_high = impact == "high" or impact == "3"
                raw_time = event.get("time")
                event_time = datetime.fromtimestamp(raw_time, UTC) if isinstance(raw_time, (int, float)) else datetime.fromisoformat(str(raw_time).replace("Z", "+00:00"))
                if currency in self.cfg.news_currencies and is_high and event_time - timedelta(minutes=self.cfg.news_before) <= now <= event_time + timedelta(minutes=self.cfg.news_after):
                    logging.warning("New entries blocked for high-impact %s event: %s", currency, event.get("title", "unnamed"))
                    self.news_blocked = True
                    return True
            self.news_blocked = False
        except (requests.RequestException, ValueError, TypeError, json.JSONDecodeError) as exc:
            self.news_blocked = self.cfg.fail_closed_on_news_error
            logging.error("News calendar unavailable/invalid (%s); fail_closed=%s", exc, self.news_blocked)
        return self.news_blocked

    def positions(self) -> list[Any]:
        found = mt5.positions_get(symbol=self.cfg.symbol)
        return [p for p in (found or []) if p.magic == self.cfg.magic]

    def daily_loss_reached(self) -> bool:
        start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        deals = mt5.history_deals_get(start, datetime.now(UTC)) or []
        realized = sum(d.profit + d.swap + d.commission for d in deals if d.magic == self.cfg.magic and d.symbol == self.cfg.symbol)
        return realized <= -self.cfg.daily_loss_limit

    def normalize_volume(self, volume: float, info: Any) -> float:
        value = max(info.volume_min, min(volume, info.volume_max))
        return round(math.floor(value / info.volume_step) * info.volume_step, 2)

    def place_entry(self, side: str, setup_stop: float) -> None:
        info, tick = mt5.symbol_info(self.cfg.symbol), mt5.symbol_info_tick(self.cfg.symbol)
        if info is None or tick is None:
            logging.error("No symbol/tick information: %s", mt5.last_error()); return
        spread = (tick.ask - tick.bid) / info.point
        if spread > self.cfg.max_spread_points:
            logging.info("Skip entry: spread %.1f > cap %s", spread, self.cfg.max_spread_points); return
        price = tick.ask if side == "buy" else tick.bid
        min_distance = max(info.trade_stops_level * info.point, 2 * info.point)
        stop = min(setup_stop, price - min_distance) if side == "buy" else max(setup_stop, price + min_distance)
        risk = abs(price - stop)
        if risk <= 0:
            return
        target = price + 2 * risk if side == "buy" else price - 2 * risk
        digits = info.digits
        request = {"action": mt5.TRADE_ACTION_DEAL, "symbol": self.cfg.symbol, "volume": self.normalize_volume(self.cfg.lot, info), "type": mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL, "price": round(price, digits), "sl": round(stop, digits), "tp": round(target, digits), "deviation": 20, "magic": self.cfg.magic, "comment": "MTF_PA_scalper", "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC}
        if self.cfg.dry_run:
            logging.warning("DRY RUN entry: %s", request); return
        result = mt5.order_send(request)
        logging.info("Entry result: %s", result)

    def close_position(self, position: Any, reason: str) -> None:
        tick = mt5.symbol_info_tick(self.cfg.symbol)
        side = mt5.ORDER_TYPE_SELL if position.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
        request = {"action": mt5.TRADE_ACTION_DEAL, "position": position.ticket, "symbol": self.cfg.symbol, "volume": position.volume, "type": side, "price": tick.bid if side == mt5.ORDER_TYPE_SELL else tick.ask, "deviation": 20, "magic": self.cfg.magic, "comment": f"exit:{reason}", "type_filling": mt5.ORDER_FILLING_IOC}
        if self.cfg.dry_run:
            logging.warning("DRY RUN close (%s): %s", reason, request); return
        logging.warning("Closing %s because %s: %s", position.ticket, reason, mt5.order_send(request))

    def manage_positions(self, frames: dict[str, pd.DataFrame], bias: Optional[str]) -> None:
        m1 = self.closed(frames["M1"])
        tick = mt5.symbol_info_tick(self.cfg.symbol)
        for pos in self.positions():
            is_buy = pos.type == mt5.POSITION_TYPE_BUY
            price = tick.bid if is_buy else tick.ask
            profitable = (price - pos.price_open) > 0 if is_buy else (pos.price_open - price) > 0
            adverse = (price - pos.price_open) < 0 if is_buy else (pos.price_open - price) < 0
            reversal = (is_buy and m1.close < m1.ema20 and m1.close < m1.open) or (not is_buy and m1.close > m1.ema20 and m1.close > m1.open)
            bias_lost = bias != ("buy" if is_buy else "sell")
            # In profit: exit at the first credible M1 reversal. In loss: retain only
            # while the multi-timeframe direction still supports it.
            if profitable and reversal:
                self.close_position(pos, "profit_reversal")
            elif adverse and reversal and bias_lost:
                self.close_position(pos, "loss_with_bias_failure")

    def run_once(self) -> None:
        frames = {name: self.candles(name) for name in TIMEFRAMES}
        bias = self.market_bias(frames)
        self.manage_positions(frames, bias)
        if self.positions() or not bias or self.event_window_active() or self.daily_loss_reached():
            return
        setup = self.entry_signal(bias, frames)
        if setup:
            self.place_entry(bias, setup[0])

    def run(self) -> None:
        self.connect()
        while self.running:
            try:
                self.run_once()
            except Exception:
                logging.exception("Cycle failed; no order was sent by this error path")
            time.sleep(self.cfg.poll_seconds)


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    bot = MT5Scalper(StrategyConfig.from_environment())
    signal.signal(signal.SIGINT, lambda *_: setattr(bot, "running", False))
    try:
        bot.run()
    finally:
        mt5.shutdown()
        logging.info("MT5 disconnected")


if __name__ == "__main__":
    main()
