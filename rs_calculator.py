#!/usr/bin/env python3
"""
台股全市場 Minervini RS 計算器
================================
自動從台灣證券交易所抓取所有上市公司清單
計算 RS Score、RS Line、SEPA 條件
輸出 docs/rs_data.json（供 GitHub Pages 使用）

RS Score = Q1×40% + Q2×20% + Q3×20% + Q4×20%
"""

import yfinance as yf
import pandas as pd
import numpy as np
import requests
import json, time, sys, warnings, argparse
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from io import StringIO

warnings.filterwarnings("ignore")

# ── 參數 ──────────────────────────────────────────────────────
BENCHMARK   = "^TWII"
WORKERS     = 12        # 並行執行緒
MIN_DAYS    = 252       # 最少交易日（約 1 年）
SLEEP       = 0.15      # 每次下載後等待秒數（降低 rate-limit 風險）
OUTPUT_DIR  = "docs"    # GitHub Pages 預設目錄
OUTPUT_FILE = f"{OUTPUT_DIR}/rs_data.json"

# 產業分類對應（證交所中文產業名稱 → 自訂板塊）
SECTOR_MAP = {
    "半導體業":     "半導體",
    "電腦及週邊設備業": "電腦/週邊",
    "光電業":       "光電",
    "通信網路業":   "通信網路",
    "電子零組件業": "電子零組件",
    "電子通路業":   "電子通路",
    "資訊服務業":   "資訊服務",
    "其他電子業":   "其他電子",
    "化學工業":     "化學",
    "生技醫療業":   "生技醫療",
    "鋼鐵工業":     "鋼鐵",
    "橡膠工業":     "橡膠",
    "玻璃陶瓷":     "玻璃陶瓷",
    "造紙工業":     "造紙",
    "食品工業":     "食品",
    "紡織纖維":     "紡織纖維",
    "電機機械":     "電機機械",
    "電器電纜":     "電器電纜",
    "汽車工業":     "汽車",
    "建材營造":     "建材營造",
    "航運業":       "航運",
    "觀光餐旅":     "觀光餐旅",
    "金融保險業":   "金融保險",
    "貿易百貨":     "貿易百貨",
    "油電燃氣業":   "油電燃氣",
    "綠能環保":     "綠能環保",
    "數位雲端":     "數位雲端",
    "運動休閒":     "運動休閒",
    "居家生活":     "居家生活",
    "文化創意業":   "文化創意",
    "其他":         "其他",
}

# ════════════════════════════════════════════════════════════════
#  Step 1：從證交所抓上市公司清單
# ════════════════════════════════════════════════════════════════
def fetch_twse_listed() -> list[dict]:
    """
    從 TWSE ISIN 頁面抓取所有上市普通股清單
    回傳 [{"code": "2330", "name": "台積電", "sector": "半導體"}, ...]
    """
    url = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2"
    headers = {"User-Agent": "Mozilla/5.0"}

    print("  📡 連線至台灣證券交易所...")
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.encoding = "big5"
        tables = pd.read_html(StringIO(resp.text))
        df = tables[0]
    except Exception as e:
        print(f"  ❌ 抓取失敗：{e}")
        sys.exit(1)

    stocks = []
    current_sector = "其他"

    for _, row in df.iterrows():
        cell = str(row.iloc[0]).strip()

        # 偵測產業標頭列（無數字開頭）
        if pd.isna(row.iloc[1]) or str(row.iloc[1]).strip() in ("", "nan"):
            # 這是產業分類列
            for key, val in SECTOR_MAP.items():
                if key in cell:
                    current_sector = val
                    break
            continue

        # 格式：「XXXX　公司名稱」
        parts = cell.split("\u3000")  # 全形空白
        if len(parts) < 2:
            continue
        code = parts[0].strip()
        name = parts[1].strip()

        # 只保留 4 位數字股票代號（普通股），排除 ETF、特別股
        if not code.isdigit() or len(code) != 4:
            continue

        stocks.append({
            "code": code,
            "name": name,
            "sector": current_sector,
        })

    print(f"  ✓ 取得 {len(stocks)} 檔上市普通股")
    return stocks


