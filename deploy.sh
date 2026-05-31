#!/bin/bash

cd /home/tanaka/stock_screener

. venv/bin/activate

pip install -r requirements.txt

pkill -f streamlit || true

nohup streamlit run app.py \
  --server.address 0.0.0.0 \
  --server.port 8501 \
  --server.sslCertFile /home/tanaka/stock_screener/certs/cert.pem \
  --server.sslKeyFile /home/tanaka/stock_screener/certs/key.pem \
  --server.headless true \

