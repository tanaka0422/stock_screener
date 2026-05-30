"""
test_db.py
----------
db.py のユニットテスト。

全テストは tmp_path の SQLite ファイルで隔離し、
実際の stock_screener.db に影響を与えない。
"""

import pytest
import pandas as pd
import numpy as np
from datetime import date, timedelta

from db import (
    init_db,
    upsert_stocks,
    load_latest_stocks,
    upsert_price_history,
    load_price_history,
    log_fetch,
    upsert_gc_signals,
    load_gc_signals,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    return path


@pytest.fixture
def sample_stocks_df():
    return pd.DataFrame([
        {
            "code": "7203", "name": "トヨタ自動車", "sector": "輸送用機器",
            "industry": "自動車", "price": 3500.0, "per": 12.0, "pbr": 0.9,
            "dividend_yield": 3.5, "market_cap": 5e13,
            "52w_high": 4000.0, "52w_low": 2800.0,
        },
        {
            "code": "8306", "name": "三菱UFJ", "sector": "銀行業",
            "industry": "銀行", "price": 1200.0, "per": 10.0, "pbr": 0.7,
            "dividend_yield": 4.5, "market_cap": 2e13,
            "52w_high": 1500.0, "52w_low": 900.0,
        },
    ])


@pytest.fixture
def sample_price_df():
    """yfinance 形式の価格 DataFrame"""
    dates = pd.date_range(end=date.today(), periods=60, freq="B")
    close = np.linspace(1000, 1200, 60)
    return pd.DataFrame(
        {"Open": close, "High": close + 5, "Low": close - 5, "Close": close, "Volume": 100_000},
        index=dates,
    )


@pytest.fixture
def sample_gc_df():
    return pd.DataFrame([
        {"code": "7203", "gc_date": str(date.today()), "gc_days_ago": 0,
         "name": "トヨタ", "per": 12.0},
        {"code": "8306", "gc_date": str(date.today() - timedelta(days=3)), "gc_days_ago": 3,
         "name": "三菱UFJ", "per": 10.0},
    ])


# ============================================================
# init_db
# ============================================================

class TestInitDb:

    def test_creates_stocks_table(self, db_path):
        import sqlite3
        with sqlite3.connect(db_path) as conn:
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
        assert "stocks" in tables

    def test_creates_price_history_table(self, db_path):
        import sqlite3
        with sqlite3.connect(db_path) as conn:
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
        assert "price_history" in tables

    def test_creates_fetch_log_table(self, db_path):
        import sqlite3
        with sqlite3.connect(db_path) as conn:
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
        assert "fetch_log" in tables

    def test_creates_gc_signals_table(self, db_path):
        import sqlite3
        with sqlite3.connect(db_path) as conn:
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
        assert "gc_signals" in tables

    def test_idempotent(self, db_path):
        init_db(db_path)
        init_db(db_path)  # 2回呼んでもエラーにならない


# ============================================================
# upsert_stocks / load_latest_stocks
# ============================================================

class TestStocks:

    def test_upsert_and_load(self, db_path, sample_stocks_df):
        upsert_stocks(sample_stocks_df, db_path)
        result = load_latest_stocks(db_path)
        assert len(result) == 2

    def test_loaded_codes_match(self, db_path, sample_stocks_df):
        upsert_stocks(sample_stocks_df, db_path)
        result = load_latest_stocks(db_path)
        assert set(result["code"]) == {"7203", "8306"}

    def test_loaded_columns(self, db_path, sample_stocks_df):
        upsert_stocks(sample_stocks_df, db_path)
        result = load_latest_stocks(db_path)
        for col in ["code", "name", "sector", "per", "pbr", "dividend_yield", "market_cap"]:
            assert col in result.columns

    def test_returns_empty_when_no_data(self, db_path):
        result = load_latest_stocks(db_path)
        assert result.empty

    def test_overwrite_same_code_same_day(self, db_path, sample_stocks_df):
        upsert_stocks(sample_stocks_df, db_path)
        updated = sample_stocks_df.copy()
        updated.loc[updated["code"] == "7203", "per"] = 99.0
        upsert_stocks(updated, db_path)
        result = load_latest_stocks(db_path)
        row = result[result["code"] == "7203"].iloc[0]
        assert row["per"] == pytest.approx(99.0)

    def test_values_preserved(self, db_path, sample_stocks_df):
        upsert_stocks(sample_stocks_df, db_path)
        result = load_latest_stocks(db_path)
        row = result[result["code"] == "7203"].iloc[0]
        assert row["per"] == pytest.approx(12.0)
        assert row["pbr"] == pytest.approx(0.9)

    def test_handles_none_values(self, db_path):
        df = pd.DataFrame([{
            "code": "9999", "name": "テスト", "sector": None,
            "industry": None, "price": None, "per": None, "pbr": None,
            "dividend_yield": None, "market_cap": None,
            "52w_high": None, "52w_low": None,
        }])
        upsert_stocks(df, db_path)
        result = load_latest_stocks(db_path)
        assert len(result) == 1

    def test_52w_fields_mapped_correctly(self, db_path, sample_stocks_df):
        upsert_stocks(sample_stocks_df, db_path)
        result = load_latest_stocks(db_path)
        assert "52w_high" in result.columns
        assert "52w_low" in result.columns
        row = result[result["code"] == "7203"].iloc[0]
        assert row["52w_high"] == pytest.approx(4000.0)


# ============================================================
# upsert_price_history / load_price_history
# ============================================================

class TestPriceHistory:

    def test_upsert_and_load(self, db_path, sample_price_df):
        upsert_price_history("7203", sample_price_df, db_path)
        result = load_price_history("7203", db_path)
        assert result is not None
        assert len(result) == len(sample_price_df)

    def test_returns_none_when_no_data(self, db_path):
        assert load_price_history("9999", db_path) is None

    def test_column_names(self, db_path, sample_price_df):
        upsert_price_history("7203", sample_price_df, db_path)
        result = load_price_history("7203", db_path)
        assert {"Open", "High", "Low", "Close", "Volume"}.issubset(result.columns)

    def test_has_datetime_index(self, db_path, sample_price_df):
        upsert_price_history("7203", sample_price_df, db_path)
        result = load_price_history("7203", db_path)
        assert isinstance(result.index, pd.DatetimeIndex)

    def test_values_preserved(self, db_path, sample_price_df):
        upsert_price_history("7203", sample_price_df, db_path)
        result = load_price_history("7203", db_path)
        assert result["Close"].iloc[-1] == pytest.approx(sample_price_df["Close"].iloc[-1], rel=1e-5)

    def test_overwrite_existing(self, db_path, sample_price_df):
        upsert_price_history("7203", sample_price_df, db_path)
        updated = sample_price_df.copy()
        updated["Close"] = 9999.0
        upsert_price_history("7203", updated, db_path)
        result = load_price_history("7203", db_path)
        assert (result["Close"] == 9999.0).all()

    def test_different_codes_isolated(self, db_path, sample_price_df):
        upsert_price_history("7203", sample_price_df, db_path)
        assert load_price_history("8306", db_path) is None


# ============================================================
# log_fetch
# ============================================================

class TestLogFetch:

    def test_writes_success_log(self, db_path):
        import sqlite3
        log_fetch("success", "テスト成功", db_path)
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute("SELECT status, message FROM fetch_log").fetchall()
        assert len(rows) == 1
        assert rows[0] == ("success", "テスト成功")

    def test_writes_error_log(self, db_path):
        import sqlite3
        log_fetch("error", "テストエラー", db_path)
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute("SELECT status FROM fetch_log").fetchall()
        assert rows[0][0] == "error"

    def test_accumulates_multiple_logs(self, db_path):
        import sqlite3
        log_fetch("success", "1回目", db_path)
        log_fetch("success", "2回目", db_path)
        with sqlite3.connect(db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM fetch_log").fetchone()[0]
        assert count == 2

    def test_executed_at_is_set(self, db_path):
        import sqlite3
        log_fetch("success", "日時テスト", db_path)
        with sqlite3.connect(db_path) as conn:
            row = conn.execute("SELECT executed_at FROM fetch_log").fetchone()
        assert row[0] is not None


# ============================================================
# upsert_gc_signals / load_gc_signals
# ============================================================

class TestGcSignals:

    def test_upsert_and_load(self, db_path, sample_gc_df):
        upsert_gc_signals(sample_gc_df, db_path)
        result = load_gc_signals(db_path)
        assert result is not None
        assert len(result) == 2

    def test_returns_none_when_no_data(self, db_path):
        assert load_gc_signals(db_path) is None

    def test_columns_exist(self, db_path, sample_gc_df):
        upsert_gc_signals(sample_gc_df, db_path)
        result = load_gc_signals(db_path)
        assert {"code", "gc_date", "gc_days_ago"}.issubset(result.columns)

    def test_codes_preserved(self, db_path, sample_gc_df):
        upsert_gc_signals(sample_gc_df, db_path)
        result = load_gc_signals(db_path)
        assert set(result["code"]) == {"7203", "8306"}

    def test_overwrite_same_day(self, db_path, sample_gc_df):
        upsert_gc_signals(sample_gc_df, db_path)
        updated = sample_gc_df.copy()
        updated.loc[updated["code"] == "7203", "gc_days_ago"] = 99
        upsert_gc_signals(updated, db_path)
        result = load_gc_signals(db_path)
        row = result[result["code"] == "7203"].iloc[0]
        assert int(row["gc_days_ago"]) == 99
