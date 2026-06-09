# 台美股 RS Ranking

這是台股 + 美股版本的 Minervini RS Ranking 靜態網站。  
每日計算結果會輸出到 `docs/rs_data.json`，GitHub Pages 直接服務 `docs/`。

## 功能

- 台股：TWSE 上市 + TPEx 上櫃，價格用 yfinance。
- 美股：NASDAQ screener 股票清單，價格用 yfinance。
- RS Score：`Q1*50% + Q2*25% + Q3*15% + Q4*10%`。
- `RS`：各市場內百分位排名，台股和美股分開排名。
- `Global`：台美股合併後的百分位排名，方便跨市場比較。
- SEPA 條件：RS≥70，加上均線與 52 週位置條件。
- 前端支援市場、市值、RS、板塊、搜尋、排序、TradingView 連結、清單下載。

## 本機測試

```bash
pip install -r requirements.txt

# 小樣本快速測試
python rs_calculator.py --markets tw,us --tw-limit 20 --us-limit 20

# 啟動靜態網站
cd docs
python -m http.server 8000
```

打開：

```text
http://localhost:8000
```

## 正式計算

```bash
python rs_calculator.py --markets tw,us
```

美股全市場檔數多，yfinance 偶爾會 rate limit；如果想先縮小範圍：

```bash
# 只跑 S&P 500
python rs_calculator.py --markets tw,us --us-universe sp500

# 只跑市值 3 億美元以上美股
python rs_calculator.py --markets tw,us --min-us-market-cap 300000000

# 只跑台股
python rs_calculator.py --markets tw

# 只跑美股
python rs_calculator.py --markets us

# 強制重建 90 個交易日 RS 歷史曲線
python rs_calculator.py --markets tw,us --us-universe sp500 --backfill-history --history-days 90
```

## GitHub Pages

1. Repo Settings → Pages。
2. Source 選 GitHub Actions。
3. Actions → `Daily Taiwan US RS Ranking` → Run workflow。

預設排程：

- 台灣時間週一到週五 17:05。
- UTC cron：`5 9 * * 1-5`。

## 專案結構

```text
.
├── .github/workflows/daily_rs.yml
├── docs/
│   ├── index.html
│   ├── app.js
│   ├── style.css
│   ├── rs_data.json
│   └── rs_history.json
├── rs_calculator.py
├── requirements.txt
└── README.md
```

## 注意

本工具僅供研究與學習，不構成投資建議。公開資料源可能延遲、缺漏或暫時限制請求；若 Actions 失敗，通常重跑一次即可。
