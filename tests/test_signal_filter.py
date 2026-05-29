"""
test_signal_filter.py
---------------------
signal_filter.py のユニットテスト。

外部API呼び出しはすべてモック：
  - get_price_history → モック価格 DataFrame を返す
  - db               → SQLite 操作をモック（gc_signals キャッシュ）
"""

import pytest
import pandas as pd
import numpy as np
from datetime import date, timedelta
from unittest.mock import patch, MagicMock

from signal_filter import find_recent_gc_stocks


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def screened_df():
    """apply_all_screens() 通過済みサンプル"""
    return pd.DataFrame([
        {
            "code": "7203", "name": "トヨタ自動車", "sector": "輸送用機器",
            "price": 3500.0, "per": 12.0, "pbr": 0.9, "dividend_yield": 3.5,
            "market_cap": 5e13, "is_undervalued": True, "is_high_dividend": False,
            "is_low_pbr": True, "label": "◆ 割安",
        },
        {
            "code": "8306", "name": "三菱UFJ", "sector": "銀行業",
            "price": 1200.0, "per": 10.0, "pbr": 0.7, "dividend_yield": 4.5,
            "market_cap": 2e13, "is_undervalued": True, "is_high_dividend": True,
            "is_low_pbr": True, "label": "★ 両方",
        },
    ])


def _make_price_df(cross_type: str | None = None):
    """
    cross_type : "golden"=GC発生あり / "dead"=DC発生あり / None=クロスなし（横ばい）
    """
    dates = pd.date_range(end=date.today(), periods=90, freq="B")

    if cross_type == "golden":
        close = np.concatenate([np.linspace(1100, 900, 75), np.linspace(900, 1200, 15)])
    elif cross_type == "dead":
        close = np.concatenate([np.linspace(900, 1100, 15), np.linspace(1100, 800, 75)])
    else:
        close = np.full(90, 1000.0)

    return pd.DataFrame(
        {"Open": close, "High": close + 5, "Low": close - 5, "Close": close, "Volume": 100_000},
        index=dates,
    )


# ============================================================
# find_recent_gc_stocks
# ============================================================