# ════════════════════════════════════════════════════════════════
#  Step 2：下載收盤價
# ════════════════════════════════════════════════════════════════
def download_close(ticker: str, period: str = "580d") -> pd.Series | None:
    for attempt in range(2):
        try:
            df = yf.download(ticker, period=period, auto_adjust=True,
                             progress=False, timeout=20)
            if df.empty:
                continue
            close = df["Close"]
            if isinstance(close, pd.DataFrame):
                close = close.squeeze()
            close = close.dropna()
            if len(close) >= MIN_DAYS:
                return close
        except Exception:
            if attempt == 0:
                time.sleep(1)
    return None


# ════════════════════════════════════════════════════════════════
#  Step 3：核心計算
# ════════════════════════════════════════════════════════════════
def safe_pct(a, b) -> float:
    try:
        a, b = float(a), float(b)
        if b == 0 or np.isnan(a) or np.isnan(b):
            return 0.0
        return round((a / b - 1) * 100, 2)
    except Exception:
        return 0.0

def calc_rs_raw(s: pd.Series, b: pd.Series) -> dict | None:
    s, b = s.align(b, join="inner")
    s, b = s.dropna(), b.dropna()
    if len(s) < MIN_DAYS:
        return None

    q1 = s.iloc[-1];    q1b = b.iloc[-1]
    q1_60 = s.iloc[-63] if len(s) >= 63 else s.iloc[0]
    b1_60 = b.iloc[-63] if len(b) >= 63 else b.iloc[0]

    def qpct(ser, end_idx, start_idx):
        n = len(ser)
        ei = min(end_idx, n-1)
        si = min(start_idx, n-1)
        return safe_pct(ser.iloc[ei], ser.iloc[si])

    q1s = qpct(s, -1, -63);   q1b_ = qpct(b, -1, -63)
    q2s = qpct(s, -63, -126); q2b_ = qpct(b, -63, -126)
    q3s = qpct(s, -126, -189); q3b_ = qpct(b, -126, -189)
    q4s = qpct(s, -189, -252); q4b_ = qpct(b, -189, -252)

    raw = q1s*0.4 + q2s*0.2 + q3s*0.2 + q4s*0.2

    c1  = safe_pct(s.iloc[-1], s.iloc[-2])  if len(s) >= 2  else 0.0
    c5  = safe_pct(s.iloc[-1], s.iloc[-6])  if len(s) >= 6  else 0.0
    c1m = safe_pct(s.iloc[-1], s.iloc[-22]) if len(s) >= 22 else 0.0
    c3m = safe_pct(s.iloc[-1], s.iloc[-63]) if len(s) >= 63 else 0.0

    return dict(rs_raw=round(raw, 3),
                q1=round(q1s,2), q2=round(q2s,2),
                q3=round(q3s,2), q4=round(q4s,2),
                c1=round(c1,2),  c5=round(c5,2),
                c1m=round(c1m,2), c3m=round(c3m,2),
                price=round(float(s.iloc[-1]), 2))

def calc_rs_line_high(s: pd.Series, b: pd.Series, window: int = 252) -> bool:
    s, b = s.align(b, join="inner")
    s, b = s.dropna(), b.dropna()
    if len(s) < 63:
        return False
    rs_line = s / b
    w = min(window, len(rs_line))
    peak = float(rs_line.rolling(w).max().iloc[-1])
    cur  = float(rs_line.iloc[-1])
    return cur >= peak * 0.999

def check_sepa(close: pd.Series) -> dict:
    n = len(close)
    d = dict(rs70=False, above_150ma=False, above_200ma=False,
             ma200_up=False, ma150_gt_200=False, near_52w_high=False)
    if n < 200:
        return d
    price  = float(close.iloc[-1])
    ma150  = float(close.rolling(150).mean().iloc[-1])
    ma200  = float(close.rolling(200).mean().iloc[-1])
    ma200_prev = float(close.rolling(200).mean().iloc[-22]) if n >= 222 else ma200
    w52    = min(252, n)
    high52 = float(close.rolling(w52).max().iloc[-1])
    d["above_150ma"]   = price > ma150
    d["above_200ma"]   = price > ma200
    d["ma200_up"]      = ma200 > ma200_prev
    d["ma150_gt_200"]  = ma150 > ma200
    d["near_52w_high"] = price >= high52 * 0.75
    return d

