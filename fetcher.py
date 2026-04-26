"""
fetcher.py
----------
yfinance を使った日本株データ取得層。

【フロー】
  1. fetch_prime_tickers_from_jpx()
       └─ JPX公式Excelからプライム銘柄コード一覧を取得（軽量・一瞬）
  2. filter_tickers_by_criteria()
       └─ セクター・時価総額規模でコードを事前絞り込み（yfinance不要）
  3. get_all_stocks()
       └─ 絞り込み後の銘柄だけ yfinance で詳細取得
  4. 日次キャッシュ（pickle）で2回目以降は即座に返す

【将来拡張ポイント】
- get_price_history() の period/interval 変更で週足・月足対応
- J-Quants API や SBI API への差し替えもこのファイルだけで完結
"""

import os
import time
import pickle
import urllib.request
from datetime import date
from typing import Optional

import yfinance as yf
import pandas as pd

# -------------------------------------------------------
# キャッシュ設定
# -------------------------------------------------------
CACHE_DIR      = ".cache"
JPX_CACHE_FILE = os.path.join(CACHE_DIR, "jpx_prime_{date}.pkl")   # 銘柄一覧（日次）
STOCK_CACHE_FILE = os.path.join(CACHE_DIR, "stocks_{date}_{key}.pkl")  # 株価情報（日次）

# JPX 上場銘柄一覧 Excel URL
JPX_LIST_URL = (
    "https://www.jpx.co.jp/markets/statistics-equities/misc/"
    "tvdivq0000001vg2-att/data_j.xls"
)

# 時価総額ランク定義（単位: 億円）
MARKET_CAP_RANKS = {
    "大型（1兆円以上）"     : (1_000_000_000_000, None),
    "中型（1000億〜1兆円）" : (100_000_000_000,  1_000_000_000_000),
    "小型（1000億円未満）"  : (None,              100_000_000_000),
}


# ============================================================
# ① JPX から東証プライム銘柄コード一覧を取得
# ============================================================

def fetch_prime_tickers_from_jpx() -> pd.DataFrame:
    """
    JPX公式Excelファイルからプライム銘柄一覧を取得し DataFrame で返す。

    Returns
    -------
    pd.DataFrame
        columns: code（4桁証券コード）, name（銘柄名）, sector33（33業種区分）

    キャッシュ
    ----------
    当日分のキャッシュが存在すればネットワークアクセスなしで即返す。
    """
    today = str(date.today())
    cache_path = JPX_CACHE_FILE.format(date=today)
    os.makedirs(CACHE_DIR, exist_ok=True)

    if os.path.exists(cache_path):
        with open(cache_path, "rb") as f:
            return pickle.load(f)

    print("[INFO] JPX から上場銘柄一覧を取得中...")
    try:
        df = pd.read_excel(JPX_LIST_URL, engine="xlrd", dtype=str)

        # プライム市場のみ抽出
        prime = df[df["市場・商品区分"] == "プライム（内国株式）"].copy()
        prime = prime.rename(columns={
            "コード"    : "code",
            "銘柄名"    : "name",
            "33業種区分": "sector33",
            "17業種区分": "sector17",
        })
        prime["code"] = prime["code"].str.zfill(4)
        result = prime[["code", "name", "sector33", "sector17"]].reset_index(drop=True)

        with open(cache_path, "wb") as f:
            pickle.dump(result, f)

        print(f"[INFO] プライム銘柄 {len(result)} 件取得完了")
        return result

    except Exception as e:
        print(f"[ERROR] JPX一覧取得失敗: {e}")
        return pd.DataFrame(columns=["code", "name", "sector33", "sector17"])


# ============================================================
# ② 事前フィルタリング（yfinance不要・高速）
# ============================================================

def filter_tickers_by_criteria(
    jpx_df: pd.DataFrame,
    sectors: Optional[list[str]] = None,
    max_count: int = 200,
) -> list[str]:
    """
    JPX一覧DataFrame をセクターで絞り込んでコードリストを返す。

    Parameters
    ----------
    jpx_df    : fetch_prime_tickers_from_jpx() の返り値
    sectors   : 絞り込む33業種名のリスト（None = 全業種）
    max_count : 最大取得銘柄数（yfinanceへの負荷上限として使用）

    Notes
    -----
    時価総額によるフィルタは yfinance 取得後に apply_all_screens() で行う。
    JPX の Excel には時価総額が含まれないため、コード段階では業種のみで絞る。
    """
    df = jpx_df.copy()

    if sectors:
        df = df[df["sector33"].isin(sectors)]

    codes = df["code"].tolist()

    if len(codes) > max_count:
        print(f"[INFO] 対象銘柄 {len(codes)} 件 → 上限 {max_count} 件に制限")
        codes = codes[:max_count]

    return codes


