# 📈 台股全市場 RS Ranking

每天台股收盤後自動計算全市場 Minervini RS Score，
結果部署至 GitHub Pages，手機電腦隨時可看。

---

## 📁 專案結構

```
rs-ranking/
├── .github/
│   └── workflows/
│       └── daily_rs.yml       ← GitHub Actions 自動排程
├── docs/
│   ├── index.html             ← 前端介面（GitHub Pages 服務這個）
│   └── rs_data.json           ← 每日自動更新的計算結果
├── rs_calculator.py           ← RS 計算主程式
├── requirements.txt
└── README.md
```

---

## 🚀 三步驟上線

### 步驟一：建立 GitHub Repository

1. 登入 [github.com](https://github.com)
2. 右上角 **+** → **New repository**
3. Repository name：`rs-ranking`
4. 選 **Public**（GitHub Pages 免費方案需公開）
5. 點 **Create repository**

### 步驟二：上傳所有檔案

```bash
# 在你電腦上，進入本專案資料夾
cd rs-ranking

# 初始化 git
git init
git remote add origin https://github.com/你的帳號/rs-ranking.git

# 上傳
git add .
git commit -m "初始化 RS Ranking 系統"
git push -u origin main
```

### 步驟三：開啟 GitHub Pages + Actions

**開啟 GitHub Pages：**
1. 進入 repo → **Settings** → 左側 **Pages**
2. Source 選 **Deploy from a branch**
3. Branch 選 **gh-pages** → 資料夾選 **/ (root)**
4. 點 **Save**

**確認 Actions 權限：**
1. 進入 repo → **Settings** → **Actions** → **General**
2. 滾到底部 **Workflow permissions**
3. 選 **Read and write permissions** → **Save**

**手動觸發第一次計算：**
1. 進入 repo → **Actions** → **每日 RS 排行自動更新**
2. 右側 **Run workflow** → **Run workflow**
3. 等待約 5–8 分鐘

完成後你的網址就是：
```
https://你的帳號.github.io/rs-ranking/
```

---

## ⏰ 自動排程時間

| 觸發時間 | 說明 |
|----------|------|
| 每週一至週五 16:35（台灣時間）| 台股收盤後自動計算 |
| 手動觸發 | Actions 頁面 → Run workflow |

---

## 📊 RS Score 公式

```
RS Score = Q1×40% + Q2×20% + Q3×20% + Q4×20%
```

| 季度 | 說明 | 權重 |
|------|------|------|
| Q1 | 近 3 個月漲幅 | 40% |
| Q2 | 前 4–6 個月漲幅 | 20% |
| Q3 | 前 7–9 個月漲幅 | 20% |
| Q4 | 前 10–12 個月漲幅 | 20% |

最終分數為全市場百分位排名（1–99），RS≥70 才值得關注。

---

## ❓ 常見問題

**Q：Actions 執行失敗怎麼辦？**
→ 進入 Actions 頁面點進失敗的 job，查看 log。最常見是 yfinance rate limit，直接重新手動觸發即可。

**Q：想增加股票？**
→ 程式已自動抓取所有台灣證券交易所上市普通股（約 900+ 檔），無需手動維護。

**Q：想同時追蹤櫃買（OTC）股票？**
→ 修改 `rs_calculator.py` 中 `fetch_twse_listed()`，改 `strMode=4` 即可加入上櫃股票。

**Q：資料多久更新一次？**
→ 每個交易日 16:35 自動執行，假日和例假日不執行。

---

> ⚠️ 本工具僅供學習研究，非投資建議。RS Score 計算基於公開市場資料，不保證準確性。