def raw_to_percentile(raws: list[float]) -> list[int]:
    arr = np.array(raws, dtype=float)
    result = []
    for v in arr:
        pct = np.sum(arr <= v) / len(arr) * 98 + 1
        result.append(int(round(pct)))
    return result


# ════════════════════════════════════════════════════════════════
#  Step 4：單一股票的完整計算（供多執行緒呼叫）
# ════════════════════════════════════════════════════════════════
def process_stock(stock: dict, bench: pd.Series, verbose: bool = False) -> dict | None:
    code = stock["code"]
    ticker_tw  = f"{code}.TW"
    ticker_two = f"{code}.TWO"

    close = download_close(ticker_tw)
    if close is None:
        close = download_close(ticker_two)
    if close is None:
        if verbose:
            print(f"  ⚠  {code} 資料不足，跳過")
        return None

    rs_data = calc_rs_raw(close, bench)
    if rs_data is None:
        return None

    rs_high  = calc_rs_line_high(close, bench)
    sepa_det = check_sepa(close)

    time.sleep(SLEEP)

    return dict(
        code    = code,
        name    = stock["name"],
        sector  = stock["sector"],
        cap     = stock.get("cap", "—"),
        rs_raw  = rs_data["rs_raw"],
        q1=rs_data["q1"], q2=rs_data["q2"],
        q3=rs_data["q3"], q4=rs_data["q4"],
        c1=rs_data["c1"], c5=rs_data["c5"],
        c1m=rs_data["c1m"], c3m=rs_data["c3m"],
        price   = rs_data["price"],
        rsHigh  = rs_high,
        sepa_detail = sepa_det,
    )


# ════════════════════════════════════════════════════════════════
#  Step 5：板塊彙整
# ════════════════════════════════════════════════════════════════
def build_sectors(results: list[dict]) -> list[dict]:
    grp = defaultdict(list)
    for r in results:
        grp[r["sector"]].append(r)

    out = []
    for sector, items in grp.items():
        rs_vals = [i["rs"] for i in items]
        out.append(dict(
            name    = sector,
            count   = len(items),
            avg_rs  = round(float(np.mean(rs_vals)), 1),
            median_rs = round(float(np.median(rs_vals)), 1),
            rs90_count = sum(1 for r in rs_vals if r >= 90),
            rs70_count = sum(1 for r in rs_vals if r >= 70),
            avg_c1  = round(float(np.mean([i["c1"]  for i in items])), 2),
            avg_c5  = round(float(np.mean([i["c5"]  for i in items])), 2),
            avg_c1m = round(float(np.mean([i["c1m"] for i in items])), 2),
            flow    = round(float(np.mean(rs_vals)) * 1.1, 1),
            flow5   = round(float(np.mean([i["c5"] for i in items])) * 40, 1),
            weeks   = [],  # 歷史週資料保留空白（完整版需逐週計算，耗時較長）
        ))
    out.sort(key=lambda x: x["avg_rs"], reverse=True)
    return out


