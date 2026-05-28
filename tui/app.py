"""Textual TUI for Alpaca_bot."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.content import Content
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    RichLog,
    Select,
    Static,
    TabbedContent,
    TabPane,
)
from tui.table_sort import (
    sort_position_tickers,
    sort_ticker_stats_items,
    sort_trades,
)
from tui.table_refresh import (
    analytics_signature,
    positions_signature,
    refresh_datatable_if_changed,
    trades_signature,
)
from tui.widgets import (
    analytics_row_cells,
    cash_display_value,
    dashboard_metrics_markup,
    format_activity_chart,
    format_money,
    format_pl_rich,
    format_swing_plain,
    server_time_label,
    tail_log_rich_lines,
    trade_row_cells,
)

from alpaca_client import get_account, get_balances
from analytics import (
    activity_bars,
    aggregate_by_ticker,
    load_state_snapshot,
    load_trades,
    portfolio_summary,
)
from config import Config, log_remote_disabled_once, setup_logging
from log_viewer import LOG_LEVEL_NAMES, format_log_line_rich
from env_config import read_margin, validate_margin, write_margin
from runner import BotRunner
from state import Status
from tui.log_tail import (
    LogTailState,
    read_initial_log_lines,
    read_new_log_lines,
    reset_log_tail,
)
PERIOD_OPTIONS = [
    ("Today", "today"),
    ("7 days", "7d"),
    ("30 days", "30d"),
    ("All", "all"),
]

LOG_FILTER_OPTIONS = [("All levels", "ALL")] + [(n, n) for n in LOG_LEVEL_NAMES]
LOG_BOT_LEVEL_OPTIONS = [(n, n) for n in LOG_LEVEL_NAMES]

ACTIVITY_BAR_LIMIT = 10
ALPACA_REFRESH_LABEL = "Refresh from Alpaca"
ALPACA_REFRESHING_LABEL = "Refreshing…"

TAB_LABELS = {
    "tab_dashboard": "Dashboard",
    "tab_positions": "Positions",
    "tab_trades": "Trades",
    "tab_analytics": "Analytics",
    "tab_logs": "Logs",
    "tab_settings": "Settings",
}


class AppHeader(Header):
    """App header without click-to-expand (avoids stacked title lines)."""

    def _on_click(self):
        pass


class QuitModal(ModalScreen[bool]):
    """Confirm stop bot and exit when the scheduler is running."""

    DEFAULT_CSS = """
    QuitModal {
        align: center middle;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("n", "cancel", "Cancel", show=False),
        Binding("y", "confirm_quit", "Quit", show=False),
    ]

    def __init__(self, *, paper: bool, last_loop: str = "—"):
        super().__init__()
        self._paper = paper
        self._last_loop = last_loop

    def compose(self) -> ComposeResult:
        mode = "PAPER" if self._paper else "LIVE"
        mode_rich = f"[green]{mode}[/]" if self._paper else f"[#d29922]{mode}[/]"
        with Container(id="quit_dialog"):
            yield Label("Quit while bot is running?", id="quit_title")
            yield Static(
                f"[dim]Mode:[/dim] {mode_rich}  "
                f"[dim]·  Last bot tick:[/dim] {self._last_loop}",
                id="quit_context",
            )
            yield Static(
                "The scheduler will stop and rebalancing will pause until you start the bot again.",
                id="quit_message",
            )
            with Horizontal(id="quit_actions"):
                yield Button("Cancel", id="quit_no", variant="primary")
                yield Button("Stop bot & quit", id="quit_yes", variant="error")

    def on_mount(self) -> None:
        self.query_one("#quit_no", Button).focus()

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_confirm_quit(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#quit_yes")
    def yes(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#quit_no")
    def no(self) -> None:
        self.dismiss(False)


class AlpacaApp(App):
    TITLE = "Alpaca Bot"
    CSS_PATH = Path(__file__).parent / "styles.tcss"

    BINDINGS = [
        Binding("t", "toggle_bot", "Bot", show=True),
        Binding("r", "refresh_all", "Refresh", show=True),
        Binding("q", "request_quit", "Quit", show=True),
        Binding("1", "tab_dashboard", "Dash", show=True),
        Binding("2", "tab_positions", "Pos", show=True),
        Binding("3", "tab_trades", "Trades", show=True),
        Binding("4", "tab_analytics", "Stats", show=True),
        Binding("5", "tab_logs", "Logs", show=True),
        Binding("6", "tab_settings", "Set", show=True),
    ]

    def __init__(self):
        super().__init__()
        self.config = Config()
        self.runner: Optional[BotRunner] = None
        self._state: Optional[dict] = None
        self._trades: list = []
        self._positions: Optional[list] = None
        self._account: Optional[dict] = None
        self._period = "all"
        self._can_start = False
        self._start_block_reason = ""
        self._log_view_filter = "INFO"
        self._log_bot_level = "INFO"
        self._log_tail = LogTailState()
        self._log_viewer_initialized = False
        self._analytics_sort_column: Optional[str] = None
        self._analytics_sort_reverse = False
        self._positions_sort_column: Optional[str] = None
        self._positions_sort_reverse = False
        self._trades_sort_column: Optional[str] = None
        self._trades_sort_reverse = False
        self._last_refresh_at: Optional[datetime] = None
        self._alpaca_refreshing = False
        self._log_strip_signature = ""
        self._positions_table_sig: Optional[str] = None
        self._trades_table_sig: Optional[str] = None
        self._analytics_table_sig: Optional[str] = None

    def format_title(self, title: str, sub_title: str) -> Content:
        """Show app name only; page names live on the tab bar."""
        return Content(self.TITLE)

    def compose(self) -> ComposeResult:
        yield AppHeader(show_clock=True)
        yield Static(id="status_bar")
        with TabbedContent(id="tabs"):
            with TabPane("Dashboard", id="tab_dashboard"):
                with Vertical():
                    yield Static(id="dashboard_metrics")
                    yield Static(id="dashboard_meta")
                    yield RichLog(
                        id="log_strip",
                        highlight=True,
                        markup=True,
                        wrap=True,
                        max_lines=5,
                    )
                    with Horizontal(id="dashboard_actions"):
                        yield Button("Start bot", id="btn_toggle", classes="primary")
            with TabPane("Positions", id="tab_positions"):
                yield DataTable(id="positions_table", zebra_stripes=True)
            with TabPane("Trades", id="tab_trades"):
                yield DataTable(id="trades_table", zebra_stripes=False)
            with TabPane("Analytics", id="tab_analytics"):
                with Vertical():
                    with Horizontal(id="analytics_toolbar"):
                        yield Select(
                            [(label, key) for label, key in PERIOD_OPTIONS],
                            id="period_select",
                            value="all",
                        )
                        yield Button(ALPACA_REFRESH_LABEL, id="btn_alpaca_refresh")
                    yield Static(id="analytics_summary")
                    yield DataTable(id="analytics_table", zebra_stripes=True)
                    yield Static(id="activity_bars")
            with TabPane("Logs", id="tab_logs"):
                with Vertical():
                    with Horizontal(id="logs_controls"):
                        with Vertical(classes="log_control_group"):
                            yield Label("Shown in viewer")
                            yield Select(
                                LOG_FILTER_OPTIONS,
                                id="log_view_filter",
                                value="INFO",
                            )
                        with Vertical(classes="log_control_group"):
                            yield Label("Written by bot")
                            yield Select(
                                LOG_BOT_LEVEL_OPTIONS,
                                id="log_bot_level",
                                value="INFO",
                            )
                    yield Static(id="log_file_label")
                    yield RichLog(
                        id="log_viewer",
                        highlight=True,
                        markup=True,
                        wrap=True,
                    )
            with TabPane("Settings", id="tab_settings"):
                with Vertical(id="settings_panel"):
                    yield Label(id="settings_status")
                    yield Label("Rebalance margin (0.02 – 0.15)")
                    yield Input(placeholder="0.05", id="margin_input")
                    yield Label(id="margin_state_label")
                    yield Button(
                        "Initialize state file",
                        id="btn_init_state",
                        variant="warning",
                    )
                    with Horizontal():
                        yield Button("Save margin", id="btn_save_margin", classes="primary")
                        yield Button("Start bot", id="btn_toggle_settings", classes="primary")
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = ""
        try:
            self.config.update()
        except ValueError as exc:
            self._can_start = False
            self._start_block_reason = str(exc)
        else:
            setup_logging(self.config, console=False, default_log_file="alpaca_bot.log")
            log_remote_disabled_once(self.config, logging.getLogger("alpaca_bot"))
            account = Status()
            self.runner = BotRunner(self.config, account)
            if Status.state_exists():
                account.load_state()
                self._can_start = True
            else:
                self._ensure_state(notify=False)

        self._init_tables()
        margin_input = self.query_one("#margin_input", Input)
        try:
            margin_input.value = f"{read_margin():g}"
        except (FileNotFoundError, ValueError, KeyError):
            margin_input.value = "0.05"
        self._log_bot_level = self.config.log_level
        try:
            bot_level = self.query_one("#log_bot_level", Select)
            bot_level.value = self._log_bot_level
        except Exception:
            pass
        self.set_interval(2, self.refresh_data)
        self.refresh_data(force_logs=True)

    def _ensure_state(self, notify: bool = True) -> None:
        """Create trading_state.json if missing and enable start."""
        if not self.runner:
            return
        if Status.state_exists():
            self.runner.account.load_state()
        else:
            self.runner.account = Status.bootstrap(self.config.margin)
        self._can_start = True
        self._start_block_reason = ""
        if notify:
            self.notify(
                f"Created {Status.STATE_FILE} — press Start to run the bot",
                severity="information",
            )

    def _init_tables(self):
        pos = self.query_one("#positions_table", DataTable)
        for label, key in (
            ("Symbol", "symbol"),
            ("Qty", "qty"),
            ("Price", "price"),
            ("Value", "value"),
            ("Swing %", "swing"),
            ("Limit", "limit"),
        ):
            pos.add_column(label, key=key)
        trades = self.query_one("#trades_table", DataTable)
        for label, key in (
            ("Time", "time"),
            ("Symbol", "symbol"),
            ("Side", "side"),
            ("Intent", "intent"),
            ("Status", "status"),
            ("Notional", "notional"),
            ("Filled", "filled"),
            ("Price", "price"),
        ):
            trades.add_column(label, key=key)
        ana = self.query_one("#analytics_table", DataTable)
        for label, key in (
            ("Symbol", "symbol"),
            ("Trades", "trades"),
            ("Filled", "filled"),
            ("Buy $", "buy"),
            ("Sell $", "sell"),
            ("Price", "price"),
            ("Trading P/L", "trading_pl"),
            ("Unreal. P/L", "unreal_pl"),
            ("Swing %", "swing"),
        ):
            ana.add_column(label, key=key)

    def _active_tab_id(self) -> str:
        return self.query_one(TabbedContent).active or ""

    def _sync_bot_toggle(self) -> None:
        running = bool(self.runner and self.runner.running)
        for toggle_id in ("btn_toggle", "btn_toggle_settings"):
            btn = self.query_one(f"#{toggle_id}", Button)
            if running:
                btn.label = "Stop bot"
                btn.remove_class("primary")
                btn.add_class("danger")
                btn.disabled = False
            else:
                btn.label = "Start bot"
                btn.remove_class("danger")
                btn.add_class("primary")
                btn.disabled = not self._can_start

    def _set_alpaca_refresh_ui(self, refreshing: bool) -> None:
        self._alpaca_refreshing = refreshing
        try:
            btn = self.query_one("#btn_alpaca_refresh", Button)
            btn.disabled = refreshing
            btn.label = ALPACA_REFRESHING_LABEL if refreshing else ALPACA_REFRESH_LABEL
        except Exception:
            pass

    def _update_status_bar(self):
        cfg = self.config
        running = self.runner and self.runner.running
        mode_class = "mode_paper" if cfg.paper else "mode_live"
        mode = "PAPER" if cfg.paper else "LIVE"
        market = (self._state or {}).get("market", "—")
        equity = (self._state or {}).get("equity", 0)
        bot_tick = "—"
        if running and self.runner and self.runner.last_loop_at:
            bot_tick = self.runner.last_loop_at.strftime("%H:%M:%S UTC")
        err = ""
        if self.runner and self.runner.last_error:
            err = f" | [red]Error: {self.runner.last_error[:60]}[/red]"
        run_cls = "status_running" if running else "status_stopped"
        run_label = "RUNNING" if running else "STOPPED"
        active = TAB_LABELS.get(self._active_tab_id(), "—")
        view = f"  |  [dim]View: {active}[/dim]"
        config_err = ""
        if not self._can_start and self._start_block_reason:
            config_err = f"  |  [red]{self._start_block_reason}[/red]"
        bar = self.query_one("#status_bar", Static)
        bar.update(
            f"[{mode_class}]{mode}[/]  |  Market: {market.upper()}  |  "
            f"[{run_cls}]{run_label}[/]  |  Equity: {format_money(equity)}  |  "
            f"Bot tick: {bot_tick}{view}{config_err}{err}"
        )

    def refresh_data(self, *, force_logs: bool = False) -> None:
        self._last_refresh_at = datetime.now(timezone.utc)
        self._state = load_state_snapshot()
        self._trades = load_trades(period=self._period)
        self._update_status_bar()
        self._refresh_dashboard()
        self._refresh_positions()
        self._refresh_trades()
        self._refresh_analytics()
        if force_logs or self._active_tab_id() == "tab_logs":
            self._refresh_logs(force_reload=force_logs)
        self._refresh_settings()
        self._sync_bot_toggle()

    def _refresh_dashboard(self):
        st = self._state or {}
        tickers = st.get("tickers", [])
        open_limits = sum(1 for t in tickers if t.get("limitTrade", {}).get("open"))
        best = max(tickers, key=lambda t: float(t.get("difference", 0)), default={})
        best_sym = best.get("ticker", "—")
        best_swing = float(best.get("difference", 0)) * 100
        margin_pct = float(st.get("margin", self.config.margin)) * 100
        cash, cash_estimated = cash_display_value(self._account, st)
        ui_updated = (
            self._last_refresh_at.strftime("%H:%M:%S")
            if self._last_refresh_at
            else "—"
        )
        meta_extra = (
            "  ·  [dim]Cash: refresh from Alpaca for live balance[/dim]"
            if cash_estimated
            else ""
        )

        swing_label = f"{best_sym} {best_swing:.1f}%"
        self.query_one("#dashboard_metrics", Static).update(
            dashboard_metrics_markup(
                equity=format_money(st.get("equity")),
                cash=cash,
                tickers=len(tickers),
                margin_pct=margin_pct,
                open_limits=open_limits,
                highest_swing=swing_label,
            )
        )
        self.query_one("#dashboard_meta", Static).update(
            f"Remote log: {'on' if self.config.remote_logging_enabled else 'off'}  ·  "
            f"State file: {server_time_label(st.get('serverTime', 0))}  ·  "
            f"UI updated: {ui_updated}{meta_extra}"
        )

        log_path = self.config.log_file or "alpaca_bot.log"
        strip = self.query_one("#log_strip", RichLog)
        lines = tail_log_rich_lines(log_path, lines=5, min_level="WARNING")
        signature = "\n".join(lines)
        if signature != self._log_strip_signature:
            self._log_strip_signature = signature
            strip.clear()
            for line in lines:
                strip.write(line)

    def _refresh_positions(self):
        table = self.query_one("#positions_table", DataTable)
        st = self._state or {}
        tickers = st.get("tickers", [])
        sig = positions_signature(
            tickers,
            sort_column=self._positions_sort_column,
            sort_reverse=self._positions_sort_reverse,
        )

        def populate() -> None:
            if not tickers:
                table.add_row(
                    "—",
                    "—",
                    "—",
                    "—",
                    "—",
                    "[dim]No positions — start bot or wait for rebalance[/dim]",
                )
                return
            if self._positions_sort_column:
                ordered = sort_position_tickers(
                    tickers,
                    self._positions_sort_column,
                    reverse=self._positions_sort_reverse,
                )
            else:
                ordered = sort_position_tickers(tickers, "swing", reverse=True)
            for t in ordered:
                sym = t.get("ticker", "")
                qty = float(t.get("volume", 0))
                price = float(t.get("price", 0))
                val = qty * price
                swing = float(t.get("difference", 0)) * 100
                lt = t.get("limitTrade", {})
                limit = "yes" if lt.get("open") else ""
                table.add_row(
                    sym,
                    f"{qty:.4g}",
                    format_money(price),
                    format_money(val),
                    format_swing_plain(swing),
                    limit,
                    key=sym,
                )

        self._positions_table_sig = refresh_datatable_if_changed(
            table, sig, self._positions_table_sig, populate
        )

    def _refresh_trades(self):
        table = self.query_one("#trades_table", DataTable)
        sig = trades_signature(
            self._trades,
            sort_column=self._trades_sort_column,
            sort_reverse=self._trades_sort_reverse,
        )

        def populate() -> None:
            if not self._trades:
                table.add_row(
                    "—",
                    "—",
                    "—",
                    "—",
                    "—",
                    "—",
                    "—",
                    "[dim]No trades in selected period[/dim]",
                )
                return
            rows = self._trades[-100:]
            if self._trades_sort_column:
                rows = sort_trades(
                    rows,
                    self._trades_sort_column,
                    reverse=self._trades_sort_reverse,
                )
            else:
                rows = list(reversed(rows))
            for row in rows:
                table.add_row(*trade_row_cells(row))

        self._trades_table_sig = refresh_datatable_if_changed(
            table, sig, self._trades_table_sig, populate
        )

    def _refresh_analytics(self):
        st = self._state or {}
        equity = float(st.get("equity", 0))
        if self._account:
            equity = float(self._account.get("equity", equity))
        stats = aggregate_by_ticker(
            self._trades,
            state_tickers=st.get("tickers"),
            positions=self._positions,
            account_equity=equity,
        )
        summary = portfolio_summary(
            self._trades,
            state=st,
            account=self._account,
            positions=self._positions,
            ticker_stats=stats,
        )
        sm = self.query_one("#analytics_summary", Static)
        sm.update(
            f"[b]Trades[/b] {summary.trade_count}  "
            f"[b]Filled[/b] {summary.filled_count} ({summary.fill_rate:.0%})  "
            f"[b]Equity[/b] {format_money(summary.equity)}  "
            f"[b]Avg Net $[/b] {format_money(summary.avg_balance_target)}  "
            f"[b]Cash[/b] {format_money(summary.cash)}  "
            f"[b]Trading P/L[/b] {format_pl_rich(summary.trading_pl)}  "
            f"[b]Unreal. P/L[/b] {format_pl_rich(summary.unrealized_pl)}  "
            f"[b]Active[/b] {summary.most_active_symbol or '—'}  "
            f"[b]Top swing[/b] {summary.largest_swing_symbol} "
            f"{summary.largest_swing_pct:.1f}%\n"
            f"[dim]Trading P/L = (sell $ − buy $) + net rebalance qty×price "
            "(rebalance fills only; excludes initial buy and liquidation). "
            "Click headers to sort.[/dim]"
        )
        table = self.query_one("#analytics_table", DataTable)
        sig = analytics_signature(
            stats,
            period=self._period,
            sort_column=self._analytics_sort_column,
            sort_reverse=self._analytics_sort_reverse,
        )

        def populate_table() -> None:
            if not stats:
                table.add_row(
                    "—",
                    "—",
                    "—",
                    "—",
                    "—",
                    "—",
                    "—",
                    "—",
                    "—",
                    "[dim]No ticker stats for this period[/dim]",
                    key="empty",
                )
                return
            col = self._analytics_sort_column or "symbol"
            ordered = sort_ticker_stats_items(
                stats,
                col,
                reverse=self._analytics_sort_reverse,
            )
            for sym, s in ordered:
                table.add_row(*analytics_row_cells(sym, s), key=sym)

        self._analytics_table_sig = refresh_datatable_if_changed(
            table, sig, self._analytics_table_sig, populate_table
        )
        bars = activity_bars(stats, width=ACTIVITY_BAR_LIMIT)
        chart_items = [(sym, cnt) for sym, _bar, cnt in bars]
        self.query_one("#activity_bars", Static).update(
            format_activity_chart(chart_items)
        )

    def _log_path(self) -> str:
        return self.config.log_file or "alpaca_bot.log"

    def _reset_log_viewer(self) -> None:
        path = self._log_path()
        self._log_tail = reset_log_tail(
            self._log_tail, path=path, min_level=self._log_view_filter
        )
        self._log_viewer_initialized = False

    def _refresh_logs(self, *, force_reload: bool = False) -> None:
        log_path = self._log_path()
        try:
            self.query_one("#log_file_label", Static).update(
                f"File: {log_path}  |  Shown: {self._log_view_filter}+  |  "
                f"Written: {self._log_bot_level}+  ·  append-only while on this tab"
            )
        except Exception:
            pass
        try:
            viewer = self.query_one("#log_viewer", RichLog)
        except Exception:
            return

        tail_key = (log_path, self._log_view_filter)
        if force_reload or self._log_tail.key() != tail_key:
            self._log_tail = reset_log_tail(
                self._log_tail, path=log_path, min_level=self._log_view_filter
            )
            viewer.clear()
            lines, self._log_tail = read_initial_log_lines(
                log_path,
                min_level=self._log_view_filter,
                max_lines=400,
            )
            self._log_viewer_initialized = True
            if not lines:
                viewer.write(
                    f"[dim]No log lines at {self._log_view_filter}+ in {log_path}. "
                    "Start the bot or lower the filter.[/dim]"
                )
                return
            for line in lines:
                viewer.write(format_log_line_rich(line))
            return

        if not self._log_viewer_initialized:
            self._refresh_logs(force_reload=True)
            return

        new_lines, self._log_tail = read_new_log_lines(self._log_tail)
        for line in new_lines:
            viewer.write(format_log_line_rich(line))

    def _apply_bot_log_level(self, level: str) -> None:
        self._log_bot_level = level.upper()
        self.config.log_level = self._log_bot_level
        setup_logging(
            self.config,
            console=False,
            default_log_file=self.config.log_file or "alpaca_bot.log",
        )
        self.notify(f"Bot logging set to {self._log_bot_level}", severity="information")

    @on(Select.Changed, "#log_view_filter")
    def log_view_filter_changed(self, event: Select.Changed) -> None:
        self._log_view_filter = str(event.value)
        self._reset_log_viewer()
        self._refresh_logs(force_reload=True)

    @on(Select.Changed, "#log_bot_level")
    def log_bot_level_changed(self, event: Select.Changed) -> None:
        self._apply_bot_log_level(str(event.value))

    def _refresh_settings(self):
        status = self.query_one("#settings_status", Static)
        if self._can_start:
            status.update("[green]Ready to start bot[/green]")
        else:
            status.update(f"[red]{self._start_block_reason}[/red]")
        st_margin = (self._state or {}).get("margin", "—")
        self.query_one("#margin_state_label", Label).update(
            f"State file margin: {st_margin}  |  .env margin: {self.config.margin:g}"
        )

    @on(Select.Changed, "#period_select")
    def period_changed(self, event: Select.Changed):
        self._period = str(event.value)
        self._trades = load_trades(period=self._period)
        self._refresh_analytics()

    @on(DataTable.HeaderSelected, "#analytics_table")
    def on_analytics_header_selected(self, event: DataTable.HeaderSelected) -> None:
        key = event.column_key
        if key is None:
            return
        if self._analytics_sort_column == key:
            self._analytics_sort_reverse = not self._analytics_sort_reverse
        else:
            self._analytics_sort_column = key
            self._analytics_sort_reverse = False
        self._refresh_analytics()

    @on(DataTable.HeaderSelected, "#positions_table")
    def on_positions_header_selected(self, event: DataTable.HeaderSelected) -> None:
        key = event.column_key
        if key is None:
            return
        if self._positions_sort_column == key:
            self._positions_sort_reverse = not self._positions_sort_reverse
        else:
            self._positions_sort_column = key
            self._positions_sort_reverse = False
        self._refresh_positions()

    @on(DataTable.HeaderSelected, "#trades_table")
    def on_trades_header_selected(self, event: DataTable.HeaderSelected) -> None:
        key = event.column_key
        if key is None:
            return
        if self._trades_sort_column == key:
            self._trades_sort_reverse = not self._trades_sort_reverse
        else:
            self._trades_sort_column = key
            self._trades_sort_reverse = False
        self._refresh_trades()

    @on(Button.Pressed)
    def button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid in ("btn_toggle", "btn_toggle_settings"):
            self.action_toggle_bot()
        elif bid == "btn_init_state":
            self._ensure_state(notify=True)
            self.refresh_data()

    @on(Button.Pressed, "#btn_save_margin")
    def btn_save_margin(self):
        raw = self.query_one("#margin_input", Input).value.strip()
        try:
            value = float(raw)
            validate_margin(value)
            write_margin(value)
            self.config.update()
            if self.runner:
                self.runner.reload_config()
            self.notify("Margin saved — active on next bot tick", severity="information")
            self.refresh_data()
        except (ValueError, FileNotFoundError) as exc:
            self.notify(str(exc), severity="error")

    @on(Button.Pressed, "#btn_alpaca_refresh")
    def btn_alpaca_refresh(self):
        if not self._alpaca_refreshing:
            self.refresh_alpaca()

    def action_start_bot(self):
        if not self.runner:
            return
        if not Status.state_exists():
            self._ensure_state(notify=True)
        if not self._can_start:
            self.notify(self._start_block_reason or "Cannot start", severity="error")
            return
        try:
            self.runner.start()
            self.notify("Bot started", severity="information")
        except FileNotFoundError as exc:
            self.notify(str(exc), severity="error")
        self.refresh_data()

    def action_stop_bot(self):
        if self.runner:
            self.runner.stop()
            self.notify("Bot stopped", severity="information")
        self.refresh_data()

    def action_toggle_bot(self):
        if self.runner and self.runner.running:
            self.action_stop_bot()
        else:
            self.action_start_bot()

    @work(thread=True)
    def refresh_alpaca(self):
        if not self.runner:
            return
        self.call_from_thread(self._set_alpaca_refresh_ui, True)
        try:
            session = self.runner.session
            config = self.config
            self._positions = get_balances(session, config)
            self._account = get_account(session, config)
            self.call_from_thread(self._after_alpaca_refresh)
        except Exception as exc:
            self.call_from_thread(self._alpaca_refresh_failed, str(exc))

    def _alpaca_refresh_failed(self, message: str) -> None:
        self._set_alpaca_refresh_ui(False)
        self.notify(message, severity="error")

    def _after_alpaca_refresh(self):
        self._set_alpaca_refresh_ui(False)
        self._refresh_dashboard()
        self._refresh_analytics()
        self.notify("Alpaca data refreshed", severity="information")

    def action_refresh_all(self):
        self._positions_table_sig = None
        self._trades_table_sig = None
        self._analytics_table_sig = None
        self.refresh_data(force_logs=True)
        if not self._alpaca_refreshing:
            self.refresh_alpaca()

    def action_tab_dashboard(self):
        self.query_one(TabbedContent).active = "tab_dashboard"

    def action_tab_positions(self):
        self.query_one(TabbedContent).active = "tab_positions"

    def action_tab_trades(self):
        self.query_one(TabbedContent).active = "tab_trades"

    def action_tab_analytics(self):
        self.query_one(TabbedContent).active = "tab_analytics"

    def action_tab_settings(self):
        self.query_one(TabbedContent).active = "tab_settings"

    def action_tab_logs(self):
        self.query_one(TabbedContent).active = "tab_logs"
        self._refresh_logs(force_reload=False)

    def action_request_quit(self):
        if self.runner and self.runner.running:
            loop = "—"
            if self.runner.last_loop_at:
                loop = self.runner.last_loop_at.strftime("%H:%M:%S UTC")
            self.push_screen(
                QuitModal(paper=self.config.paper, last_loop=loop),
                self._quit_result,
            )
        else:
            self.exit()

    def _quit_result(self, stop_and_quit: bool | None):
        if stop_and_quit:
            if self.runner:
                self.runner.stop()
            self.exit()

    def on_unmount(self):
        if self.runner and self.runner.running:
            self.runner.stop()
