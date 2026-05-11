from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Any

from market_watcher.monitoring import TerminalDashboard
from market_watcher.orchestrator import MarketWatcher, MarketWatcherConfig

logger = logging.getLogger("market_watcher")


def _parse_config_file(config_path: str | None) -> dict[str, Any]:
    if not config_path:
        return {}

    path = Path(config_path)
    if not path.exists():
        return {}

    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
        return data if isinstance(data, dict) else {}

    try:
        import yaml  # type: ignore[import-untyped]

        data = yaml.safe_load(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _env_symbols(default: str) -> list[str]:
    raw = os.getenv("MARKET_WATCHER_SYMBOLS", default)
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


def build_config(args: argparse.Namespace) -> MarketWatcherConfig:
    file_cfg = _parse_config_file(args.config)

    symbols = args.symbols or file_cfg.get("symbols") or _env_symbols("EUR/USD,SPY,BTC-USD")
    if isinstance(symbols, str):
        symbols = [s.strip().upper() for s in symbols.split(",") if s.strip()]

    timeframe = str(
        args.timeframe or file_cfg.get("timeframe") or os.getenv("MARKET_WATCHER_TIMEFRAME", "1h")
    )
    lookback = str(
        args.lookback_period
        or file_cfg.get("lookback_period")
        or os.getenv("MARKET_WATCHER_LOOKBACK", "30d")
    )
    poll_candidate = (
        args.poll_interval_seconds
        if args.poll_interval_seconds is not None
        else file_cfg.get("poll_interval_seconds")
    )
    if poll_candidate is None:
        poll_candidate = os.getenv("MARKET_WATCHER_POLL_SECONDS", "60")
    poll_seconds = float(poll_candidate)

    return MarketWatcherConfig(
        symbols=list(symbols),
        timeframe=timeframe,
        lookback_period=lookback,
        strategy_preset_id=str(
            args.strategy_preset_id
            or file_cfg.get("strategy_preset_id")
            or os.getenv("MARKET_WATCHER_STRATEGY_PRESET", "safe_trend_follower")
        ),
        eli5_mode=bool(
            args.eli5_mode if args.eli5_mode is not None else file_cfg.get("eli5_mode", True)
        ),
        risk_per_trade_percent=float(
            args.risk_per_trade_percent
            if args.risk_per_trade_percent is not None
            else file_cfg.get("risk_per_trade_percent", 1.0)
        ),
        max_daily_loss_percent=float(
            args.max_daily_loss_percent
            if args.max_daily_loss_percent is not None
            else file_cfg.get("max_daily_loss_percent", 3.0)
        ),
        poll_interval_seconds=poll_seconds,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Aletheia Market Watcher service")
    parser.add_argument("--config", default=None, help="Optional YAML/JSON config path")
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--timeframe", default=None)
    parser.add_argument("--lookback-period", default=None)
    parser.add_argument("--strategy-preset-id", default=None)
    parser.add_argument("--eli5-mode", action="store_true", default=None)
    parser.add_argument("--risk-per-trade-percent", type=float, default=None)
    parser.add_argument("--max-daily-loss-percent", type=float, default=None)
    parser.add_argument("--poll-interval-seconds", type=float, default=None)
    parser.add_argument("--run-once", action="store_true")
    parser.add_argument("--run-once-async", action="store_true")
    parser.add_argument("--terminal-dashboard", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    config = build_config(args)
    watcher = MarketWatcher(config=config)
    terminal = TerminalDashboard() if args.terminal_dashboard else None

    logger.info(
        "Starting MarketWatcher | symbols=%s timeframe=%s", config.symbols, config.timeframe
    )

    if args.run_once:
        snapshot = watcher.run_cycle()
        logger.info("Run-once snapshot generated with %s symbols", len(snapshot.get("symbols", [])))
        if terminal is not None:
            terminal.render(status=watcher.status(), snapshot=snapshot)
        print(json.dumps(snapshot, indent=2, default=str))
        return

    if args.run_once_async:
        import asyncio

        snapshot = asyncio.run(watcher.run_cycle_async())
        logger.info(
            "Async run-once snapshot generated with %s symbols", len(snapshot.get("symbols", []))
        )
        if terminal is not None:
            terminal.render(status=watcher.status(), snapshot=snapshot)
        print(json.dumps(snapshot, indent=2, default=str))
        return

    watcher.start()
    try:
        while True:
            status = watcher.status()
            logger.info(
                "Heartbeat cycle=%s lag=%ss error=%s",
                status.get("cycle_count"),
                status.get("seconds_since_heartbeat"),
                status.get("last_error"),
            )
            if terminal is not None:
                terminal.render(status=status, snapshot=status.get("latest_snapshot"))
            if watcher._stop_event.wait(config.poll_interval_seconds):  # noqa: SLF001
                break
    except KeyboardInterrupt:
        logger.info("Stopping MarketWatcher...")
    finally:
        watcher.stop()


if __name__ == "__main__":
    main()
