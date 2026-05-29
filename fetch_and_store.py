"""
fetch_and_store.py
------------------
cronから呼び出すバッチ取得スクリプト。

実行イメージ:
    python fetch_and_store.py

→ 全プライム銘柄の基本情報を yfinance から取得して SQLite に保存
→ 実行結果を fetch_log に記録
"""

import sys
import traceback

import db
from fetcher import fetch_prime_tickers_from_jpx, get_all_stocks


def main() -> None:
    db.init_db()

    print("[INFO] fetch_and_store: 開始")

    try:
        jpx_df = fetch_prime_tickers_from_jpx()
        if jpx_df.empty:
            msg = "JPX銘柄一覧の取得に失敗しました"
            print(f"[ERROR] {msg}")
            db.log_fetch("error", msg)
            sys.exit(1)

        tickers = jpx_df["code"].tolist()
        print(f"[INFO] 対象銘柄: {len(tickers)} 件")

        # progress をコンソール出力
        def progress(current, total, code):
            if current % 50 == 0 or current == total:
                print(f"[INFO] {current}/{total} ({code})")

        # SQLite チェックをスキップして強制的に yfinance から取得するため
        # get_stock_info を直接呼んでまとめて upsert する
        from fetcher import get_stock_info
        import time

        records = []
        total = len(tickers)
        for i, code in enumerate(tickers):
            progress(i + 1, total, code)
            info = get_stock_info(code)
            if info:
                records.append(info)
            time.sleep(0.4)

        if not records:
            msg = "取得できた銘柄が0件でした"
            print(f"[WARN] {msg}")
            db.log_fetch("error", msg)
            sys.exit(1)

        import pandas as pd
        df = pd.DataFrame(records)
        db.upsert_stocks(df)

        msg = f"{len(records)} 件の銘柄情報を保存しました"
        print(f"[INFO] {msg}")
        db.log_fetch("success", msg)

    except Exception:
        msg = traceback.format_exc()
        print(f"[ERROR] 予期せぬエラー:\n{msg}")
        db.log_fetch("error", msg)
        sys.exit(1)


if __name__ == "__main__":
    main()
