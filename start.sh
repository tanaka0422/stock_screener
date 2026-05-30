#!/bin/bash
# start.sh
# Termux 起動時に cron と Streamlit を自動起動するスクリプト。
# このスクリプト自身の場所を基準に動くので、どこに置いても動く。

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

# ログディレクトリ作成
mkdir -p "$SCRIPT_DIR/logs"

# cron デーモン起動（すでに動いていても無害）
service cron start 2>/dev/null || true

# Streamlit をバックグラウンドで起動
cd "$SCRIPT_DIR"
source "$SCRIPT_DIR/venv/bin/activate"

nohup streamlit run app.py \
  --server.address 0.0.0.0 \
  --server.port 8501 \
  --server.headless true \
  > "$SCRIPT_DIR/logs/streamlit.log" 2>&1 &

echo "[start.sh] Streamlit started (PID: $!)"
echo "[start.sh] Log: $SCRIPT_DIR/logs/streamlit.log"
