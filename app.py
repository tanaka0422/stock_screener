"""
app.py
------
Streamlit による日本株スクリーナー UI。

起動方法:
    streamlit run app.py

【画面構成】
1. サイドバー : フィルター設定（PER / 配当利回り / セクター）
2. サマリーカード : 割安・高配当・両方の件数を表示
3. スクリーニング結果テーブル
4. （拡張済み）銘柄詳細タブ : 株価チャート + 移動平均 + クロスシグナル
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from fetcher import (
    fetch_prime_tickers_from_jpx,
    filter_tickers_by_criteria,
    get_sector33_list,
    get_all_stocks,
    get_price_history,
    MARKET_CAP_RANKS,
)
# ※ DEFAULT_TICKERS は JPX CSV取得方式に移行したため削除済み
from screener import apply_all_screens, calculate_technical_indicators, get_latest_signal
from signal_filter import find_recent_gc_stocks
from watchlist import load_watchlists, add_watchlist, delete_watchlist, list_watchlist_names

# ============================================================
# ページ設定
# ============================================================
st.set_page_config(
    page_title="日本株スクリーナー",
    page_icon="📈",
    layout="wide",
)

st.title("📈 日本株スクリーナー（東証プライム）")
st.caption("JPX公式データ × yfinance による東証プライム銘柄スクリーニングツール（個人利用向け）")

# ============================================================
# Step1: JPX から銘柄一覧を取得（軽量・キャッシュあり）
# ============================================================
@st.cache_data(ttl=86400)   # 1日キャッシュ
def load_jpx():
    return fetch_prime_tickers_from_jpx()

with st.spinner("JPXから銘柄一覧を取得中..."):
    jpx_df = load_jpx()

if jpx_df.empty:
    st.error("JPX銘柄一覧の取得に失敗しました。ネットワーク接続を確認してください。")
    st.stop()

sector33_list = get_sector33_list(jpx_df)

# ============================================================
# サイドバー：フィルター設定
# ============================================================
with st.sidebar:
    st.header("🔧 フィルター設定")

    # --- ⓪ ウォッチリスト読み込み ---
    wl_names = list_watchlist_names()
    if wl_names:
        st.subheader("⓪ ウォッチリスト")
        selected_wl = st.selectbox(
            "保存済み条件を読み込む",
            options=["（選択してください）"] + wl_names,
        )
        col_load, col_del = st.columns(2)
        load_button   = col_load.button("📂 読み込み", use_container_width=True)
        delete_button = col_del.button("🗑 削除",     use_container_width=True)

        if load_button and selected_wl != "（選択してください）":
            from watchlist import get_watchlist
            wl = get_watchlist(selected_wl)
            if wl:
                st.session_state["wl_load"] = wl["conditions"]
                st.rerun()

        if delete_button and selected_wl != "（選択してください）":
            delete_watchlist(selected_wl)
            st.success(f"「{selected_wl}」を削除しました")
            st.rerun()

        st.divider()

    # セッションステートから条件を復元（ウォッチリスト読み込み時）
    _wl = st.session_state.pop("wl_load", None)
    _default_sectors   = _wl["sectors"]    if _wl else []
    _default_max_count = _wl["max_count"]  if _wl else 150
    _default_per_max   = _wl["per_max"]    if _wl else 15.0
    _default_yield_min = _wl["yield_min"]  if _wl else 5.0
    _default_use_pbr   = _wl["use_pbr"]    if _wl else False
    _default_cap       = _wl["cap_filter"] if _wl else "指定なし"

    # --- ① 事前絞り込み（JPX CSV段階・yfinance不要）---
    st.subheader("① 銘柄ユニバース")

    selected_sectors = st.multiselect(
        "業種（33業種）",
        options=sector33_list,
        default=_default_sectors,
        placeholder="未選択 = 全業種対象",
        help="複数選択可。未選択の場合は全業種が対象（取得件数が増えます）",
    )

    max_count = st.slider(
        "最大取得銘柄数",
        min_value=50, max_value=500, value=_default_max_count, step=50,
        help="yfinanceへの負荷を抑えるため上限を設定。業種で絞るほど少なくできます",
    )

    st.divider()

    # --- ② スクリーニング条件 ---
    st.subheader("② スクリーニング条件")

    per_max = st.slider(
        "PER 上限（割安株）",
        min_value=5.0, max_value=50.0, value=_default_per_max, step=0.5,
        help="PER がこの値以下の銘柄を『割安株』として強調表示",
    )

    yield_min = st.slider(
        "配当利回り 下限（高配当株）",
        min_value=1.0, max_value=10.0, value=_default_yield_min, step=0.5,
        help="配当利回りがこの値(%)以上の銘柄を『高配当株』として強調表示",
    )

    use_pbr = st.checkbox("低PBR フィルターを使用（PBR ≤ 1.0）", value=_default_use_pbr)
    pbr_max = 1.0 if use_pbr else None

    # 時価総額フィルター（yfinance取得後に適用）
    cap_options = ["指定なし"] + list(MARKET_CAP_RANKS.keys())
    cap_filter = st.selectbox(
        "時価総額フィルター",
        options=cap_options,
        index=cap_options.index(_default_cap) if _default_cap in cap_options else 0,
    )

    st.divider()

    # --- ③ 取得ボタン ---
    fetch_button = st.button("🔍 スクリーニング開始", type="primary", use_container_width=True)
    st.caption(f"📋 プライム上場銘柄: {len(jpx_df)} 件")

    st.divider()

    # --- ④ ウォッチリスト保存 ---
    st.subheader("④ ウォッチリストに保存")
    wl_name_input = st.text_input("ウォッチリスト名", placeholder="例：高配当・製造業")
    save_button   = st.button("💾 現在の条件を保存", use_container_width=True)

    if save_button:
        if not wl_name_input.strip():
            st.warning("ウォッチリスト名を入力してください")
        else:
            add_watchlist(wl_name_input, {
                "sectors"   : selected_sectors,
                "max_count" : max_count,
                "per_max"   : per_max,
                "yield_min" : yield_min,
                "use_pbr"   : use_pbr,
                "pbr_max"   : pbr_max,
                "cap_filter": cap_filter,
            })
            st.success(f"「{wl_name_input.strip()}」を保存しました")

# ============================================================
# Step2: セッションステートで取得済みデータを保持
# ============================================================
if "raw_df" not in st.session_state:
    st.session_state.raw_df = pd.DataFrame()
if "gc_result" not in st.session_state:
    st.session_state.gc_result = pd.DataFrame()

if fetch_button:
    tickers = filter_tickers_by_criteria(
        jpx_df,
        sectors=selected_sectors if selected_sectors else None,
        max_count=max_count,
    )

    st.info(f"対象銘柄 {len(tickers)} 件のデータを取得します（約 {len(tickers) * 0.4 / 60:.1f} 分）")

    # プログレスバー付きで取得
    progress_bar  = st.progress(0)
    status_text   = st.empty()

    def update_progress(current, total, code):
        pct = current / total
        progress_bar.progress(pct)
        status_text.text(f"取得中... {current}/{total}  ({code})")

    raw_df = get_all_stocks(tickers, progress_callback=update_progress)
    progress_bar.empty()
    status_text.empty()

    st.session_state.raw_df = raw_df

raw_df = st.session_state.raw_df

# 初回（未取得）状態の案内
if raw_df.empty:
    st.info("👈 サイドバーで条件を設定し「スクリーニング開始」を押してください")
    st.stop()

# 時価総額フィルター適用
filtered_base = raw_df.copy()
if cap_filter != "指定なし":
    cap_min, cap_max = MARKET_CAP_RANKS[cap_filter]
    if cap_min:
        filtered_base = filtered_base[filtered_base["market_cap"] >= cap_min]
    if cap_max:
        filtered_base = filtered_base[filtered_base["market_cap"] < cap_max]

# ============================================================
# スクリーニング実行
# ============================================================
df = apply_all_screens(
    filtered_base,
    per_max=per_max,
    yield_min=yield_min,
    pbr_max=pbr_max,
)

# ============================================================
# サマリーカード
# ============================================================
col1, col2, col3, col4 = st.columns(4)
col1.metric("対象銘柄", f"{len(df)} 銘柄")
col2.metric("◆ 割安株",     f"{df['is_undervalued'].sum()} 銘柄",   f"PER ≤ {per_max}")
col3.metric("◉ 高配当株",   f"{df['is_high_dividend'].sum()} 銘柄", f"利回り ≥ {yield_min}%")
col4.metric("★ 両方クリア", f"{(df['is_undervalued'] & df['is_high_dividend']).sum()} 銘柄")

st.divider()

# ============================================================
# タブ構成
# ============================================================
tab_screen, tab_gc, tab_detail = st.tabs(["📋 スクリーニング結果", "🚀 直近GC銘柄", "🔍 銘柄詳細（チャート）"])

# -------- Tab1: スクリーニング結果テーブル --------
with tab_screen:

    # モードフィルター
    mode = st.radio(
        "表示モード",
        ["全表示", "◆ 割安株のみ", "◉ 高配当のみ", "★ 両方クリア"],
        horizontal=True,
    )

    if mode == "◆ 割安株のみ":
        display_df = df[df["is_undervalued"]]
    elif mode == "◉ 高配当のみ":
        display_df = df[df["is_high_dividend"]]
    elif mode == "★ 両方クリア":
        display_df = df[df["is_undervalued"] & df["is_high_dividend"]]
    else:
        display_df = df

    # 表示列の選択・整形
    show_cols = {
        "code"          : "コード",
        "name"          : "銘柄名",
        "sector"        : "セクター",
        "price"         : "株価（円）",
        "per"           : "PER（倍）",
        "pbr"           : "PBR（倍）",
        "dividend_yield": "配当利回り（%）",
        "label"         : "タグ",
    }
    table_df = display_df[list(show_cols.keys())].rename(columns=show_cols)

    # 条件を満たす行をハイライト
    def highlight_rows(row):
        original = display_df[display_df["code"] == row["コード"]].iloc[0]
        if original["is_undervalued"] and original["is_high_dividend"]:
            return ["background-color: #2a1a3a"] * len(row)
        elif original["is_undervalued"]:
            return ["background-color: #2a2210"] * len(row)
        elif original["is_high_dividend"]:
            return ["background-color: #0d2a1a"] * len(row)
        return [""] * len(row)

    st.dataframe(
        table_df.style.apply(highlight_rows, axis=1).format({
            "PER（倍）"       : lambda x: f"{x:.1f}" if pd.notna(x) else "-",
            "PBR（倍）"       : lambda x: f"{x:.2f}" if pd.notna(x) else "-",
            "配当利回り（%）" : lambda x: f"{x:.2f}%" if pd.notna(x) else "-",
            "株価（円）"      : lambda x: f"¥{x:,.0f}" if pd.notna(x) else "-",
        }),
        use_container_width=True,
        height=500,
    )

# -------- Tab2: 直近GC銘柄 --------
with tab_gc:
    st.subheader("🚀 直近ゴールデンクロス銘柄スキャン")

    gc_base = df[df["is_undervalued"] | df["is_high_dividend"]].copy()

    st.info(
        f"ファンダメンタル条件（PER / 配当）を通過した **{len(gc_base)} 銘柄** を対象にGCスキャンします。"
        "　※スクリーニングを先に実行してください。"
    )

    gc_days = st.slider("GC発生を遡る日数", min_value=3, max_value=30, value=7, step=1)
    gc_scan_button = st.button("🔍 GCスキャン開始", type="primary", use_container_width=False)

    if gc_scan_button and not gc_base.empty:
        # キャッシュキーが変わる可能性があるのでリセット
        st.session_state.gc_result = pd.DataFrame()

        gc_progress_bar = st.progress(0)
        gc_status_text  = st.empty()

        def update_gc_progress(current, total, code):
            gc_progress_bar.progress(current / total)
            gc_status_text.text(f"GCスキャン中... {current}/{total}  ({code})")

        gc_found = find_recent_gc_stocks(gc_base, days=gc_days, progress_callback=update_gc_progress)
        gc_progress_bar.empty()
        gc_status_text.empty()
        st.session_state.gc_result = gc_found

    gc_result = st.session_state.gc_result

    if gc_result is not None and not gc_result.empty:
        st.success(f"✅ {len(gc_result)} 銘柄で直近 {gc_days} 日以内のGCを検出")

        gc_show_cols = {
            "code"          : "コード",
            "name"          : "銘柄名",
            "sector"        : "セクター",
            "price"         : "株価（円）",
            "per"           : "PER（倍）",
            "dividend_yield": "配当利回り（%）",
            "label"         : "タグ",
            "gc_date"       : "GC発生日",
            "gc_days_ago"   : "何日前",
        }
        available = [c for c in gc_show_cols if c in gc_result.columns]
        gc_table  = gc_result[available].rename(columns=gc_show_cols)

        st.dataframe(
            gc_table.style.format({
                "PER（倍）"       : lambda x: f"{x:.1f}"  if pd.notna(x) else "-",
                "配当利回り（%）" : lambda x: f"{x:.2f}%" if pd.notna(x) else "-",
                "株価（円）"      : lambda x: f"¥{x:,.0f}" if pd.notna(x) else "-",
                "何日前"          : lambda x: f"{int(x)}日前" if pd.notna(x) else "-",
            }),
            use_container_width=True,
        )
    elif gc_scan_button and gc_base.empty:
        st.warning("スクリーニング結果がありません。先にスクリーニングを実行してください。")
    else:
        st.caption("👆 「GCスキャン開始」を押すとスキャンします。")

# -------- Tab3: 銘柄詳細（チャート + テクニカル） --------
with tab_detail:
    st.subheader("🔍 個別銘柄の株価チャートとテクニカル指標")

    # 銘柄選択
    stock_options = {
        f"{row['code']} - {row['name']}": row['code']
        for _, row in df.iterrows()
    }
    selected_label = st.selectbox("銘柄を選択", list(stock_options.keys()))
    selected_code  = stock_options[selected_label]

    # 期間選択
    period_map = {
        "3ヶ月": "3mo",
        "6ヶ月": "6mo",
        "1年"  : "1y",
        "2年"  : "2y",
    }
    selected_period_label = st.select_slider("期間", options=list(period_map.keys()), value="6ヶ月")
    selected_period = period_map[selected_period_label]

    # 移動平均の表示切り替え
    col_ma, col_vol = st.columns(2)
    with col_ma:
        show_ma = st.multiselect(
            "移動平均線",
            ["MA5（5日）", "MA25（25日）", "MA75（75日）"],
            default=["MA5（5日）", "MA25（25日）"],
        )
    with col_vol:
        show_volume = st.checkbox("出来高を表示", value=True)
        show_cross  = st.checkbox("クロスシグナルを表示", value=True)
        show_rsi    = st.checkbox("RSI（14日）を表示", value=True)
        show_macd   = st.checkbox("MACDを表示", value=True)

    # 株価履歴取得（キャッシュ）
    @st.cache_data(ttl=300)
    def load_history(code, period):
        return get_price_history(code, period=period)

    with st.spinner(f"{selected_label} のチャートを描画中..."):
        price_df = load_history(selected_code, selected_period)

    if price_df is None or price_df.empty:
        st.warning("株価データを取得できませんでした。")
    else:
        tech_df = calculate_technical_indicators(price_df)
        signal  = get_latest_signal(price_df)

        # シグナルサマリー
        s_col1, s_col2, s_col3, s_col4, s_col5, s_col6 = st.columns(6)
        s_col1.metric("トレンド",   signal.get("trend", "-"))
        s_col2.metric("MA5",        f"¥{signal['ma5']:,.0f}"  if signal.get("ma5")  else "-")
        s_col3.metric("MA25",       f"¥{signal['ma25']:,.0f}" if signal.get("ma25") else "-")
        gc_date = signal.get("golden_cross_date")
        dc_date = signal.get("dead_cross_date")
        s_col4.metric(
            "直近MAクロス",
            f"GC: {gc_date}" if gc_date else "GC: なし",
            delta=f"DC: {dc_date}" if dc_date else "DC: なし",
            delta_color="off",
        )
        rsi_val = signal.get("rsi")
        rsi_label = (
            "⚠ 買われすぎ" if rsi_val and rsi_val >= 70
            else "⚠ 売られすぎ" if rsi_val and rsi_val <= 30
            else ""
        )
        s_col5.metric("RSI(14)", f"{rsi_val:.1f}" if rsi_val else "-", delta=rsi_label or None, delta_color="off")
        macd_cross = signal.get("macd_cross")
        s_col6.metric("MACDクロス", macd_cross if macd_cross else "-")

        # ============================================================
        # Plotly チャート描画
        # ============================================================
        panel_weights = [0.5]
        if show_volume: panel_weights.append(0.15)
        if show_rsi:    panel_weights.append(0.175)
        if show_macd:   panel_weights.append(0.175)
        total_w = sum(panel_weights)
        row_heights = [w / total_w for w in panel_weights]
        rows = len(row_heights)

        _row = 2
        vol_row = _row if show_volume else None
        if show_volume: _row += 1
        rsi_row = _row if show_rsi else None
        if show_rsi: _row += 1
        macd_row = _row if show_macd else None

        fig = make_subplots(
            rows=rows, cols=1,
            shared_xaxes=True,
            row_heights=row_heights,
            vertical_spacing=0.03,
        )

        # ローソク足
        fig.add_trace(
            go.Candlestick(
                x=tech_df.index,
                open=tech_df["Open"], high=tech_df["High"],
                low=tech_df["Low"],   close=tech_df["Close"],
                name="株価",
                increasing_line_color="#00ff88",
                decreasing_line_color="#ff4d6d",
            ),
            row=1, col=1,
        )

        # 移動平均線
        ma_config = {
            "MA5（5日）" : ("MA5",  "#ffd700", 1.5),
            "MA25（25日）": ("MA25", "#4a9eff", 1.5),
            "MA75（75日）": ("MA75", "#ff6b9d", 1.5),
        }
        for label, (col, color, width) in ma_config.items():
            if label in show_ma:
                fig.add_trace(
                    go.Scatter(
                        x=tech_df.index, y=tech_df[col],
                        name=label, line=dict(color=color, width=width),
                    ),
                    row=1, col=1,
                )

        # ゴールデンクロス / デッドクロスのマーカー
        if show_cross:
            gc = tech_df[tech_df["golden_cross"]]
            dc = tech_df[tech_df["dead_cross"]]

            if not gc.empty:
                fig.add_trace(
                    go.Scatter(
                        x=gc.index, y=gc["Close"],
                        mode="markers+text",
                        marker=dict(symbol="triangle-up", size=14, color="#ffd700"),
                        text="GC", textposition="top center",
                        name="ゴールデンクロス",
                    ),
                    row=1, col=1,
                )
            if not dc.empty:
                fig.add_trace(
                    go.Scatter(
                        x=dc.index, y=dc["Close"],
                        mode="markers+text",
                        marker=dict(symbol="triangle-down", size=14, color="#ff4d6d"),
                        text="DC", textposition="bottom center",
                        name="デッドクロス",
                    ),
                    row=1, col=1,
                )

        # 出来高バー
        if show_volume:
            colors = [
                "#00ff88" if c >= o else "#ff4d6d"
                for c, o in zip(tech_df["Close"], tech_df["Open"])
            ]
            fig.add_trace(
                go.Bar(
                    x=tech_df.index, y=tech_df["Volume"],
                    name="出来高", marker_color=colors, opacity=0.6,
                ),
                row=vol_row, col=1,
            )

        # RSI
        if show_rsi and "rsi" in tech_df.columns:
            fig.add_trace(
                go.Scatter(
                    x=tech_df.index, y=tech_df["rsi"],
                    name="RSI(14)", line=dict(color="#a78bfa", width=1.5),
                ),
                row=rsi_row, col=1,
            )
            for level, color in [(70, "rgba(255,77,109,0.4)"), (30, "rgba(0,255,136,0.4)")]:
                fig.add_hline(y=level, line_dash="dash", line_color=color, row=rsi_row, col=1)
            fig.update_yaxes(title_text="RSI", range=[0, 100], row=rsi_row, col=1)

        # MACD
        if show_macd and "macd" in tech_df.columns:
            fig.add_trace(
                go.Scatter(
                    x=tech_df.index, y=tech_df["macd"],
                    name="MACD", line=dict(color="#4a9eff", width=1.5),
                ),
                row=macd_row, col=1,
            )
            fig.add_trace(
                go.Scatter(
                    x=tech_df.index, y=tech_df["macd_signal"],
                    name="シグナル", line=dict(color="#ffd700", width=1.5),
                ),
                row=macd_row, col=1,
            )
            hist_colors = [
                "#00ff88" if v >= 0 else "#ff4d6d"
                for v in tech_df["macd_hist"].fillna(0)
            ]
            fig.add_trace(
                go.Bar(
                    x=tech_df.index, y=tech_df["macd_hist"],
                    name="ヒストグラム", marker_color=hist_colors, opacity=0.6,
                ),
                row=macd_row, col=1,
            )
            fig.update_yaxes(title_text="MACD", row=macd_row, col=1)

        fig.update_layout(
            template="plotly_dark",
            xaxis_rangeslider_visible=False,
            height=600,
            margin=dict(l=0, r=0, t=30, b=0),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )

        st.plotly_chart(fig, use_container_width=True)

        # ============================================================
        # 【将来拡張ポイント】
        # ここに RSI / MACD / ボリンジャーバンドの
        # Plotly トレースを追加するだけで対応可能
        # ============================================================

st.divider()
st.caption("⚠️ 本ツールは個人学習目的のものです。投資判断は自己責任でお願いします。")