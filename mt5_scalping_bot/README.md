# MT5 Multi-timeframe Scalping Bot

> **Important:** This is an educational automation template, not investment advice or a promise of profitability. Scalping is high risk. Test on a **demo** account and review every configuration value before allowing real orders. The bot starts in `DRY_RUN=true` mode, so it will never send an order until you explicitly change it.

## What it does

1. Gets MT5 candles for `H1`, `M30`, `M15`, `M5`, and `M1`.
2. Uses EMA alignment and M15 market structure to establish a directional bias.
3. Blocks new entries around configurable high-impact calendar events.
4. Looks for a pullback/rejection on M5 and a breakout confirmation on the most recently closed M1 candle.
5. Opens at most one `0.05` lot position (configurable), placing a stop beyond the M5 setup and a **2:1 reward/risk** target.
6. Actively protects an open position: it closes when momentum and price action contradict it, but tolerates a small adverse move while the higher-timeframe bias and position trend remain valid.

No strategy can guarantee that a loss will reverse. The exit rules are deterministic risk controls, not a prediction.

## Prerequisites

- Windows machine with the MetaTrader 5 desktop terminal installed, open, and logged into the target account.
- Python 3.10+.
- The symbol must be visible in MT5 Market Watch and trading must be enabled in the terminal/account.

## Installation

```bash
cd mt5_scalping_bot
python -m venv .venv
.venv\\Scripts\\activate          # Windows PowerShell/cmd equivalent is also fine
pip install -r requirements.txt
copy .env.example .env               # Windows
# cp .env.example .env               # macOS/Linux
```

Set `DRY_RUN=false` in `.env` only after demo validation. If needed, fill `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER`, and `MT5_PATH`; otherwise the bot uses the terminal's active session.

## Run

```bash
python bot.py
```

The log states every skip, signal, virtual order, sent order, and managed exit. Stop the process with `Ctrl+C`.

The project is kept as source files in this repository; install it using the steps above rather than a bundled ZIP archive.

## News feed contract

`NEWS_URL` is deliberately configurable because calendar API providers differ. It must return a JSON list of objects such as:

```json
[{"time":"2026-09-21T12:30:00Z", "currency":"USD", "impact":"high", "title":"CPI"}]
```

When no URL is configured, the calendar gate is disabled. When a configured request fails, the bot logs the condition and applies its **fail-closed** policy for new entries. It never fetches browser pages or scrapes sites.

## Operational safeguards

- One strategy position per symbol/magic number.
- Spread cap before entries.
- Daily realized-loss cap before entries.
- Entry analysis only uses completed candles (`iloc[-2]`), avoiding intrabar look-ahead.
- Server-side SL/TP are submitted with every real order.
- Volume and prices are normalized to broker constraints.

Review `StrategyConfig` in `bot.py` and broker contract specifications (minimum stop distance, filling mode, volume) before live use.
