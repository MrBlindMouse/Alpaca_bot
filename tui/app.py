"""Textual TUI for Alpaca_bot."""

from __future__ import annotations

import logging
import time
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
    Checkbox,
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
from tui.ui_refresh import update_text_if_changed
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
from backtest.config import load_backtest_config
from backtest.service import (
    apply_ui_overrides,
    cache_status_dict,
    default_config,
    execute_comparisons,
    execute_fetch,
    list_cached_datasets,
    load_comparison_rows,
    load_equity_preview,
    load_trades_preview,
    summarize_decisions,
)
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
ALPACA_REFRESHING_LABEL = "Refreshing..."
REFRESH_INTERVAL_FAST = 2.0
REFRESH_INTERVAL_HEAVY_IDLE = 5.0

TAB_LABELS = {
    "tab_dashboard": "Dashboard",
    "tab_positions": "Positions",
    "tab_trades": "Trades",
    "tab_analytics": "Analytics",
    "tab_logs": "Logs",
    "tab_backtest": "Backtest",
    "tab_settings": "Settings",
}

BT_TIMEFRAME_OPTIONS = [
    ("5 Min", "5Min"),
    ("1 Min", "1Min"),
    ("15 Min", "15Min"),
    ("1 Hour", "1Hour"),
    ("1 Day", "1Day"),
]
BT_FEED_OPTIONS = [("IEX", "iex"), ("SIP", "sip")]
BT_ADJUSTMENT_OPTIONS = [
    ("All", "all"),
    ("Raw", "raw"),
    ("Split", "split"),
    ("Dividend", "dividend"),
]


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
        Binding("6", "tab_logs", "Logs", show=False),
        Binding("7", "tab_backtest", "BT", show=True),
        Binding("8", "tab_settings", "Set", show=True),
    ]

    def __init__(self, config: Optional[Config] = None):
        super().__init__()
        self.config = config if config is not None else Config()
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
        self._bt_cfg = default_config()
        self._backtest_busy = False
        self._bt_primary_margin: Optional[float] = None
        self._bt_comparison_sig: Optional[str] = None
        self._bt_equity_sig: Optional[str] = None
        self._bt_trades_sig: Optional[str] = None
        self._bt_dataset_options_sig: Optional[str] = None
        self._status_bar_content: Optional[str] = None
        self._dashboard_metrics_content: Optional[str] = None
        self._dashboard_meta_content: Optional[str] = None
        self._dashboard_meta_data_sig: Optional[str] = None
        self._dashboard_meta_clock: str = ""
        self._analytics_summary_content: Optional[str] = None
        self._activity_bars_content: Optional[str] = None
        self._settings_status_content: Optional[str] = None
        self._margin_state_content: Optional[str] = None
        self._backtest_cache_content: Optional[str] = None
        self._log_file_label_content: Optional[str] = None
        self._toggle_ui_state: Optional[tuple[bool, bool]] = None
        self._last_heavy_refresh_at: float = 0.0

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
                        yield Button("Start bot", id="btn_toggle", variant="success")
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
            with TabPane("Backtest", id="tab_backtest"):
                with Vertical(id="backtest_panel"):
                    with Horizontal(id="backtest_toolbar_row1"):
                        with Vertical(classes="bt_field"):
                            yield Label("Start")
                            yield Input(placeholder="2025-01-01", id="bt_start")
                        with Vertical(classes="bt_field"):
                            yield Label("End")
                            yield Input(placeholder="2025-12-31", id="bt_end")
                        with Vertical(classes="bt_field"):
                            yield Label("Initial cash")
                            yield Input(placeholder="100000", id="bt_cash")
                        with Vertical(classes="bt_field"):
                            yield Label("Margins")
                            yield Input(placeholder="0.03,0.05,0.10", id="bt_margins")
                    with Horizontal(id="backtest_toolbar_row2"):
                        with Vertical(classes="bt_field"):
                            yield Label("Dataset")
                            yield Select([], id="bt_dataset", prompt="Select cached dataset")
                        with Vertical(classes="bt_field"):
                            yield Label("Timeframe")
                            yield Select(BT_TIMEFRAME_OPTIONS, id="bt_timeframe", value="5Min")
                        with Vertical(classes="bt_field"):
                            yield Label("Feed")
                            yield Select(BT_FEED_OPTIONS, id="bt_feed", value="iex")
                        with Vertical(classes="bt_field"):
                            yield Label("Adjustment")
                            yield Select(BT_ADJUSTMENT_OPTIONS, id="bt_adjustment", value="all")
                        with Vertical(classes="bt_field"):
                            yield Label("Detail margin")
                            yield Select([], id="bt_primary_margin", prompt="After run")
                    with Horizontal(id="backtest_actions"):
                        yield Button("Fetch bars", id="btn_bt_fetch", variant="primary")
                        yield Button("Run comparison", id="btn_bt_run", variant="primary")
                        yield Button("Refresh status", id="btn_bt_status")
                        yield Checkbox("Force refetch", id="bt_force")
                    yield Static(id="backtest_cache_status")
                    yield Static(id="backtest_results")
                    yield DataTable(id="backtest_compare_table", zebra_stripes=True)
                    yield RichLog(
                        id="backtest_log",
                        highlight=True,
                        markup=True,
                        wrap=True,
                        max_lines=8,
                    )
                    yield Static("[dim]Detail for selected rebalancer margin[/dim]")
                    yield DataTable(id="backtest_equity_table", zebra_stripes=True)
                    yield DataTable(id="backtest_trades_table", zebra_stripes=False)
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
                        yield Button("Save margin", id="btn_save_margin", variant="primary")
                        yield Button("Start bot", id="btn_toggle_settings", variant="success")
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
        self._init_backtest_form()
        self.set_interval(2, self.refresh_data)
        self.refresh_data(force_logs=True, force_heavy=True)

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
        self._toggle_ui_state = None
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
        compare = self.query_one("#backtest_compare_table", DataTable)
        for label, key in (
            ("Strategy", "strategy"),
            ("Margin", "margin"),
            ("Return %", "return"),
            ("Max DD %", "dd"),
            ("Trades", "trades"),
            ("End equity", "equity"),
        ):
            compare.add_column(label, key=key)
        eq = self.query_one("#backtest_equity_table", DataTable)
        for label, key in (
            ("Time", "ts"),
            ("Equity", "equity"),
            ("Cash", "cash"),
            ("Drawdown %", "dd"),
        ):
            eq.add_column(label, key=key)
        bt_trades = self.query_one("#backtest_trades_table", DataTable)
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
            bt_trades.add_column(label, key=key)

    def _init_backtest_form(self) -> None:
        cfg = load_backtest_config()
        self._bt_cfg = cfg
        try:
            self.query_one("#bt_start", Input).value = cfg.start
            self.query_one("#bt_end", Input).value = cfg.end
            self.query_one("#bt_cash", Input).value = f"{cfg.initial_cash:g}"
            margins = cfg.margins or f"{read_margin():g}"
            self.query_one("#bt_margins", Input).value = margins
            self.query_one("#bt_timeframe", Select).value = cfg.timeframe
            self.query_one("#bt_feed", Select).value = cfg.feed
            self.query_one("#bt_adjustment", Select).value = cfg.adjustment
        except Exception:
            pass
        self._refresh_backtest_status()

    def _active_tab_id(self) -> str:
        return self.query_one(TabbedContent).active or ""

    def _should_run_heavy_refresh(self, *, force: bool = False) -> bool:
        if force:
            return True
        if self.runner and self.runner.running:
            return True
        if self._active_tab_id() in ("tab_logs", "tab_backtest"):
            return True
        return (time.monotonic() - self._last_heavy_refresh_at) >= REFRESH_INTERVAL_HEAVY_IDLE

    def _refresh_active_tab(self, *, force: bool = False) -> None:
        """Refresh widgets for the currently visible tab."""
        tab = self._active_tab_id()
        if tab == "tab_dashboard":
            self._refresh_dashboard()
        elif tab == "tab_positions":
            self._refresh_positions()
        elif tab == "tab_trades":
            self._refresh_trades()
        elif tab == "tab_analytics":
            self._refresh_analytics()
        elif tab == "tab_backtest":
            self._refresh_backtest_status()
        elif tab == "tab_settings":
            self._refresh_settings()
        elif tab == "tab_logs":
            self._refresh_logs(force_reload=force)

    @on(TabbedContent.TabActivated, "#tabs")
    def on_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        self._refresh_active_tab(force=True)

    def _sync_bot_toggle(self) -> None:
        running = bool(self.runner and self.runner.running)
        disabled = not self._can_start if not running else False
        state = (running, disabled)
        if state == self._toggle_ui_state:
            return
        self._toggle_ui_state = state
        for toggle_id in ("btn_toggle", "btn_toggle_settings"):
            btn = self.query_one(f"#{toggle_id}", Button)
            if running:
                btn.label = "Stop bot"
                btn.variant = "error"
                btn.disabled = False
            else:
                btn.label = "Start bot"
                btn.variant = "success"
                btn.disabled = disabled

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
        content = (
            f"[{mode_class}]{mode}[/]  |  Market: {market.upper()}  |  "
            f"[{run_cls}]{run_label}[/]  |  Equity: {format_money(equity)}  |  "
            f"Bot tick: {bot_tick}{view}{config_err}{err}"
        )
        bar = self.query_one("#status_bar", Static)
        self._status_bar_content = update_text_if_changed(
            bar, content, self._status_bar_content
        )

    def refresh_data(self, *, force_logs: bool = False, force_heavy: bool = False) -> None:
        self._last_refresh_at = datetime.now(timezone.utc)
        self._state = load_state_snapshot()
        self._trades = load_trades(period=self._period)
        self._update_status_bar()
        self._sync_bot_toggle()

        heavy = self._should_run_heavy_refresh(force=force_heavy)
        if heavy:
            self._last_heavy_refresh_at = time.monotonic()
            self._refresh_active_tab(force=force_logs)
        elif force_logs and self._active_tab_id() == "tab_logs":
            self._refresh_logs(force_reload=force_logs)

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
        metrics_content = dashboard_metrics_markup(
            equity=format_money(st.get("equity")),
            cash=cash,
            tickers=len(tickers),
            margin_pct=margin_pct,
            open_limits=open_limits,
            highest_swing=swing_label,
        )
        metrics_widget = self.query_one("#dashboard_metrics", Static)
        self._dashboard_metrics_content = update_text_if_changed(
            metrics_widget, metrics_content, self._dashboard_metrics_content
        )

        meta_data_sig = (
            f"{self.config.remote_logging_enabled}|"
            f"{st.get('serverTime', 0)}|{cash_estimated}"
        )
        clock_minute = ui_updated[:5] if ui_updated != "—" else ""
        meta_changed = meta_data_sig != self._dashboard_meta_data_sig
        clock_changed = clock_minute != self._dashboard_meta_clock
        if meta_changed or clock_changed:
            self._dashboard_meta_data_sig = meta_data_sig
            self._dashboard_meta_clock = clock_minute
            meta_content = (
                f"Remote log: {'on' if self.config.remote_logging_enabled else 'off'}  ·  "
                f"State file: {server_time_label(st.get('serverTime', 0))}  ·  "
                f"UI updated: {ui_updated}{meta_extra}"
            )
            meta_widget = self.query_one("#dashboard_meta", Static)
            self._dashboard_meta_content = update_text_if_changed(
                meta_widget, meta_content, self._dashboard_meta_content
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
        summary_content = (
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
        sm = self.query_one("#analytics_summary", Static)
        self._analytics_summary_content = update_text_if_changed(
            sm, summary_content, self._analytics_summary_content
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
        chart_content = format_activity_chart(chart_items)
        activity_widget = self.query_one("#activity_bars", Static)
        self._activity_bars_content = update_text_if_changed(
            activity_widget, chart_content, self._activity_bars_content
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
            label_content = (
                f"File: {log_path}  |  Shown: {self._log_view_filter}+  |  "
                f"Written: {self._log_bot_level}+  ·  append-only while on this tab"
            )
            label_widget = self.query_one("#log_file_label", Static)
            self._log_file_label_content = update_text_if_changed(
                label_widget, label_content, self._log_file_label_content
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
        status = self.query_one("#settings_status", Label)
        status_content = (
            "[green]Ready to start bot[/green]"
            if self._can_start
            else f"[red]{self._start_block_reason}[/red]"
        )
        self._settings_status_content = update_text_if_changed(
            status, status_content, self._settings_status_content
        )
        st_margin = (self._state or {}).get("margin", "—")
        margin_content = (
            f"State file margin: {st_margin}  |  .env margin: {self.config.margin:g}"
        )
        margin_label = self.query_one("#margin_state_label", Label)
        self._margin_state_content = update_text_if_changed(
            margin_label, margin_content, self._margin_state_content
        )

    @on(Select.Changed, "#period_select")
    def period_changed(self, event: Select.Changed):
        self._period = str(event.value)
        self._trades = load_trades(period=self._period)
        self._trades_table_sig = None
        self._refresh_trades()
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
        # Toggle/init only; other buttons use dedicated handlers below.
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

    def _set_backtest_busy(self, busy: bool) -> None:
        self._backtest_busy = busy
        for widget_id in ("btn_bt_fetch", "btn_bt_run", "btn_bt_status"):
            try:
                self.query_one(f"#{widget_id}", Button).disabled = busy
            except Exception:
                pass

    def _backtest_log_append(self, line: str) -> None:
        try:
            viewer = self.query_one("#backtest_log", RichLog)
            viewer.write(line)
        except Exception:
            pass

    def _read_backtest_form(self):
        start = self.query_one("#bt_start", Input).value.strip()
        end = self.query_one("#bt_end", Input).value.strip()
        cash = float(self.query_one("#bt_cash", Input).value.strip())
        margins = self.query_one("#bt_margins", Input).value.strip()
        timeframe = str(self.query_one("#bt_timeframe", Select).value or "5Min")
        feed = str(self.query_one("#bt_feed", Select).value or "iex")
        adjustment = str(self.query_one("#bt_adjustment", Select).value or "all")
        cfg, margin_list = apply_ui_overrides(
            self._bt_cfg,
            start=start,
            end=end,
            cash=cash,
            timeframe=timeframe,
            feed=feed,
            adjustment=adjustment,
            margins=margins,
        )
        self._bt_cfg = cfg
        return cfg, margin_list

    def _refresh_backtest_status(self) -> None:
        cache_widget = self.query_one("#backtest_cache_status", Static)
        try:
            st = cache_status_dict(self._bt_cfg)
            datasets = list_cached_datasets(self._bt_cfg)
            self._refresh_backtest_dataset_select(datasets)
            cache_content = (
                f"[b]Cache[/b] {st['db']}  "
                f"[b]Bars[/b] {st.get('bar_count', 0)}  "
                f"[b]Symbols[/b] {st.get('symbol_count', 0)}  "
                f"[b]Ranges[/b] {st.get('fetch_ranges', 0)}  "
                f"[b]Datasets[/b] {len(datasets)}\n"
                f"[dim]{st.get('min_ts') or '—'} .. {st.get('max_ts') or '—'}  "
                "| 5Min steps vs live 1Min bot  |  cap weights are current NDX (static)[/dim]"
            )
        except Exception as exc:
            cache_content = f"[red]Cache error: {exc}[/red]"
        self._backtest_cache_content = update_text_if_changed(
            cache_widget, cache_content, self._backtest_cache_content
        )

    def _refresh_backtest_dataset_select(self, datasets: list[dict]) -> None:
        select = self.query_one("#bt_dataset", Select)
        options = [(row["label"], row["label"]) for row in datasets]
        sig = str(options)
        if sig == self._bt_dataset_options_sig:
            return
        self._bt_dataset_options_sig = sig
        select.set_options(options)
        if options:
            if str(select.value) not in {value for _, value in options}:
                select.value = Select.BLANK

    @on(Select.Changed, "#bt_dataset")
    def bt_dataset_changed(self, event: Select.Changed) -> None:
        selected = str(event.value or "").strip()
        if not selected:
            return
        for row in list_cached_datasets(self._bt_cfg):
            if row["label"] != selected:
                continue
            self.query_one("#bt_start", Input).value = row["start"]
            self.query_one("#bt_end", Input).value = row["end"]
            self.query_one("#bt_timeframe", Select).value = row["timeframe"]
            self._backtest_log_append(
                f"Dataset selected: {row['start']} .. {row['end']} ({row['timeframe']})"
            )
            break

    def _refresh_backtest_compare_table(self, results=None) -> None:
        table = self.query_one("#backtest_compare_table", DataTable)
        if results is None:
            rows = load_comparison_rows(self._bt_cfg.comparison_file)
        else:
            rows = [
                (
                    r.strategy,
                    r.margin_label(),
                    f"{r.total_return_pct:.2f}",
                    f"{r.max_drawdown_pct:.2f}",
                    str(r.trade_count),
                    format_money(r.end_equity),
                )
                for r in results
            ]
        sig = str(rows)
        if sig == self._bt_comparison_sig:
            return
        self._bt_comparison_sig = sig
        table.clear()
        if not rows:
            table.add_row("—", "—", "—", "—", "—", "[dim]Run comparison to populate[/dim]")
            return
        for idx, row in enumerate(rows):
            table.add_row(*row, key=str(idx))

    def _update_primary_margin_select(self, margins: list) -> None:
        select = self.query_one("#bt_primary_margin", Select)
        options = [(f"{m:g}", str(m)) for m in margins]
        if not options:
            return
        select.set_options(options)
        if self._bt_primary_margin is not None:
            select.value = str(self._bt_primary_margin)
        else:
            select.value = options[0][1]
            self._bt_primary_margin = margins[0]

    def _paths_for_margin(self, margin: float) -> tuple[str, str]:
        import os

        _, margin_list = self._read_backtest_form()
        primary = margin_list[0] if margin_list else margin
        equity_path = self._bt_cfg.equity_file
        trades_path = self._bt_cfg.trades_file
        if margin != primary:
            base_eq, ext_eq = os.path.splitext(self._bt_cfg.equity_file)
            base_tr, ext_tr = os.path.splitext(self._bt_cfg.trades_file)
            equity_path = f"{base_eq}_m{margin:g}{ext_eq or '.csv'}"
            trades_path = f"{base_tr}_m{margin:g}{ext_tr or '.jsonl'}"
        return equity_path, trades_path

    def _refresh_backtest_detail_tables(self) -> None:
        margin_val = self.query_one("#bt_primary_margin", Select).value
        if margin_val is None:
            return
        try:
            margin = float(str(margin_val))
        except ValueError:
            return
        self._bt_primary_margin = margin
        equity_path, trades_path = self._paths_for_margin(margin)

        eq_table = self.query_one("#backtest_equity_table", DataTable)
        eq_rows = load_equity_preview(equity_path, limit=20)
        eq_sig = str((equity_path, eq_rows))
        if eq_sig != self._bt_equity_sig:
            self._bt_equity_sig = eq_sig
            eq_table.clear()
            if not eq_rows:
                eq_table.add_row("—", "—", "—", "—")
            else:
                for idx, row in enumerate(eq_rows):
                    eq_table.add_row(*row, key=f"eq{idx}")

        tr_table = self.query_one("#backtest_trades_table", DataTable)
        trade_rows = load_trades_preview(trades_path, limit=50)
        tr_sig = str((trades_path, len(trade_rows)))
        if tr_sig != self._bt_trades_sig:
            self._bt_trades_sig = tr_sig
            tr_table.clear()
            if not trade_rows:
                tr_table.add_row("—", "—", "—", "—", "—", "—", "—", "—")
            else:
                for idx, row in enumerate(trade_rows):
                    tr_table.add_row(*trade_row_cells(row), key=f"tr{idx}")

    @on(Select.Changed, "#bt_primary_margin")
    def bt_primary_margin_changed(self) -> None:
        self._refresh_backtest_detail_tables()

    @on(Button.Pressed, "#btn_bt_status")
    def btn_bt_status(self) -> None:
        if not self._backtest_busy:
            self._refresh_backtest_status()

    @on(Button.Pressed, "#btn_bt_fetch")
    def btn_bt_fetch(self) -> None:
        if not self._backtest_busy:
            self.backtest_fetch_worker()

    @on(Button.Pressed, "#btn_bt_run")
    def btn_bt_run(self) -> None:
        if not self._backtest_busy:
            self.backtest_run_worker()

    @work(thread=True)
    def backtest_fetch_worker(self) -> None:
        self.call_from_thread(self._set_backtest_busy, True)
        try:
            cfg, _margins = self.call_from_thread(lambda: self._read_backtest_form())
            if not cfg.start or not cfg.end:
                raise ValueError("Start and end dates are required")
            force = self.call_from_thread(
                lambda: self.query_one("#bt_force", Checkbox).value
            )

            def progress(line: str) -> None:
                self.call_from_thread(self._backtest_log_append, line)

            self.call_from_thread(self._backtest_log_append, "Fetching bars...")
            result = execute_fetch(
                cfg,
                cfg.start,
                cfg.end,
                force=force,
                on_progress=progress,
            )
            msg = (
                f"Fetch done: {result['symbols']} symbols, "
                f"{result['bars_inserted']} bars inserted"
            )
            self.call_from_thread(self._backtest_log_append, msg)
            self.call_from_thread(
                self._backtest_log_append, f"Activity log: {cfg.log_file}"
            )
            self.call_from_thread(self._refresh_backtest_status)
            self.call_from_thread(
                self.notify, msg, severity="information"
            )
        except Exception as exc:
            self.call_from_thread(self._backtest_log_append, f"[red]Fetch failed: {exc}[/red]")
            self.call_from_thread(self.notify, str(exc), severity="error")
        finally:
            self.call_from_thread(self._set_backtest_busy, False)

    @work(thread=True)
    def backtest_run_worker(self) -> None:
        self.call_from_thread(self._set_backtest_busy, True)
        try:
            cfg, margins = self.call_from_thread(lambda: self._read_backtest_form())
            if not cfg.start or not cfg.end:
                raise ValueError("Start and end dates are required")
            if not margins:
                raise ValueError("At least one margin is required")

            self.call_from_thread(self._backtest_log_append, "Running comparisons...")
            results = execute_comparisons(
                cfg,
                cfg.start,
                cfg.end,
                cfg.initial_cash,
                margins,
                primary_margin=margins[0],
                reset_trades=True,
            )
            self._bt_primary_margin = margins[0]

            def after_run() -> None:
                self._update_primary_margin_select(margins)
                self._refresh_backtest_compare_table(results)
                best = max(results, key=lambda r: r.total_return_pct)
                diag = summarize_decisions(cfg.decisions_file)
                skipped = diag.get("skipped", {})
                skip_line = ", ".join(
                    f"{k}:{v}" for k, v in sorted(skipped.items())
                ) or "none"
                self.query_one("#backtest_results", Static).update(
                    f"[b]Last run[/b]  "
                    f"Best return: {best.strategy} ({best.margin_label()}) "
                    f"{best.total_return_pct:.2f}%  "
                    f"[dim]→ {cfg.comparison_file}[/dim]\n"
                    f"[dim]Log: {cfg.log_file}  |  "
                    f"Diagnostics: {cfg.decisions_file} | "
                    f"events={diag['events']} ticks={diag['tick_summaries']} "
                    f"attempts={diag['attempts']} fills={diag['fills']} "
                    f"fails={diag['failures']} | skipped: {skip_line}[/dim]"
                )
                self._backtest_log_append(
                    f"Activity log: {cfg.log_file}"
                )
                self._backtest_log_append(
                    "Diagnostics written: "
                    f"{cfg.decisions_file} | events={diag['events']} "
                    f"ticks={diag['tick_summaries']} attempts={diag['attempts']} "
                    f"fills={diag['fills']} fails={diag['failures']}"
                )
                self._refresh_backtest_detail_tables()

            self.call_from_thread(after_run)
            self.call_from_thread(
                self.notify, "Comparison complete", severity="information"
            )
        except Exception as exc:
            self.call_from_thread(
                self._backtest_log_append, f"[red]Run failed: {exc}[/red]"
            )
            self.call_from_thread(self.notify, str(exc), severity="error")
        finally:
            self.call_from_thread(self._set_backtest_busy, False)

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
        self.refresh_data(force_heavy=True)

    def action_stop_bot(self):
        if self.runner:
            self.runner.stop()
            self.notify("Bot stopped", severity="information")
        self.refresh_data(force_heavy=True)

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
            positions = get_balances(session, config)
            if positions is None:
                raise RuntimeError("Could not load positions from Alpaca")
            account = get_account(session, config)
            self._positions = positions
            self._account = account
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
        self._positions_table_sig = None
        self._refresh_positions()
        self.notify("Alpaca data refreshed", severity="information")

    def action_refresh_all(self):
        self._positions_table_sig = None
        self._trades_table_sig = None
        self._analytics_table_sig = None
        self.refresh_data(force_logs=True, force_heavy=True)
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

    def action_tab_backtest(self):
        self.query_one(TabbedContent).active = "tab_backtest"

    def action_tab_logs(self):
        self.query_one(TabbedContent).active = "tab_logs"

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
