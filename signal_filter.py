"""
signal_filter.py
----------------
テクニカルシグナルによる二次フィルタリング層。

【フロー】
  スクリーニング済み DataFrame（PER/PBR/配当条件通過済み）
    └─ find_recent_gc_stocks()
         ├─ SQLite の gc_signals に今日のキャッシュがあれば即返す
         ├─ 各銘柄の価格履歴を取得（3ヶ月分）
         ├─ calculate_technical_indicators() でGC判定
         ├─ GC発生日が cutoff 日以降かチェック
         └─ 結果を SQLite（gc_signals）に保存

【設計思想】
- ファンダメンタル条件で絞り込んだ後に呼び出す想定（対象銘柄を最小化）
- fetcher / screener には依存するが app.py には依存しない
"""

from datetime import date, timedelta
from typing import Callable, Optional

import pandas as pd

import db
from fetcher import get_price_history
from screener import calculate_technical_indicators


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

    db.init_db()

    cached_signals = db.load_gc_signals()
    if cached_signals is not None:
        merged = screened_df.merge(cached_signals, on="code", how="inner")
        return merged.sort_values("gc_days_ago").reset_index(drop=True)

    today = date.today()
    cutoff = today - timedelta(days=days)

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

    if not records:
        return pd.DataFrame()

    result = pd.DataFrame(records).sort_values("gc_days_ago").reset_index(drop=True)
    db.upsert_gc_signals(result)
    return result