class TestFindRecentGcStocks:

    # --- 基本動作 ---

    def test_returns_dataframe(self, screened_df):
        price_df = _make_price_df(cross_type="golden")
        with patch("signal_filter.db.init_db"), \
             patch("signal_filter.db.load_gc_signals", return_value=None), \
             patch("signal_filter.db.upsert_gc_signals"), \
             patch("signal_filter.get_price_history", return_value=price_df):
            result = find_recent_gc_stocks(screened_df, days=30)
        assert isinstance(result, pd.DataFrame)

    def test_empty_input_returns_empty(self):
        empty_df = pd.DataFrame(columns=["code"])
        result = find_recent_gc_stocks(empty_df, days=7)
        assert result.empty

    # --- GC検出ロジック ---

    def test_detects_recent_gc(self, screened_df):
        """直近30日以内にGCが発生している銘柄を検出する"""
        price_df = _make_price_df(cross_type="golden")
        with patch("signal_filter.db.init_db"), \
             patch("signal_filter.db.load_gc_signals", return_value=None), \
             patch("signal_filter.db.upsert_gc_signals"), \
             patch("signal_filter.get_price_history", return_value=price_df):
            result = find_recent_gc_stocks(screened_df, days=30)
        assert not result.empty

    def test_excludes_stocks_without_gc(self, screened_df):
        """GCが発生していない銘柄は除外される"""
        flat_df = _make_price_df(cross_type=None)
        with patch("signal_filter.db.init_db"), \
             patch("signal_filter.db.load_gc_signals", return_value=None), \
             patch("signal_filter.db.upsert_gc_signals"), \
             patch("signal_filter.get_price_history", return_value=flat_df):
            result = find_recent_gc_stocks(screened_df, days=7)
        assert result.empty

    def test_excludes_stocks_with_only_dead_cross(self, screened_df):
        """DCのみの銘柄は除外される"""
        dc_df = _make_price_df(cross_type="dead")
        with patch("signal_filter.db.init_db"), \
             patch("signal_filter.db.load_gc_signals", return_value=None), \
             patch("signal_filter.db.upsert_gc_signals"), \
             patch("signal_filter.get_price_history", return_value=dc_df):
            result = find_recent_gc_stocks(screened_df, days=7)
        assert result.empty

    # --- 追加列 ---

    def test_result_contains_gc_date_column(self, screened_df):
        price_df = _make_price_df(cross_type="golden")
        with patch("signal_filter.db.init_db"), \
             patch("signal_filter.db.load_gc_signals", return_value=None), \
             patch("signal_filter.db.upsert_gc_signals"), \
             patch("signal_filter.get_price_history", return_value=price_df):
            result = find_recent_gc_stocks(screened_df, days=30)
        if not result.empty:
            assert "gc_date" in result.columns

    def test_result_contains_gc_days_ago_column(self, screened_df):
        price_df = _make_price_df(cross_type="golden")
        with patch("signal_filter.db.init_db"), \
             patch("signal_filter.db.load_gc_signals", return_value=None), \
             patch("signal_filter.db.upsert_gc_signals"), \
             patch("signal_filter.get_price_history", return_value=price_df):
            result = find_recent_gc_stocks(screened_df, days=30)
        if not result.empty:
            assert "gc_days_ago" in result.columns
            assert (result["gc_days_ago"] >= 0).all()

    def test_result_sorted_by_gc_days_ago(self, screened_df):
        """直近のGCが上に来るよう gc_days_ago 昇順になっている"""
        price_df = _make_price_df(cross_type="golden")
        with patch("signal_filter.db.init_db"), \
             patch("signal_filter.db.load_gc_signals", return_value=None), \
             patch("signal_filter.db.upsert_gc_signals"), \
             patch("signal_filter.get_price_history", return_value=price_df):
            result = find_recent_gc_stocks(screened_df, days=30)
        if len(result) > 1:
            assert result["gc_days_ago"].is_monotonic_increasing

    def test_original_columns_preserved(self, screened_df):
        """元のスクリーニング列が保持されている"""
        price_df = _make_price_df(cross_type="golden")
        with patch("signal_filter.db.init_db"), \
             patch("signal_filter.db.load_gc_signals", return_value=None), \
             patch("signal_filter.db.upsert_gc_signals"), \
             patch("signal_filter.get_price_history", return_value=price_df):
            result = find_recent_gc_stocks(screened_df, days=30)
        if not result.empty:
            for col in ["code", "name", "per", "dividend_yield"]:
                assert col in result.columns

    # --- エラーハンドリング ---

    def test_skips_ticker_when_price_unavailable(self, screened_df):
        """価格データ取得失敗の銘柄はスキップされ、エラーにならない"""
        with patch("signal_filter.db.init_db"), \
             patch("signal_filter.db.load_gc_signals", return_value=None), \
             patch("signal_filter.db.upsert_gc_signals"), \
             patch("signal_filter.get_price_history", return_value=None):
            result = find_recent_gc_stocks(screened_df, days=7)
        assert isinstance(result, pd.DataFrame)

    def test_skips_ticker_when_price_empty(self, screened_df):
        """空 DataFrame が返ってきた銘柄はスキップされる"""
        with patch("signal_filter.db.init_db"), \
             patch("signal_filter.db.load_gc_signals", return_value=None), \
             patch("signal_filter.db.upsert_gc_signals"), \
             patch("signal_filter.get_price_history", return_value=pd.DataFrame()):
            result = find_recent_gc_stocks(screened_df, days=7)
        assert result.empty

    # --- キャッシュ（SQLite）---

    def test_uses_db_cache_when_available(self, screened_df):
        """今日の gc_signals キャッシュがあれば yfinance を呼ばない"""
        cached_signals = pd.DataFrame([
            {"code": "7203", "gc_date": str(date.today()), "gc_days_ago": 0},
            {"code": "8306", "gc_date": str(date.today()), "gc_days_ago": 0},
        ])
        with patch("signal_filter.db.init_db"), \
             patch("signal_filter.db.load_gc_signals", return_value=cached_signals), \
             patch("signal_filter.get_price_history") as mock_hist:
            result = find_recent_gc_stocks(screened_df, days=7)
        mock_hist.assert_not_called()
        assert len(result) == len(screened_df)

    def test_saves_to_db_after_scan(self, screened_df):
        """スキャン後に gc_signals テーブルへ保存する"""
        price_df = _make_price_df(cross_type="golden")
        with patch("signal_filter.db.init_db"), \
             patch("signal_filter.db.load_gc_signals", return_value=None), \
             patch("signal_filter.db.upsert_gc_signals") as mock_upsert, \
             patch("signal_filter.get_price_history", return_value=price_df):
            result = find_recent_gc_stocks(screened_df, days=30)
        if not result.empty:
            mock_upsert.assert_called_once()

    # --- progress_callback ---

    def test_calls_progress_callback(self, screened_df):
        calls = []
        flat_df = _make_price_df(cross_type=None)
        with patch("signal_filter.db.init_db"), \
             patch("signal_filter.db.load_gc_signals", return_value=None), \
             patch("signal_filter.db.upsert_gc_signals"), \
             patch("signal_filter.get_price_history", return_value=flat_df):
            find_recent_gc_stocks(
                screened_df, days=7,
                progress_callback=lambda c, t, code: calls.append((c, t)),
            )
        assert len(calls) == len(screened_df)
        assert calls[-1] == (len(screened_df), len(screened_df))
