from __future__ import annotations

from datetime import datetime
from typing import Any


class TerminalDashboard:
    """Terminal diagnostics renderer with optional rich support."""

    def __init__(self) -> None:
        self._rich_available = False
        self._console = None
        self._table_cls = None
        self._panel_cls = None
        try:
            from rich.console import Console
            from rich.panel import Panel
            from rich.table import Table

            self._console = Console()
            self._table_cls = Table
            self._panel_cls = Panel
            self._rich_available = True
        except Exception:
            self._rich_available = False

    def render(self, *, status: dict[str, Any], snapshot: dict[str, Any] | None) -> None:
        if self._rich_available:
            self._render_rich(status=status, snapshot=snapshot)
            return
        self._render_plain(status=status, snapshot=snapshot)

    def _render_plain(self, *, status: dict[str, Any], snapshot: dict[str, Any] | None) -> None:
        ts = datetime.utcnow().isoformat()
        line = (
            f"[{ts}] cycle={status.get('cycle_count')} "
            f"lag={status.get('seconds_since_heartbeat')}s "
            f"running={status.get('running')} "
            f"error={status.get('last_error') or 'none'}"
        )
        print(line)
        if snapshot:
            rows = snapshot.get("symbols", [])
            if isinstance(rows, list) and rows:
                top = rows[0]
                if isinstance(top, dict):
                    print(
                        "  top symbol="
                        f"{top.get('symbol')} signal={top.get('signal')} "
                        f"regime={top.get('regime')} conf={top.get('confidence')}"
                    )

    def _render_rich(self, *, status: dict[str, Any], snapshot: dict[str, Any] | None) -> None:
        assert self._console is not None
        assert self._table_cls is not None
        assert self._panel_cls is not None

        table = self._table_cls(title="Aletheia Market Watcher")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")
        table.add_row("Running", str(status.get("running")))
        table.add_row("Cycle", str(status.get("cycle_count")))
        table.add_row("Lag (s)", str(status.get("seconds_since_heartbeat")))
        table.add_row("Last Error", str(status.get("last_error") or "none"))

        if snapshot and isinstance(snapshot.get("symbols"), list):
            rows = snapshot["symbols"]
            for row in rows[:5]:
                if not isinstance(row, dict):
                    continue
                table.add_row(
                    str(row.get("symbol", "?")),
                    (
                        f"sig={row.get('signal')} | reg={row.get('regime')} | "
                        f"vol={row.get('volatility_regime')} | conf={row.get('confidence', 0):.1f}"
                    ),
                )

        panel = self._panel_cls(table, title="Live Market Watcher", border_style="bright_blue")
        self._console.print(panel)