def get_sector33_list(jpx_df: pd.DataFrame) -> list[str]:
    """UI のセクター選択肢用に33業種一覧を返す"""
    return sorted(jpx_df["sector33"].dropna().unique().tolist())


# ============================================================
# ③ yfinance による株価情報取得
# ============================================================

def _to_jp_ticker(code: str) -> str:
    """証券コード → yfinance 用ティッカー（例: '7203' → '7203.T'）"""
    return f"{code}.T"


def get_stock_info(code: str) -> Optional[dict]:
    """
    1銘柄の基本情報（PER/PBR/配当利回り等）を取得。
    取得失敗時は None を返す。
    """
    ticker_symbol = _to_jp_ticker(code)
    try:
        ticker = yf.Ticker(ticker_symbol)
        info = ticker.info
        return {
            "code"          : code,
            "name"          : info.get("longName") or info.get("shortName") or code,
            "sector"        : info.get("sector", "不明"),
            "industry"      : info.get("industry", "不明"),
            "price"         : info.get("currentPrice") or info.get("regularMarketPrice"),
            "per"           : info.get("trailingPE"),
            "pbr"           : info.get("priceToBook"),
            "dividend_yield": (info.get("dividendYield") or 0) * 100,  # 小数 → %
            "market_cap"    : info.get("marketCap"),                    # 単位: 円
            "52w_high"      : info.get("fiftyTwoWeekHigh"),
            "52w_low"       : info.get("fiftyTwoWeekLow"),
            # 【拡張予定】EPS / ROE / 営業CF 等をここに追加
        }
    except Exception as e:
        print(f"[WARN] {code} の情報取得失敗: {e}")
        return None


def get_price_history(code: str, period: str = "6mo", interval: str = "1d") -> Optional[pd.DataFrame]:
    """
    株価の時系列データを取得（移動平均・ゴールデンクロス計算に使用）。

    Parameters
    ----------
    period   : '1mo' / '3mo' / '6mo' / '1y' / '2y' など
    interval : '1d'（日足）/ '1wk'（週足）/ '1mo'（月足）
    """
    ticker_symbol = _to_jp_ticker(code)
    try:
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.history(period=period, interval=interval)
        return df if not df.empty else None
    except Exception as e:
        print(f"[WARN] {code} の株価履歴取得失敗: {e}")
        return None


def get_all_stocks(
    tickers: list[str],
    sleep_sec: float = 0.4,
    progress_callback=None,
) -> pd.DataFrame:
    """
    複数銘柄の基本情報をまとめて取得し DataFrame で返す。

    Parameters
    ----------
    tickers           : 証券コードのリスト
    sleep_sec         : API連続アクセスへの配慮（デフォルト 0.4 秒）
    progress_callback : (current, total, code) を受け取る関数（Streamlit進捗表示用）

    キャッシュ
    ----------
    当日 + 同一銘柄リストの組み合わせでキャッシュ保存。
    銘柄リストが変わればキャッシュも別ファイルになる。
    """
    today   = str(date.today())
    # 銘柄リストのハッシュでキャッシュキーを生成（順序非依存）
    key     = str(hash(frozenset(tickers)))[:8]
    cache_path = STOCK_CACHE_FILE.format(date=today, key=key)
    os.makedirs(CACHE_DIR, exist_ok=True)

    if os.path.exists(cache_path):
        print("[INFO] キャッシュから株価データを読み込み中...")
        with open(cache_path, "rb") as f:
            return pickle.load(f)

    records = []
    total   = len(tickers)
    for i, code in enumerate(tickers):
        if progress_callback:
            progress_callback(i + 1, total, code)
        info = get_stock_info(code)
        if info:
            records.append(info)
        time.sleep(sleep_sec)

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)

    with open(cache_path, "wb") as f:
        pickle.dump(df, f)

    return df