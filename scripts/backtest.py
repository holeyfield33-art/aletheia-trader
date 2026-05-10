from __future__ import annotations

import json

from agents.forex_agent import ForexAgent
from agents.options_agent import OptionsAgent
from brokers.simulator import PaperSimulator


def main() -> None:
    forex = ForexAgent()
    options = OptionsAgent()
    sim = PaperSimulator()

    fx_res = forex.run("EUR/USD")
    opt_res = options.run("SPY")

    if fx_res.get("signal") in {"BUY", "SELL"}:
        sim.submit_order("EUR/USD", fx_res["signal"], qty=1.0, price=1.0, approved=False)

    if opt_res.get("signal") in {"CALL_BUY", "PUT_BUY"}:
        sim.submit_order("SPY", opt_res["signal"], qty=1.0, price=1.0, approved=False)

    summary = {
        "forex": fx_res,
        "options": opt_res,
        "daily_pnl": sim.get_daily_pnl(),
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
