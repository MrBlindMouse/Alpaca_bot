"""SQLite cache for historical bars."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Dict, Iterator, List, Optional, Tuple

from backtest.config import ensure_parent_dir

BarRow = Tuple[str, str, float, float, float, float, float, Optional[float]]
DEFAULT_TIMEFRAME = "5Min"


def bar_price(vwap: Optional[float], close: float) -> float:
    if vwap is not None and vwap > 0:
        return vwap
    return close


class BarCache:
    def __init__(self, path: str):
        self.path = path
        ensure_parent_dir(path)
        self._init_schema()

    @contextmanager
    def _connect(self, *, readonly: bool = False) -> Iterator[sqlite3.Connection]:
        if readonly:
            conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        else:
            conn = sqlite3.connect(self.path)
        try:
            if not readonly:
                conn.execute("PRAGMA journal_mode=WAL")
            yield conn
            if not readonly:
                conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS bars (
                  symbol TEXT NOT NULL,
                  ts TEXT NOT NULL,
                  timeframe TEXT NOT NULL DEFAULT '5Min',
                  open REAL NOT NULL,
                  high REAL NOT NULL,
                  low REAL NOT NULL,
                  close REAL NOT NULL,
                  volume REAL NOT NULL,
                  vwap REAL,
                  PRIMARY KEY (symbol, ts, timeframe)
                );
                CREATE INDEX IF NOT EXISTS idx_bars_ts ON bars(ts);
                CREATE INDEX IF NOT EXISTS idx_bars_tf_ts ON bars(timeframe, ts);

                CREATE TABLE IF NOT EXISTS fetch_log (
                  symbol TEXT NOT NULL,
                  range_start TEXT NOT NULL,
                  range_end TEXT NOT NULL,
                  timeframe TEXT NOT NULL DEFAULT '',
                  bar_count INTEGER NOT NULL,
                  fetched_at TEXT NOT NULL,
                  PRIMARY KEY (symbol, range_start, range_end, timeframe)
                );
                """
            )
            self._migrate_bars_timeframe(conn)
            self._migrate_fetch_log_pk(conn)

    def _migrate_bars_timeframe(self, conn: sqlite3.Connection) -> None:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(bars)").fetchall()}
        if "timeframe" in cols:
            return
        conn.executescript(
            """
            CREATE TABLE bars_migrated (
              symbol TEXT NOT NULL,
              ts TEXT NOT NULL,
              timeframe TEXT NOT NULL DEFAULT '5Min',
              open REAL NOT NULL,
              high REAL NOT NULL,
              low REAL NOT NULL,
              close REAL NOT NULL,
              volume REAL NOT NULL,
              vwap REAL,
              PRIMARY KEY (symbol, ts, timeframe)
            );
            INSERT INTO bars_migrated
              (symbol, ts, timeframe, open, high, low, close, volume, vwap)
            SELECT symbol, ts, '5Min', open, high, low, close, volume, vwap FROM bars;
            DROP TABLE bars;
            ALTER TABLE bars_migrated RENAME TO bars;
            CREATE INDEX IF NOT EXISTS idx_bars_ts ON bars(ts);
            CREATE INDEX IF NOT EXISTS idx_bars_tf_ts ON bars(timeframe, ts);
            """
        )

    def _migrate_fetch_log_pk(self, conn: sqlite3.Connection) -> None:
        """Ensure fetch_log PK includes timeframe (rebuild if legacy 3-col PK)."""
        cols = {row[1] for row in conn.execute("PRAGMA table_info(fetch_log)").fetchall()}
        if "timeframe" not in cols:
            conn.execute(
                "ALTER TABLE fetch_log ADD COLUMN timeframe TEXT NOT NULL DEFAULT ''"
            )
        info = conn.execute("PRAGMA table_info(fetch_log)").fetchall()
        # pk columns: cid order where pk > 0
        pk_cols = [
            row[1] for row in sorted(info, key=lambda col: col[5]) if row[5] > 0
        ]
        if pk_cols == ["symbol", "range_start", "range_end", "timeframe"]:
            return
        conn.executescript(
            """
            CREATE TABLE fetch_log_migrated (
              symbol TEXT NOT NULL,
              range_start TEXT NOT NULL,
              range_end TEXT NOT NULL,
              timeframe TEXT NOT NULL DEFAULT '',
              bar_count INTEGER NOT NULL,
              fetched_at TEXT NOT NULL,
              PRIMARY KEY (symbol, range_start, range_end, timeframe)
            );
            INSERT OR IGNORE INTO fetch_log_migrated
              (symbol, range_start, range_end, timeframe, bar_count, fetched_at)
            SELECT symbol, range_start, range_end,
                   COALESCE(NULLIF(timeframe, ''), '5Min'),
                   bar_count, fetched_at
            FROM fetch_log;
            DROP TABLE fetch_log;
            ALTER TABLE fetch_log_migrated RENAME TO fetch_log;
            """
        )

    def is_fetched(
        self,
        symbol: str,
        range_start: str,
        range_end: str,
        *,
        timeframe: str = "",
    ) -> bool:
        with self._connect(readonly=True) as conn:
            row = conn.execute(
                """
                SELECT 1 FROM fetch_log
                WHERE symbol = ? AND range_start = ? AND range_end = ?
                  AND timeframe = ?
                """,
                (symbol, range_start, range_end, timeframe),
            ).fetchone()
            return row is not None

    def upsert_bars(
        self, rows: List[BarRow], *, timeframe: str = DEFAULT_TIMEFRAME
    ) -> int:
        if not rows:
            return 0
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO bars
                  (symbol, ts, timeframe, open, high, low, close, volume, vwap)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, ts, timeframe) DO UPDATE SET
                  open=excluded.open,
                  high=excluded.high,
                  low=excluded.low,
                  close=excluded.close,
                  volume=excluded.volume,
                  vwap=excluded.vwap
                """,
                [
                    (sym, ts, timeframe, o, h, low, c, vol, vwap)
                    for sym, ts, o, h, low, c, vol, vwap in rows
                ],
            )
            return len(rows)

    def mark_fetched(
        self,
        symbol: str,
        range_start: str,
        range_end: str,
        bar_count: int,
        *,
        timeframe: str = "",
    ) -> None:
        fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO fetch_log
                  (symbol, range_start, range_end, timeframe, bar_count, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, range_start, range_end, timeframe) DO UPDATE SET
                  bar_count=excluded.bar_count,
                  fetched_at=excluded.fetched_at
                """,
                (symbol, range_start, range_end, timeframe, bar_count, fetched_at),
            )

    def clear_fetch_log(
        self,
        symbol: str,
        range_start: str,
        range_end: str,
        *,
        timeframe: str = "",
    ) -> None:
        with self._connect() as conn:
            if timeframe:
                conn.execute(
                    """
                    DELETE FROM fetch_log
                    WHERE symbol = ? AND range_start = ? AND range_end = ?
                      AND timeframe = ?
                    """,
                    (symbol, range_start, range_end, timeframe),
                )
            else:
                conn.execute(
                    """
                    DELETE FROM fetch_log
                    WHERE symbol = ? AND range_start = ? AND range_end = ?
                    """,
                    (symbol, range_start, range_end),
                )

    def clear_bars(
        self,
        symbol: str,
        range_start: str,
        range_end: str,
        *,
        timeframe: str = DEFAULT_TIMEFRAME,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                DELETE FROM bars
                WHERE symbol = ? AND ts >= ? AND ts <= ? AND timeframe = ?
                """,
                (symbol, range_start, range_end, timeframe),
            )

    def list_fetch_datasets(self) -> List[dict]:
        with self._connect(readonly=True) as conn:
            rows = conn.execute(
                """
                SELECT
                  range_start,
                  range_end,
                  timeframe,
                  COUNT(DISTINCT symbol) AS symbols,
                  MAX(fetched_at) AS fetched_at
                FROM fetch_log
                GROUP BY range_start, range_end, timeframe
                ORDER BY fetched_at DESC
                """
            ).fetchall()
        out = []
        for range_start, range_end, timeframe, symbols, fetched_at in rows:
            out.append(
                {
                    "start": range_start,
                    "end": range_end,
                    "timeframe": timeframe or "",
                    "symbols": int(symbols or 0),
                    "fetched_at": fetched_at or "",
                }
            )
        return out

    def list_timestamps(
        self,
        start: str,
        end: str,
        *,
        timeframe: str = DEFAULT_TIMEFRAME,
    ) -> List[str]:
        with self._connect(readonly=True) as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT ts FROM bars
                WHERE ts >= ? AND ts <= ? AND timeframe = ?
                ORDER BY ts
                """,
                (start, end, timeframe),
            ).fetchall()
        return [r[0] for r in rows]

    def prices_at(
        self,
        ts: str,
        symbols: List[str],
        *,
        timeframe: str = DEFAULT_TIMEFRAME,
    ) -> Dict[str, float]:
        if not symbols:
            return {}
        placeholders = ",".join("?" * len(symbols))
        with self._connect(readonly=True) as conn:
            rows = conn.execute(
                f"""
                SELECT symbol, vwap, close FROM bars
                WHERE ts = ? AND timeframe = ? AND symbol IN ({placeholders})
                """,
                [ts, timeframe, *symbols],
            ).fetchall()
        return {sym: bar_price(vwap, close) for sym, vwap, close in rows}

    def status(self) -> dict:
        with self._connect(readonly=True) as conn:
            bar_rows = conn.execute(
                "SELECT COUNT(*), COUNT(DISTINCT symbol) FROM bars"
            ).fetchone()
            fetch_rows = conn.execute("SELECT COUNT(*) FROM fetch_log").fetchone()
            minmax = conn.execute("SELECT MIN(ts), MAX(ts) FROM bars").fetchone()
        return {
            "bar_count": bar_rows[0] if bar_rows else 0,
            "symbol_count": bar_rows[1] if bar_rows else 0,
            "fetch_ranges": fetch_rows[0] if fetch_rows else 0,
            "min_ts": minmax[0] if minmax else None,
            "max_ts": minmax[1] if minmax else None,
        }
