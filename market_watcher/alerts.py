from __future__ import annotations

from typing import Any


class AlertEngine:
    """Generate operational alerts from market watcher diagnostics."""

    def evaluate_symbol(self, diagnostics: dict[str, Any]) -> list[dict[str, str]]:
        alerts: list[dict[str, str]] = []
        symbol = str(diagnostics.get("symbol", "UNKNOWN"))
        anomaly = float(diagnostics.get("anomaly_score", 0.0))
        volatility_regime = str(diagnostics.get("volatility_regime", "unknown"))
        sentiment = float(diagnostics.get("sentiment_score", 0.0))

        if anomaly >= 2.5:
            alerts.append(
                {
                    "symbol": symbol,
                    "severity": "high",
                    "type": "price_anomaly",
                    "message": f"Anomaly score elevated ({anomaly:.2f})",
                }
            )

        if volatility_regime == "high-vol":
            alerts.append(
                {
                    "symbol": symbol,
                    "severity": "medium",
                    "type": "volatility_regime",
                    "message": "High-vol regime active",
                }
            )

        if abs(sentiment) >= 0.8:
            alerts.append(
                {
                    "symbol": symbol,
                    "severity": "medium",
                    "type": "sentiment_extreme",
                    "message": "External sentiment is at an extreme",
                }
            )
        return alerts
