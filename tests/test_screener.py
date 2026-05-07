"""
test_screener.py
----------------
screener.py のユニットテスト。

対象関数:
  - screen_undervalued / screen_high_dividend / screen_low_pbr
  - apply_all_screens
  - calculate_technical_indicators
  - get_latest_signal
  - _calc_rsi / _calc_macd（内部ヘルパー）
"""

import pytest
import pandas as pd
import numpy as np
from datetime import date

from screener import (
    screen_undervalued,
    screen_high_dividend,
    screen_low_pbr,
    apply_all_screens,
    calculate_technical_indicators,
    get_latest_signal,
    _calc_rsi,
    _calc_macd,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def stock_df():
    """スクリーニング用サンプル DataFrame"""
    return pd.DataFrame([
        # code  per    pbr   yield  → 期待タグ
        {"code": "1001", "name": "割安高配当", "per": 10.0, "pbr": 0.8, "dividend_yield": 6.0},
        {"code": "1002", "name": "割安のみ",   "per": 14.9, "pbr": 0.95, "dividend_yield": 2.0},
        {"code": "1003", "name": "高配当のみ", "per": 20.0, "pbr": 1.2, "dividend_yield": 5.0},
        {"code": "1004", "name": "該当なし",   "per": 30.0, "pbr": 2.0, "dividend_yield": 1.0},
        {"code": "1005", "name": "NaN銘柄",   "per": None,  "pbr": None, "dividend_yield": None},
    ])


@pytest.fixture
def flat_price_df():
    """横ばい株価（クロスなし）"""
    dates = pd.date_range(end=date.today(), periods=90, freq="B")
    close = np.full(90, 1000.0)
    return pd.DataFrame(
        {"Open": close, "High": close + 5, "Low": close - 5, "Close": close, "Volume": 100_000},
        index=dates,
    )


@pytest.fixture
def rising_price_df():
    """右肩上がり株価（GC発生あり）"""
    dates = pd.date_range(end=date.today(), periods=90, freq="B")
    # 前半下落→後半急騰でMA5がMA25を上抜け
    close = np.concatenate([np.linspace(1100, 900, 75), np.linspace(900, 1200, 15)])
    return pd.DataFrame(
        {"Open": close, "High": close + 5, "Low": close - 5, "Close": close, "Volume": 100_000},
        index=dates,
    )


@pytest.fixture
def falling_price_df():
    """右肩下がり株価（DC発生あり）"""
    dates = pd.date_range(end=date.today(), periods=90, freq="B")
    close = np.concatenate([np.linspace(900, 1100, 15), np.linspace(1100, 800, 75)])
    return pd.DataFrame(
        {"Open": close, "High": close + 5, "Low": close - 5, "Close": close, "Volume": 100_000},
        index=dates,
    )


# ============================================================
# screen_undervalued
# ============================================================

class TestScreenUndervalued:

    def test_filters_by_per_max(self, stock_df):
        result = screen_undervalued(stock_df, per_max=15.0)
        assert set(result["code"]) == {"1001", "1002"}

    def test_excludes_nan_per(self, stock_df):
        result = screen_undervalued(stock_df, per_max=99.0)
        assert "1005" not in result["code"].values

    def test_strict_boundary(self, stock_df):
        # per_max=10.0 のとき per==10.0 の銘柄は含む（≤）
        result = screen_undervalued(stock_df, per_max=10.0)
        assert "1001" in result["code"].values

    def test_empty_input(self):
        result = screen_undervalued(pd.DataFrame(columns=["per", "code"]))
        assert result.empty


# ============================================================
# screen_high_dividend
# ============================================================

class TestScreenHighDividend:

    def test_filters_by_yield_min(self, stock_df):
        result = screen_high_dividend(stock_df, yield_min=5.0)
        assert set(result["code"]) == {"1001", "1003"}

    def test_excludes_nan_yield(self, stock_df):
        result = screen_high_dividend(stock_df, yield_min=0.1)
        assert "1005" not in result["code"].values

    def test_strict_boundary(self, stock_df):
        # yield_min=5.0 のとき dividend_yield==5.0 は含む（≥）
        result = screen_high_dividend(stock_df, yield_min=5.0)
        assert "1003" in result["code"].values


# ============================================================
# screen_low_pbr
# ============================================================

class TestScreenLowPbr:

    def test_filters_by_pbr_max(self, stock_df):
        result = screen_low_pbr(stock_df, pbr_max=1.0)
        assert set(result["code"]) == {"1001", "1002"}

    def test_excludes_nan_pbr(self, stock_df):
        result = screen_low_pbr(stock_df, pbr_max=99.0)
        assert "1005" not in result["code"].values


# ============================================================
# apply_all_screens
# ============================================================

class TestApplyAllScreens:

    def test_label_both(self, stock_df):
        result = apply_all_screens(stock_df, per_max=15.0, yield_min=5.0)
        row = result[result["code"] == "1001"].iloc[0]
        assert row["is_undervalued"] == True
        assert row["is_high_dividend"] == True
        assert row["label"] == "★ 両方"

    def test_label_undervalued_only(self, stock_df):
        result = apply_all_screens(stock_df, per_max=15.0, yield_min=5.0)
        row = result[result["code"] == "1002"].iloc[0]
        assert row["is_undervalued"] == True
        assert row["is_high_dividend"] == False
        assert "◆ 割安" in row["label"]

    def test_label_high_dividend_only(self, stock_df):
        result = apply_all_screens(stock_df, per_max=15.0, yield_min=5.0)
        row = result[result["code"] == "1003"].iloc[0]
        assert row["is_undervalued"] == False
        assert row["is_high_dividend"] == True
        assert "◉ 高配当" in row["label"]

    def test_label_none(self, stock_df):
        result = apply_all_screens(stock_df, per_max=15.0, yield_min=5.0)
        row = result[result["code"] == "1004"].iloc[0]
        assert row["label"] == "-"

    def test_pbr_filter_disabled_by_default(self, stock_df):
        result = apply_all_screens(stock_df, per_max=99.0, yield_min=0.1, pbr_max=None)
        assert (result["is_low_pbr"] == False).all()

    def test_pbr_filter_enabled(self, stock_df):
        result = apply_all_screens(stock_df, per_max=99.0, yield_min=0.1, pbr_max=1.0)
        low_pbr = result[result["is_low_pbr"] == True]
        assert set(low_pbr["code"]) == {"1001", "1002"}

    def test_all_rows_preserved(self, stock_df):
        result = apply_all_screens(stock_df)
        assert len(result) == len(stock_df)


# ============================================================
# calculate_technical_indicators
# ============================================================

class TestCalculateTechnicalIndicators:

    def test_ma_columns_exist(self, flat_price_df):
        result = calculate_technical_indicators(flat_price_df)
        assert {"MA5", "MA25", "MA75"}.issubset(result.columns)

    def test_ma5_nan_for_first_rows(self, flat_price_df):
        result = calculate_technical_indicators(flat_price_df)
        assert result["MA5"].iloc[:4].isna().all()
        assert pd.notna(result["MA5"].iloc[4])

    def test_ma25_nan_for_first_rows(self, flat_price_df):
        result = calculate_technical_indicators(flat_price_df)
        assert result["MA25"].iloc[:24].isna().all()
        assert pd.notna(result["MA25"].iloc[24])

    def test_golden_cross_detected(self, rising_price_df):
        result = calculate_technical_indicators(rising_price_df)
        assert result["golden_cross"].any(), "GCが検出されるべき"

    def test_dead_cross_detected(self, falling_price_df):
        result = calculate_technical_indicators(falling_price_df)
        assert result["dead_cross"].any(), "DCが検出されるべき"

    def test_golden_cross_condition(self, rising_price_df):
        result = calculate_technical_indicators(rising_price_df)
        gc_rows = result[result["golden_cross"]]
        # GC発生行では MA5 > MA25
        assert (gc_rows["MA5"] > gc_rows["MA25"]).all()

    def test_rsi_columns_exist(self, flat_price_df):
        result = calculate_technical_indicators(flat_price_df)
        assert "rsi" in result.columns

    def test_rsi_range(self, rising_price_df):
        result = calculate_technical_indicators(rising_price_df)
        rsi = result["rsi"].dropna()
        assert (rsi >= 0).all() and (rsi <= 100).all()

    def test_macd_columns_exist(self, flat_price_df):
        result = calculate_technical_indicators(flat_price_df)
        assert {"macd", "macd_signal", "macd_hist"}.issubset(result.columns)

    def test_macd_hist_equals_macd_minus_signal(self, rising_price_df):
        result = calculate_technical_indicators(rising_price_df)
        diff = (result["macd"] - result["macd_signal"] - result["macd_hist"]).dropna()
        assert (diff.abs() < 1e-10).all()


# ============================================================
# get_latest_signal
# ============================================================

class TestGetLatestSignal:

    def test_returns_all_keys(self, rising_price_df):
        signal = get_latest_signal(rising_price_df)
        expected = {"golden_cross_date", "dead_cross_date", "trend", "ma5", "ma25", "ma75", "rsi", "macd_cross"}
        assert expected.issubset(signal.keys())

    def test_trend_rising(self, rising_price_df):
        signal = get_latest_signal(rising_price_df)
        assert signal["trend"] == "上昇"

    def test_trend_falling(self, falling_price_df):
        signal = get_latest_signal(falling_price_df)
        assert signal["trend"] == "下降"

    def test_golden_cross_date_set(self, rising_price_df):
        signal = get_latest_signal(rising_price_df)
        assert signal["golden_cross_date"] is not None

    def test_empty_input_returns_empty_dict(self):
        assert get_latest_signal(pd.DataFrame()) == {}

    def test_none_input_returns_empty_dict(self):
        assert get_latest_signal(None) == {}


# ============================================================
# _calc_rsi（内部ヘルパー）
# ============================================================

class TestCalcRsi:

    def test_rsi_range(self):
        close = pd.Series(np.random.uniform(900, 1100, 100))
        rsi = _calc_rsi(close, period=14)
        valid = rsi.dropna()
        assert (valid >= 0).all() and (valid <= 100).all()

    def test_rsi_high_on_strong_uptrend(self):
        close = pd.Series(np.linspace(1000, 2000, 50))
        rsi = _calc_rsi(close, period=14)
        assert rsi.iloc[-1] > 70

    def test_rsi_low_on_strong_downtrend(self):
        close = pd.Series(np.linspace(2000, 1000, 50))
        rsi = _calc_rsi(close, period=14)
        assert rsi.iloc[-1] < 30


# ============================================================
# _calc_macd（内部ヘルパー）
# ============================================================

class TestCalcMacd:

    def test_returns_two_series(self):
        close = pd.Series(np.random.uniform(900, 1100, 100))
        macd, signal = _calc_macd(close)
        assert isinstance(macd, pd.Series)
        assert isinstance(signal, pd.Series)
        assert len(macd) == len(close)

    def test_macd_positive_on_uptrend(self):
        close = pd.Series(np.linspace(1000, 2000, 100))
        macd, _ = _calc_macd(close)
        assert macd.iloc[-1] > 0

    def test_macd_negative_on_downtrend(self):
        close = pd.Series(np.linspace(2000, 1000, 100))
        macd, _ = _calc_macd(close)
        assert macd.iloc[-1] < 0