# ════════════════════════════════════════════════════════════════
#  主程式
# ════════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers",  type=int, default=WORKERS)
    parser.add_argument("--output",   type=str, default=OUTPUT_FILE)
    parser.add_argument("--verbose",  action="store_true")
    args = parser.parse_args()

    tw_tz = timezone(timedelta(hours=8))
    now   = datetime.now(tw_tz)

    print("=" * 62)
    print("  台股全市場 Minervini RS 計算器")
    print(f"  {now.strftime('%Y-%m-%d %H:%M')} (台灣時間)")
    print("=" * 62)

    # ── 基準指數 ─────────────────────────────────────────────
    print(f"\n▶ [1/4] 下載基準指數 {BENCHMARK}...")
    bench = download_close(BENCHMARK)
    if bench is None:
        print("  ❌ 無法下載加權指數，中止")
        sys.exit(1)
    print(f"  ✓ {len(bench)} 筆交易日資料")

    # ── 抓上市公司清單 ────────────────────────────────────────
    print(f"\n▶ [2/4] 抓取上市公司清單...")
    stocks = fetch_twse_listed()

    # ── 並行計算 ──────────────────────────────────────────────
    print(f"\n▶ [3/4] 計算 RS（{len(stocks)} 檔 × {args.workers} 執行緒）...")
    print(f"  預估時間：約 {int(len(stocks) * SLEEP / args.workers / 60) + 1} 分鐘\n")

    raw_results = []
    done = 0
    failed = 0
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(process_stock, s, bench, args.verbose): s
            for s in stocks
        }
        for future in as_completed(futures):
            done += 1
            result = future.result()
            if result:
                raw_results.append(result)
            else:
                failed += 1

            # 進度列
            pct  = done / len(stocks) * 100
            bar  = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
            elapsed = time.time() - start_time
            eta = elapsed / done * (len(stocks) - done) if done > 0 else 0
            print(f"  [{bar}] {pct:4.0f}%  {done}/{len(stocks)}  "
                  f"成功:{len(raw_results)}  失敗:{failed}  "
                  f"ETA:{int(eta//60)}:{int(eta%60):02d}",
                  end="\r", flush=True)

    elapsed_total = time.time() - start_time
    print(f"\n\n  ✓ 完成，耗時 {int(elapsed_total//60)}分{int(elapsed_total%60)}秒")

    if not raw_results:
        print("  ❌ 沒有任何成功結果，中止")
        sys.exit(1)

    # ── 百分位換算 + SEPA 判定 ────────────────────────────────
    print(f"\n▶ [4/4] 換算百分位、判定 SEPA...")

    pcts = raw_to_percentile([r["rs_raw"] for r in raw_results])

    final = []
    for r, rs in zip(raw_results, pcts):
        r["rs"] = rs
        r["sepa_detail"]["rs70"] = rs >= 70
        other = [v for k, v in r["sepa_detail"].items() if k != "rs70"]
        r["sepa"] = r["sepa_detail"]["rs70"] and sum(other) >= 4
        final.append(r)

    final.sort(key=lambda x: x["rs"], reverse=True)

    # ── 板塊彙整 ─────────────────────────────────────────────
    sectors = build_sectors(final)

    # ── 統計 ─────────────────────────────────────────────────
    rs90  = sum(1 for r in final if r["rs"] >= 90)
    rs70  = sum(1 for r in final if r["rs"] >= 70)
    sepa_n = sum(1 for r in final if r["sepa"])
    high_n = sum(1 for r in final if r["rsHigh"])
    top    = final[0] if final else {}

    # ── 輸出 JSON ────────────────────────────────────────────
    import os
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    output = dict(
        updated_at = now.strftime("%Y-%m-%d %H:%M"),
        total      = len(final),
        summary    = dict(rs90=rs90, rs70=rs70, sepa=sepa_n, rs_line_high=high_n),
        stocks     = final,
        sectors    = sectors,
    )
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, separators=(",", ":"))

    size_kb = os.path.getsize(args.output) / 1024

    print(f"""
  ╔══════════════════════════════════════╗
  ║        計算完成 ✅                   ║
  ╠══════════════════════════════════════╣
  ║  計算總數  ：{len(final):<5} 檔               ║
  ║  RS ≥ 90  ：{rs90:<5} 檔               ║
  ║  RS ≥ 70  ：{rs70:<5} 檔               ║
  ║  SEPA 入選：{sepa_n:<5} 檔               ║
  ║  RS線新高 ：{high_n:<5} 檔               ║
  ║  🏆 最強  ：{top.get('code','')} {top.get('name',''):<8} RS {top.get('rs','')}    ║
  ║  輸出檔案 ：{args.output:<28} ║
  ║  檔案大小 ：{size_kb:.0f} KB                     ║
  ╚══════════════════════════════════════╝
""")


if __name__ == "__main__":
    main()
