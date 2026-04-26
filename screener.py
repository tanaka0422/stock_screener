"""
screener.py
-----------
スクリーニングロジックとテクニカル指標の計算層。

【設計思想】
- 各スクリーニング条件は独立した関数として定義
  → 条件を増やす場合もこのファイルに関数を追加するだけ
- テクニカル指標（移動平均・クロス系）は calculate_technical_indicators() に集約
  → 将来 MACD / RSI / ボリンジャーバンドなども同じ関数内に追加可能
- screener.py は「判定ロジック」に集中し、データ取得（fetcher.py）とUI（app.py）に依存しない
"""

import pandas as pd
import numpy as np
from typing import Optional


# ============================================================
# ① ファンダメンタルスクリーニング
# ============================================================

def screen_undervalued(df: pd.DataFrame, per_max: float = 15.0) -> pd.DataFrame:
    """割安株：PER が per_max 以下の銘柄を抽出"""
    return df[df["per"].notna() & (df["per"] <= per_max)].copy()


def screen_high_dividend(df: pd.DataFrame, yield_min: float = 5.0) -> pd.DataFrame:
    """高配当株：配当利回りが yield_min(%) 以上の銘柄を抽出"""
    return df[df["dividend_yield"].notna() & (df["dividend_yield"] >= yield_min)].copy()


def screen_low_pbr(df: pd.DataFrame, pbr_max: float = 1.0) -> pd.DataFrame:
    """
    低PBR株（解散価値以下）：PBR が pbr_max 以下の銘柄を抽出
    【拡張例】東証の PBR 1倍割れ改善要請に対応した銘柄ウォッチ等に活用
    """
    return df[df["pbr"].notna() & (df["pbr"] <= pbr_max)].copy()


def apply_all_screens(
    df: pd.DataFrame,
    per_max: float = 15.0,
    yield_min: float = 5.0,
    pbr_max: Optional[float] = None,
) -> pd.DataFrame:
    """
    複数スクリーニング条件を組み合わせてタグ付きの DataFrame を返す。

    タグ列
    ------
    is_undervalued   : PER 条件
    is_high_dividend : 配当利回り条件
    is_low_pbr       : PBR 条件（pbr_max 指定時のみ）
    label            : 表示用ラベル文字列
    """
    result = df.copy()

    result["is_undervalued"] = (
        result["per"].notna() & (result["per"] <= per_max)
    )
    result["is_high_dividend"] = (
        result["dividend_yield"].notna() & (result["dividend_yield"] >= yield_min)
    )

    # PBR フィルターは任意（将来拡張用）
    if pbr_max is not None:
        result["is_low_pbr"] = (
            result["pbr"].notna() & (result["pbr"] <= pbr_max)
        )
    else:
        result["is_low_pbr"] = False

    # ラベル生成
    def _make_label(row):
        tags = []
        if row["is_undervalued"] and row["is_high_dividend"]:
            return "★ 両方"
        if row["is_undervalued"]:
            tags.append("◆ 割安")
        if row["is_high_dividend"]:
            tags.append("◉ 高配当")
        if row["is_low_pbr"]:
            tags.append("▲ 低PBR")
        return " / ".join(tags) if tags else "-"

    result["label"] = result.apply(_make_label, axis=1)
    return result


# ============================================================
# ② テクニカル指標の計算
# ============================================================

def calculate_technical_indicators(price_df: pd.DataFrame) -> pd.DataFrame:
    """
    株価の時系列 DataFrame にテクニカル指標を追加して返す。

    現在実装済み
    ------------
    - MA5   : 5日移動平均（短期）
    - MA25  : 25日移動平均（中期）
    - MA75  : 75日移動平均（長期）
    - golden_cross : ゴールデンクロス（MA5 > MA25 かつ 前日は MA5 <= MA25）
    - dead_cross   : デッドクロス（MA5 < MA25 かつ 前日は MA5 >= MA25）

    【将来拡張ポイント】
    - MACD         : EMA12 - EMA26 とシグナル線
    - RSI          : 14日 RSI（売買過熱感）
    - Bollinger    : 移動平均 ± 2σ
    以下のように関数末尾に追記するだけで対応可能：

        df["rsi"] = _calc_rsi(df["Close"], period=14)
        df["macd"], df["macd_signal"] = _calc_macd(df["Close"])
    """
    df = price_df.copy()

    # --- 移動平均 ---
    df["MA5"]  = df["Close"].rolling(window=5).mean()
    df["MA25"] = df["Close"].rolling(window=25).mean()
    df["MA75"] = df["Close"].rolling(window=75).mean()

    # --- ゴールデンクロス / デッドクロス ---
    # 前日の MA5 < MA25 → 当日 MA5 > MA25 になったタイミング = ゴールデンクロス
    prev_ma5  = df["MA5"].shift(1)
    prev_ma25 = df["MA25"].shift(1)

    df["golden_cross"] = (df["MA5"] > df["MA25"]) & (prev_ma5 <= prev_ma25)
    df["dead_cross"]   = (df["MA5"] < df["MA25"]) & (prev_ma5 >= prev_ma25)

    # --- 直近シグナルの状態（最新行で判定用）---
    # True : 現在 MA5 > MA25（上昇トレンド）
    df["ma5_above_ma25"] = df["MA5"] > df["MA25"]

    return df


def get_latest_signal(price_df: pd.DataFrame) -> dict:
    """
    calculate_technical_indicators() を実行し、最新のシグナル情報を辞書で返す。
    Streamlit 等で1銘柄のサマリー表示に利用。

    Returns
    -------
    {
        "golden_cross_date": 直近GC発生日 or None,
        "dead_cross_date"  : 直近DC発生日 or None,
        "trend"            : "上昇" / "下降" / "不明",
        "ma5"              : 最新MA5,
        "ma25"             : 最新MA25,
        "ma75"             : 最新MA75,
    }
    """
    if price_df is None or price_df.empty:
        return {}

    df = calculate_technical_indicators(price_df)
    latest = df.iloc[-1]

    gc_dates = df[df["golden_cross"]].index
    dc_dates = df[df["dead_cross"]].index

    return {
        "golden_cross_date": gc_dates[-1].date() if len(gc_dates) > 0 else None,
        "dead_cross_date"  : dc_dates[-1].date() if len(dc_dates) > 0 else None,
        "trend"            : "上昇" if latest.get("ma5_above_ma25") else "下降",
        "ma5"              : latest.get("MA5"),
        "ma25"             : latest.get("MA25"),
        "ma75"             : latest.get("MA75"),
    }


# ============================================================
# ③ 将来拡張用：内部ヘルパー関数（コメントアウト済み）
# ============================================================

def _calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss
    return 100 - (100 / (1 + rs))

def _calc_macd(close: pd.Series, fast=12, slow=26, signal=9):
    ema_fast   = close.ewm(span=fast, adjust=False).mean()
    ema_slow   = close.ewm(span=slow, adjust=False).mean()
    macd       = ema_fast - ema_slow
    macd_signal = macd.ewm(span=signal, adjust=False).mean()
    return macd, macd_signal