"""
db.py
-----
SQLite 操作の共通層。

テーブル構成:
  stocks         : 銘柄基本情報（PER / PBR / 配当利回り等）
  price_history  : 株価時系列
  fetch_log      : cronバッチの実行ログ
  gc_signals     : ゴールデンクロス検出結果（日次スキャンキャッシュ）
"""

import sqlite3
from datetime import date, datetime
from typing import Optional

import pandas as pd

DB_PATH = "stock_screener.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS stocks (
    code             TEXT,
    fetched_at       TEXT,
    name             TEXT,
    sector           TEXT,
    industry         TEXT,
    price            REAL,
    per              REAL,
    pbr              REAL,
    dividend_yield   REAL,
    market_cap       REAL,
    week52_high      REAL,
    week52_low       REAL,
    PRIMARY KEY (code, fetched_at)
);

CREATE TABLE IF NOT EXISTS price_history (
    code   TEXT,
    date   TEXT,
    open   REAL,
    high   REAL,
    low    REAL,
    close  REAL,
    volume REAL,
    PRIMARY KEY (code, date)
);

CREATE TABLE IF NOT EXISTS fetch_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    executed_at TEXT,
    status      TEXT,
    message     TEXT
);

CREATE TABLE IF NOT EXISTS gc_signals (
    code        TEXT,
    scanned_at  TEXT,
    gc_date     TEXT,
    gc_days_ago INTEGER,
    PRIMARY KEY (code, scanned_at)
);
"""


def _f(val) -> Optional[float]:
    """None / NaN を None に変換して返す。"""
    if val is None:
        return None
    try:
        v = float(val)
        return None if v != v else v  # NaN check
    except (TypeError, ValueError):
        return None


# ============================================================
# 初期化
# ============================================================

def init_db(db_path: str = DB_PATH) -> None:
    """テーブルを作成する（冪等）。"""
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_SCHEMA)


# ============================================================
# stocks
# ============================================================

def upsert_stocks(df: pd.DataFrame, db_path: str = DB_PATH) -> None:
    """
    銘柄基本情報を stocks テーブルへ保存（同日同コードは上書き）。

    Parameters
    ----------
    df : get_all_stocks() / get_stock_info() の返り値を集めた DataFrame
         想定カラム: code, name, sector, industry, price, per, pbr,
                    dividend_yield, market_cap, 52w_high, 52w_low
    """
    today = str(date.today())
    records = [
        (
            str(row.get("code", "")),
            today,
            str(row.get("name", "") or ""),
            str(row.get("sector", "") or ""),
            str(row.get("industry", "") or ""),
            _f(row.get("price")),
            _f(row.get("per")),
            _f(row.get("pbr")),
            _f(row.get("dividend_yield")),
            _f(row.get("market_cap")),
            _f(row.get("52w_high")),
            _f(row.get("52w_low")),
        )
        for _, row in df.iterrows()
    ]
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO stocks
               (code, fetched_at, name, sector, industry, price, per, pbr,
                dividend_yield, market_cap, week52_high, week52_low)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            records,
        )


def load_latest_stocks(db_path: str = DB_PATH) -> pd.DataFrame:
    """
    直近取得日の全銘柄データを DataFrame で返す。
    データがなければ空の DataFrame を返す。
    """
    with sqlite3.connect(db_path) as conn:
        df = pd.read_sql(
            """SELECT code, name, sector, industry, price, per, pbr,
                      dividend_yield, market_cap,
                      week52_high AS "52w_high", week52_low AS "52w_low"
               FROM stocks
               WHERE fetched_at = (SELECT MAX(fetched_at) FROM stocks)""",
            conn,
        )
    return df


# ============================================================
# price_history
# ============================================================

def upsert_price_history(code: str, df: pd.DataFrame, db_path: str = DB_PATH) -> None:
    """
    株価時系列を price_history テーブルへ保存（同日同コードは上書き）。

    Parameters
    ----------
    code : 4桁証券コード
    df   : yfinance の history() が返す DataFrame
           index=DatetimeIndex, columns=[Open, High, Low, Close, Volume, ...]
    """
    records = []
    for dt, row in df.iterrows():
        date_str = dt.date().isoformat() if hasattr(dt, "date") else str(dt)[:10]
        records.append((
            code,
            date_str,
            _f(row.get("Open")),
            _f(row.get("High")),
            _f(row.get("Low")),
            _f(row.get("Close")),
            _f(row.get("Volume")),
        ))
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO price_history
               (code, date, open, high, low, close, volume)
               VALUES (?,?,?,?,?,?,?)""",
            records,
        )


def load_price_history(code: str, db_path: str = DB_PATH) -> Optional[pd.DataFrame]:
    """
    指定銘柄の株価時系列を返す。
    データがなければ None を返す。

    Returns
    -------
    pd.DataFrame with DatetimeIndex and columns [Open, High, Low, Close, Volume]
    """
    with sqlite3.connect(db_path) as conn:
        raw = pd.read_sql(
            """SELECT date, open, high, low, close, volume
               FROM price_history WHERE code = ? ORDER BY date""",
            conn,
            params=(code,),
        )
    if raw.empty:
        return None
    raw["date"] = pd.to_datetime(raw["date"])
    raw = raw.set_index("date")
    raw.index.name = None
    raw.columns = ["Open", "High", "Low", "Close", "Volume"]
    return raw


# ============================================================
# fetch_log
# ============================================================

def log_fetch(status: str, message: str, db_path: str = DB_PATH) -> None:
    """cronバッチの実行結果を fetch_log に記録する。"""
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO fetch_log (executed_at, status, message) VALUES (?,?,?)",
            (datetime.now().isoformat(timespec="seconds"), status, message),
        )


# ============================================================
# gc_signals
# ============================================================

def upsert_gc_signals(df: pd.DataFrame, db_path: str = DB_PATH) -> None:
    """
    GCスキャン結果を gc_signals テーブルへ保存（今日付きで上書き）。

    Parameters
    ----------
    df : find_recent_gc_stocks() の返り値
         必須カラム: code, gc_date, gc_days_ago
    """
    today = str(date.today())
    records = [
        (
            str(row["code"]),
            today,
            str(row["gc_date"]),
            int(row["gc_days_ago"]),
        )
        for _, row in df.iterrows()
    ]
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO gc_signals
               (code, scanned_at, gc_date, gc_days_ago) VALUES (?,?,?,?)""",
            records,
        )


def load_gc_signals(db_path: str = DB_PATH) -> Optional[pd.DataFrame]:
    """
    今日付きの GC スキャン結果を返す。
    今日のデータがなければ None を返す。
    """
    today = str(date.today())
    with sqlite3.connect(db_path) as conn:
        df = pd.read_sql(
            "SELECT code, gc_date, gc_days_ago FROM gc_signals WHERE scanned_at = ?",
            conn,
            params=(today,),
        )
    return df if not df.empty else None
