"""
signal_filter.py
----------------
テクニカルシグナルによる二次フィルタリング層。

【フロー】
  スクリーニング済み DataFrame（PER/PBR/配当条件通過済み）
    └─ find_recent_gc_stocks()
         ├─ 各銘柄の価格履歴を取得（3ヶ月分）
         ├─ calculate_technical_indicators() でGC判定
         ├─ GC発生日が cutoff 日以降かチェック
         └─ 結果をキャッシュ（当日 + 銘柄リストのハッシュ）

【設計思想】
- ファンダメンタル条件で絞り込んだ後に呼び出す想定（対象銘柄を最小化）
- fetcher / screener には依存するが app.py には依存しない
"""

import os
import pickle
from datetime import date, timedelta
from typing import Callable, Optional

import pandas as pd

from fetcher import get_price_history, CACHE_DIR
from screener import calculate_technical_indicators

GC_CACHE_FILE = os.path.join(CACHE_DIR, "gc_{date}_{key}.pkl")


def find_recent_gc_stocks(
    screened_df: pd.DataFrame,
    days: int = 7,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> pd.DataFrame:
    """
    スクリーニング済み DataFrame から直近 days 日以内に
    ゴールデンクロス（MA5 > MA25 のクロス）が発生した銘柄を返す。

    Parameters
    ----------
    screened_df       : apply_all_screens() 通過済みの DataFrame
    days              : GC 発生を遡る日数（デフォルト 7 日）
    progress_callback : (current, total, code) を受け取る関数

    Returns
    -------
    pd.DataFrame
        元の列に加えて以下を追加：
        - gc_date     : 直近 GC 発生日（date 型）
        - gc_days_ago : 今日から何日前か（int）
    """
    if screened_df.empty:
        return pd.DataFrame()

    today = date.today()
    cutoff = today - timedelta(days=days)

    key = str(hash(frozenset(screened_df["code"].tolist())))[:8]
    cache_path = GC_CACHE_FILE.format(date=str(today), key=key)
    os.makedirs(CACHE_DIR, exist_ok=True)

    if os.path.exists(cache_path):
        with open(cache_path, "rb") as f:
            return pickle.load(f)

    records = []
    total = len(screened_df)

    for i, (_, row) in enumerate(screened_df.iterrows()):
        code = row["code"]
        if progress_callback:
            progress_callback(i + 1, total, code)

        price_df = get_price_history(code, period="3mo")
        if price_df is None or price_df.empty:
            continue

        tech_df = calculate_technical_indicators(price_df)
        gc_rows = tech_df[tech_df["golden_cross"]]

        if gc_rows.empty:
            continue

        latest_gc_date = gc_rows.index[-1].date()
        if latest_gc_date >= cutoff:
            records.append({
                **row.to_dict(),
                "gc_date"    : latest_gc_date,
                "gc_days_ago": (today - latest_gc_date).days,
            })

    result = pd.DataFrame(records).sort_values("gc_days_ago") if records else pd.DataFrame()

    with open(cache_path, "wb") as f:
        pickle.dump(result, f)

    return result
