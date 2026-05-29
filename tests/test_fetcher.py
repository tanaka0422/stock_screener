"""
test_fetcher.py
---------------
fetcher.py のユニットテスト。

外部API・ネットワーク呼び出しはすべてモック：
  - yf.Ticker       → unittest.mock.MagicMock
  - pd.read_excel   → モック DataFrame を返す
  - pickle / os     → JPX キャッシュのみ引き続き使用
  - db              → SQLite 操作をモック
"""

import pytest
import pandas as pd
import numpy as np
from datetime import date
from unittest.mock import patch, MagicMock

from fetcher import (
    fetch_prime_tickers_from_jpx,
    filter_tickers_by_criteria,
    get_sector33_list,
    get_stock_info,
    get_price_history,
    get_all_stocks,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def jpx_df():
    """JPX銘柄一覧のサンプル DataFrame"""
    return pd.DataFrame([
        {"code": "7203", "name": "トヨタ自動車",   "sector33": "輸送用機器", "sector17": "自動車"},
        {"code": "9984", "name": "ソフトバンクG", "sector33": "情報通信業", "sector17": "IT"},
        {"code": "6758", "name": "ソニーG",        "sector33": "電気機器",   "sector17": "電機"},
        {"code": "8306", "name": "三菱UFJ",        "sector33": "銀行業",     "sector17": "金融"},
    ])


@pytest.fixture
def mock_ticker_info():
    """yf.Ticker.info のモックデータ"""
    return {
        "longName"           : "Toyota Motor Corporation",
        "sector"             : "Consumer Cyclical",
        "industry"           : "Auto Manufacturers",
        "currentPrice"       : 3500.0,
        "trailingPE"         : 12.5,
        "priceToBook"        : 0.9,
        "dividendYield"      : 0.035,
        "marketCap"          : 50_000_000_000_000,
        "fiftyTwoWeekHigh"   : 4000.0,
        "fiftyTwoWeekLow"    : 2800.0,
    }


@pytest.fixture
def mock_price_df():
    """yf.Ticker.history のモックデータ"""
    dates = pd.date_range(end=date.today(), periods=60, freq="B")
    close = np.linspace(3000, 3500, 60)
    return pd.DataFrame(
        {"Open": close, "High": close + 50, "Low": close - 50, "Close": close, "Volume": 500_000},
        index=dates,
    )


def _make_stock_record(code: str) -> dict:
    return {
        "code": code, "name": f"株{code}", "sector": "製造業",
        "price": 1000.0, "per": 12.0, "pbr": 1.0,
        "dividend_yield": 3.0, "market_cap": 1e12,
        "52w_high": 1200.0, "52w_low": 800.0,
        "industry": "製造",
    }


# ============================================================
# fetch_prime_tickers_from_jpx
# ============================================================

class TestFetchPrimeTickersFromJpx:

    def test_returns_dataframe_with_required_columns(self):
        mock_excel = pd.DataFrame([
            {"市場・商品区分": "プライム（内国株式）", "コード": "7203", "銘柄名": "トヨタ", "33業種区分": "輸送用機器", "17業種区分": "自動車"},
            {"市場・商品区分": "スタンダード（内国株式）", "コード": "9999", "銘柄名": "除外株", "33業種区分": "製造業", "17業種区分": "製造"},
        ])
        with patch("fetcher.os.path.exists", return_value=False), \
             patch("fetcher.pd.read_excel", return_value=mock_excel), \
             patch("builtins.open", MagicMock()), \
             patch("fetcher.pickle.dump"):
            result = fetch_prime_tickers_from_jpx()
        assert set(result.columns) >= {"code", "name", "sector33", "sector17"}

    def test_filters_prime_only(self):
        mock_excel = pd.DataFrame([
            {"市場・商品区分": "プライム（内国株式）",    "コード": "1001", "銘柄名": "プライム株", "33業種区分": "製造業", "17業種区分": "製造"},
            {"市場・商品区分": "スタンダード（内国株式）", "コード": "9999", "銘柄名": "除外株",   "33業種区分": "製造業", "17業種区分": "製造"},
        ])
        with patch("fetcher.os.path.exists", return_value=False), \
             patch("fetcher.pd.read_excel", return_value=mock_excel), \
             patch("builtins.open", MagicMock()), \
             patch("fetcher.pickle.dump"):
            result = fetch_prime_tickers_from_jpx()
        assert "9999" not in result["code"].values
        assert "1001" in result["code"].values

    def test_uses_cache_when_available(self):
        cached_df = pd.DataFrame([{"code": "7203", "name": "キャッシュ株", "sector33": "製造業", "sector17": "製造"}])
        with patch("fetcher.os.path.exists", return_value=True), \
             patch("fetcher.pickle.load", return_value=cached_df), \
             patch("builtins.open", MagicMock()):
            result = fetch_prime_tickers_from_jpx()
        assert result.iloc[0]["name"] == "キャッシュ株"

    def test_returns_empty_df_on_error(self):
        with patch("fetcher.os.path.exists", return_value=False), \
             patch("fetcher.pd.read_excel", side_effect=Exception("network error")):
            result = fetch_prime_tickers_from_jpx()
        assert result.empty


# ============================================================
# filter_tickers_by_criteria
# ============================================================

class TestFilterTickersByCriteria:

    def test_no_filter_returns_all(self, jpx_df):
        result = filter_tickers_by_criteria(jpx_df, sectors=None, max_count=100)
        assert set(result) == {"7203", "9984", "6758", "8306"}

    def test_sector_filter(self, jpx_df):
        result = filter_tickers_by_criteria(jpx_df, sectors=["輸送用機器"])
        assert result == ["7203"]

    def test_multiple_sector_filter(self, jpx_df):
        result = filter_tickers_by_criteria(jpx_df, sectors=["輸送用機器", "電気機器"])
        assert set(result) == {"7203", "6758"}

    def test_max_count_truncates(self, jpx_df):
        result = filter_tickers_by_criteria(jpx_df, sectors=None, max_count=2)
        assert len(result) == 2

    def test_unknown_sector_returns_empty(self, jpx_df):
        result = filter_tickers_by_criteria(jpx_df, sectors=["存在しない業種"])
        assert result == []


# ============================================================
# get_sector33_list
# ============================================================

class TestGetSector33List:

    def test_returns_sorted_unique_list(self, jpx_df):
        result = get_sector33_list(jpx_df)
        assert result == sorted(set(["輸送用機器", "情報通信業", "電気機器", "銀行業"]))

    def test_excludes_nan(self):
        df = pd.DataFrame([
            {"sector33": "製造業"},
            {"sector33": None},
            {"sector33": "情報通信業"},
        ])
        result = get_sector33_list(df)
        assert None not in result
        assert len(result) == 2


# ============================================================
# get_stock_info
# ============================================================

class TestGetStockInfo:

    def test_returns_expected_keys(self, mock_ticker_info):
        mock_ticker = MagicMock()
        mock_ticker.info = mock_ticker_info
        with patch("fetcher.yf.Ticker", return_value=mock_ticker):
            result = get_stock_info("7203")
        expected_keys = {"code", "name", "sector", "price", "per", "pbr", "dividend_yield", "market_cap"}
        assert expected_keys.issubset(result.keys())

    def test_dividend_yield_converted_to_percent(self, mock_ticker_info):
        mock_ticker = MagicMock()
        mock_ticker.info = mock_ticker_info  # dividendYield=0.035
        with patch("fetcher.yf.Ticker", return_value=mock_ticker):
            result = get_stock_info("7203")
        assert abs(result["dividend_yield"] - 3.5) < 1e-9

    def test_uses_correct_ticker_format(self, mock_ticker_info):
        mock_ticker = MagicMock()
        mock_ticker.info = mock_ticker_info
        with patch("fetcher.yf.Ticker", return_value=mock_ticker) as mock_yf:
            get_stock_info("7203")
        mock_yf.assert_called_once_with("7203.T")

    def test_returns_none_on_exception(self):
        with patch("fetcher.yf.Ticker", side_effect=Exception("API error")):
            result = get_stock_info("7203")
        assert result is None

    def test_code_preserved_in_result(self, mock_ticker_info):
        mock_ticker = MagicMock()
        mock_ticker.info = mock_ticker_info
        with patch("fetcher.yf.Ticker", return_value=mock_ticker):
            result = get_stock_info("7203")
        assert result["code"] == "7203"


# ============================================================
# get_price_history
# ============================================================

class TestGetPriceHistory:

    def test_returns_dataframe_from_yfinance(self, mock_price_df):
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = mock_price_df
        with patch("fetcher.db.load_price_history", return_value=None), \
             patch("fetcher.db.upsert_price_history"), \
             patch("fetcher.yf.Ticker", return_value=mock_ticker):
            result = get_price_history("7203", period="6mo")
        assert isinstance(result, pd.DataFrame)
        assert not result.empty

    def test_returns_cached_from_db(self, mock_price_df):
        """SQLite にデータがあれば yfinance を呼ばない"""
        with patch("fetcher.db.load_price_history", return_value=mock_price_df), \
             patch("fetcher.yf.Ticker") as mock_yf:
            result = get_price_history("7203")
        mock_yf.assert_not_called()
        assert result is mock_price_df

    def test_uses_correct_ticker_format(self, mock_price_df):
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = mock_price_df
        with patch("fetcher.db.load_price_history", return_value=None), \
             patch("fetcher.db.upsert_price_history"), \
             patch("fetcher.yf.Ticker", return_value=mock_ticker) as mock_yf:
            get_price_history("7203")
        mock_yf.assert_called_once_with("7203.T")

    def test_returns_none_on_empty(self):
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = pd.DataFrame()
        with patch("fetcher.db.load_price_history", return_value=None), \
             patch("fetcher.yf.Ticker", return_value=mock_ticker):
            result = get_price_history("7203")
        assert result is None

    def test_returns_none_on_exception(self):
        with patch("fetcher.db.load_price_history", return_value=None), \
             patch("fetcher.yf.Ticker", side_effect=Exception("network error")):
            result = get_price_history("7203")
        assert result is None

    def test_saves_to_db_after_fetch(self, mock_price_df):
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = mock_price_df
        with patch("fetcher.db.load_price_history", return_value=None), \
             patch("fetcher.db.upsert_price_history") as mock_upsert, \
             patch("fetcher.yf.Ticker", return_value=mock_ticker):
            get_price_history("7203")
        mock_upsert.assert_called_once()


# ============================================================
# get_all_stocks
# ============================================================

class TestGetAllStocks:

    def test_returns_dataframe_from_yfinance(self):
        with patch("fetcher.db.init_db"), \
             patch("fetcher.db.load_latest_stocks", return_value=pd.DataFrame()), \
             patch("fetcher.db.upsert_stocks"), \
             patch("fetcher.get_stock_info", side_effect=_make_stock_record), \
             patch("fetcher.time.sleep"):
            result = get_all_stocks(["7203", "9984"], sleep_sec=0)
        assert len(result) == 2
        assert set(result["code"]) == {"7203", "9984"}

    def test_returns_from_db_when_available(self):
        """SQLite に今日のデータがあればそれを返す"""
        cached_df = pd.DataFrame([
            _make_stock_record("7203"),
            _make_stock_record("9984"),
        ])
        with patch("fetcher.db.init_db"), \
             patch("fetcher.db.load_latest_stocks", return_value=cached_df), \
             patch("fetcher.get_stock_info") as mock_info:
            result = get_all_stocks(["7203", "9984"])
        mock_info.assert_not_called()
        assert set(result["code"]) == {"7203", "9984"}

    def test_filters_db_by_requested_tickers(self):
        """DBに多くの銘柄があっても、要求した銘柄だけ返す"""
        cached_df = pd.DataFrame([
            _make_stock_record("7203"),
            _make_stock_record("9984"),
            _make_stock_record("6758"),
        ])
        with patch("fetcher.db.init_db"), \
             patch("fetcher.db.load_latest_stocks", return_value=cached_df):
            result = get_all_stocks(["7203"])
        assert list(result["code"]) == ["7203"]

    def test_skips_failed_tickers(self):
        def mock_get_info(code):
            if code == "9999":
                return None
            return _make_stock_record(code)

        with patch("fetcher.db.init_db"), \
             patch("fetcher.db.load_latest_stocks", return_value=pd.DataFrame()), \
             patch("fetcher.db.upsert_stocks"), \
             patch("fetcher.get_stock_info", side_effect=mock_get_info), \
             patch("fetcher.time.sleep"):
            result = get_all_stocks(["7203", "9999"], sleep_sec=0)
        assert "9999" not in result["code"].values

    def test_returns_empty_df_when_all_fail(self):
        with patch("fetcher.db.init_db"), \
             patch("fetcher.db.load_latest_stocks", return_value=pd.DataFrame()), \
             patch("fetcher.get_stock_info", return_value=None), \
             patch("fetcher.time.sleep"):
            result = get_all_stocks(["9999"], sleep_sec=0)
        assert result.empty

    def test_saves_to_db_after_yfinance_fetch(self):
        with patch("fetcher.db.init_db"), \
             patch("fetcher.db.load_latest_stocks", return_value=pd.DataFrame()), \
             patch("fetcher.db.upsert_stocks") as mock_upsert, \
             patch("fetcher.get_stock_info", side_effect=_make_stock_record), \
             patch("fetcher.time.sleep"):
            get_all_stocks(["7203"], sleep_sec=0)
        mock_upsert.assert_called_once()

    def test_calls_progress_callback(self):
        calls = []

        with patch("fetcher.db.init_db"), \
             patch("fetcher.db.load_latest_stocks", return_value=pd.DataFrame()), \
             patch("fetcher.db.upsert_stocks"), \
             patch("fetcher.get_stock_info", side_effect=_make_stock_record), \
             patch("fetcher.time.sleep"):
            get_all_stocks(
                ["7203", "9984"], sleep_sec=0,
                progress_callback=lambda c, t, code: calls.append(c),
            )
        assert calls == [1, 2]
