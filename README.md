# app.py
- Streamlit による日本株スクリーナー UI

- 起動方法:
```
streamlit run app.py
```

- 画面構成:
  1. サイドバー : フィルター設定（PER / 配当利回り / セクター）
  2. サマリーカード : 割安・高配当・両方の件数を表示
  3. スクリーニング結果テーブル
  4. （拡張済み）銘柄詳細タブ : 株価チャート + 移動平均 + クロスシグナル

---
# fetcher.py
- yfinance を使った日本株データ取得層

- フロー:
  1. fetch_prime_tickers_from_jpx()
       └─ JPX公式Excelからプライム銘柄コード一覧を取得（軽量・一瞬）
  2. filter_tickers_by_criteria()
       └─ セクター・時価総額規模でコードを事前絞り込み（yfinance不要）
  3. get_all_stocks()
       └─ 絞り込み後の銘柄だけ yfinance で詳細取得
  4. 日次キャッシュ（pickle）で2回目以降は即座に返す

- 将来拡張ポイント:
  - get_price_history() の period/interval 変更で週足・月足対応
  - J-Quants API や SBI API への差し替えもこのファイルだけで完結

---
# screener.py
- スクリーニングロジックとテクニカル指標の計算層

- 設計思想:
  - 各スクリーニング条件は独立した関数として定義
    → 条件を増やす場合もこのファイルに関数を追加するだけ
  - テクニカル指標（移動平均・クロス系）は calculate_technical_indicators() に集約
    → 将来 MACD / RSI / ボリンジャーバンドなども同じ関数内に追加可能
  - screener.py は「判定ロジック」に集中し、データ取得（fetcher.py）とUI（app.py）に依存しない
