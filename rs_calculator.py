#!/usr/bin/env python3
"""
台股全市場 Minervini RS 計算器
================================
自動從台灣證券交易所抓取所有上市公司清單
計算 RS Score、RS Line、SEPA 條件
輸出 docs/rs_data.json（供 GitHub Pages 使用）

RS Score = Q1×50% + Q2×25% + Q3×15% + Q4×10%
"""

import os
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import json, time, sys, warnings, argparse, pickle, threading, re
from datetime import datetime, timezone, timedelta, date
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict

warnings.filterwarnings("ignore")

# ── 參數 ──────────────────────────────────────────────────────
BENCHMARK   = "^TWII"
WORKERS     = 12        # 並行執行緒
MIN_DAYS    = 252       # 最少交易日（約 1 年）
SLEEP       = 0.15      # 每次下載後等待秒數（降低 rate-limit 風險）
OUTPUT_DIR  = "docs"    # GitHub Pages 預設目錄
OUTPUT_FILE   = f"{OUTPUT_DIR}/rs_data.json"
HISTORY_FILE  = f"{OUTPUT_DIR}/rs_history.json"
CACHE_FILE    = "price_cache.pkl"   # 收盤價快取（不入 git）
HISTORY_DAYS  = 180   # 保留最近幾天
HISTORY_MIN_RS = 50   # 只記錄 RS >= 50 的股票

# ── 收盤價快取 ────────────────────────────────────────────────
_price_cache: dict = {}   # { ticker: pd.Series }
_cache_lock = threading.Lock()

def load_price_cache():
    global _price_cache
    if not __import__("os").path.exists(CACHE_FILE):
        return
    try:
        with open(CACHE_FILE, "rb") as f:
            _price_cache = pickle.load(f)
        print(f"  ✓ 快取載入：{len(_price_cache)} 支股票")
    except Exception as e:
        print(f"  ⚠ 快取讀取失敗，將重新下載：{e}")
        _price_cache = {}

def save_price_cache():
    try:
        with open(CACHE_FILE, "wb") as f:
            pickle.dump(_price_cache, f)
    except Exception as e:
        print(f"  ⚠ 快取儲存失敗：{e}")

# TWSE OpenAPI 產業別代碼 → 自訂板塊
# 來源：openapi.twse.com.tw/v1/opendata/t187ap03_L 的「產業別」欄位
SECTOR_MAP = {
    "01": "建材營造",    # 水泥工業
    "02": "食品",
    "03": "化學",        # 塑膠工業
    "04": "紡織纖維",
    "05": "電機機械",
    "06": "電器電纜",
    "08": "玻璃陶瓷",
    "09": "造紙",
    "10": "鋼鐵",
    "11": "橡膠",
    "12": "汽車",
    "14": "建材營造",
    "15": "航運",
    "16": "觀光餐旅",
    "17": "金融保險",
    "18": "貿易百貨",
    "20": "其他",
    "21": "化學",
    "22": "生技醫療",
    "23": "油電燃氣",
    "24": "半導體",
    "25": "電腦/週邊",
    "26": "光電",
    "27": "通信網路",
    "28": "電子零組件",
    "29": "電子通路",
    "30": "資訊服務",
    "31": "其他電子",
    "35": "綠能環保",
    "36": "數位雲端",
    "37": "運動休閒",
    "38": "居家生活",
    "91": "其他",        # 存託憑證 (DR)
}

# ════════════════════════════════════════════════════════════════
#  Step 1：從證交所抓上市公司清單
# ════════════════════════════════════════════════════════════════
def fetch_twse_listed() -> list[dict]:
    """
    從 TWSE OpenAPI 抓取上市普通股清單（JSON 格式，不需解析 HTML）
    API：https://openapi.twse.com.tw/v1/opendata/t187ap03_L
    回傳 [{"code": "2330", "name": "台積電", "sector": "半導體"}, ...]
    """
    url = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

    print("  📡 連線至 TWSE OpenAPI...")
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  ❌ OpenAPI 抓取失敗：{e}")
        sys.exit(1)

    stocks = []
    for item in data:
        code     = str(item.get("公司代號", "")).strip()
        name     = str(item.get("公司簡稱", "")).strip()
        industry = str(item.get("產業別",   "")).strip()

        # 只保留 4 位數字股票代號（普通股），排除 ETF、KY 股等特殊格式
        if not code.isdigit() or len(code) != 4:
            continue

        # 依 SECTOR_MAP 對應板塊（部分比對）
        sector = "其他"
        for key, val in SECTOR_MAP.items():
            if key in industry:
                sector = val
                break

        # 已發行股數（股）→ 搭配收盤價算市值
        try:
            shares = int(str(item.get("已發行普通股數或TDR原股發行股數", "0")).replace(",", ""))
        except ValueError:
            shares = 0

        stocks.append({"code": code, "name": name, "sector": sector, "shares": shares})

    print(f"  ✓ 取得 {len(stocks)} 檔上市普通股")
    return stocks


# ════════════════════════════════════════════════════════════════
#  Step 2：下載收盤價
# ════════════════════════════════════════════════════════════════
def _fetch_yf(ticker: str, period: str, timeout: int = 20) -> pd.Series | None:
    """直接從 yfinance 下載，回傳 Close Series 或 None。"""
    try:
        df = yf.download(ticker, period=period, auto_adjust=True,
                         progress=False, timeout=timeout)
        if df.empty:
            return None
        close = df["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.squeeze()
        return close.dropna()
    except Exception:
        return None

def download_close(ticker: str, period: str = "580d") -> pd.Series | None:
    today = date.today()

    # ── 1. 快取命中：嘗試增量更新（只補最近幾天）────────────────
    with _cache_lock:
        cached = _price_cache.get(ticker)

    if cached is not None:
        last_date = cached.index[-1].date()
        if last_date >= today:
            return cached if len(cached) >= MIN_DAYS else None

        # 快取有舊資料 → 只補最近 5 天
        new_data = _fetch_yf(ticker, period="5d", timeout=10)
        if new_data is not None and not new_data.empty:
            merged = pd.concat([cached, new_data])
            merged = merged[~merged.index.duplicated(keep="last")].sort_index()
            with _cache_lock:
                _price_cache[ticker] = merged
            return merged if len(merged) >= MIN_DAYS else None

        # 增量失敗 → 直接用舊快取（今天沒收盤也無妨）
        return cached if len(cached) >= MIN_DAYS else None

    # ── 2. 快取不命中：完整下載 ──────────────────────────────────
    for attempt in range(2):
        close = _fetch_yf(ticker, period=period)
        if close is not None and len(close) >= MIN_DAYS:
            with _cache_lock:
                _price_cache[ticker] = close
            return close
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

    raw = q1s*0.5 + q2s*0.25 + q3s*0.15 + q4s*0.10

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

    shares = stock.get("shares", 0)
    if shares and rs_data["price"] > 0:
        mc = shares * rs_data["price"]   # 市值（元）
        if mc >= 100e9:   cap = "大"     # ≥ 1000億
        elif mc >= 10e9:  cap = "中"     # ≥ 100億
        else:             cap = "小"
    else:
        cap = "—"

    return dict(
        code    = code,
        name    = stock["name"],
        sector  = stock["sector"],
        cap     = cap,
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
#  主程式輔助函式
# ════════════════════════════════════════════════════════════════
def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=WORKERS)
    parser.add_argument("--output",  type=str, default=OUTPUT_FILE)
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def load_benchmark() -> pd.Series:
    print(f"\n▶ [1/4] 下載基準指數 {BENCHMARK}...")
    bench = download_close(BENCHMARK)
    if bench is None:
        print("  ❌ 無法下載加權指數，中止")
        sys.exit(1)
    print(f"  ✓ {len(bench)} 筆交易日資料")
    return bench


def run_parallel(stocks: list[dict], bench: pd.Series,
                 workers: int, verbose: bool) -> list[dict]:
    print(f"\n▶ [3/4] 計算 RS（{len(stocks)} 檔 × {workers} 執行緒）...")
    print(f"  預估時間：約 {int(len(stocks) * SLEEP / workers / 60) + 1} 分鐘\n")

    raw_results = []
    done = failed = 0
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(process_stock, s, bench, verbose): s
            for s in stocks
        }
        for future in as_completed(futures):
            done += 1
            result = future.result()
            if result:
                raw_results.append(result)
            else:
                failed += 1

            pct     = done / len(stocks) * 100
            bar     = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
            elapsed = time.time() - start_time
            eta     = elapsed / done * (len(stocks) - done) if done > 0 else 0
            print(f"  [{bar}] {pct:4.0f}%  {done}/{len(stocks)}  "
                  f"成功:{len(raw_results)}  失敗:{failed}  "
                  f"ETA:{int(eta//60)}:{int(eta%60):02d}",
                  end="\r", flush=True)

    elapsed_total = time.time() - start_time
    print(f"\n\n  ✓ 完成，耗時 {int(elapsed_total//60)}分{int(elapsed_total%60)}秒")
    return raw_results


def finalize_results(raw_results: list[dict]) -> list[dict]:
    pcts = raw_to_percentile([r["rs_raw"] for r in raw_results])
    final = []
    for r, rs in zip(raw_results, pcts):
        r["rs"] = rs
        r["sepa_detail"]["rs70"] = rs >= 70
        other = [v for k, v in r["sepa_detail"].items() if k != "rs70"]
        r["sepa"] = r["sepa_detail"]["rs70"] and sum(other) >= 4
        final.append(r)
    final.sort(key=lambda x: x["rs"], reverse=True)
    return final


def write_output(final: list[dict], sectors: list[dict],
                 now: datetime, output_path: str):
    rs90   = sum(1 for r in final if r["rs"] >= 90)
    rs70   = sum(1 for r in final if r["rs"] >= 70)
    sepa_n = sum(1 for r in final if r["sepa"])
    high_n = sum(1 for r in final if r["rsHigh"])
    top    = final[0] if final else {}

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output = dict(
        updated_at = now.strftime("%Y-%m-%d %H:%M"),
        total      = len(final),
        summary    = dict(rs90=rs90, rs70=rs70, sepa=sepa_n, rs_line_high=high_n),
        stocks     = final,
        sectors    = sectors,
    )
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, separators=(",", ":"))

    size_kb = os.path.getsize(output_path) / 1024
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
  ║  輸出檔案 ：{output_path:<28} ║
  ║  檔案大小 ：{size_kb:.0f} KB                     ║
  ╚══════════════════════════════════════╝
""")


def save_history(final: list[dict], now: datetime):
    today = now.strftime("%Y-%m-%d")
    history: dict = {}
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = {}

    for s in final:
        if s["rs"] < HISTORY_MIN_RS:
            continue
        code = s["code"]
        if code not in history:
            history[code] = []
        entries = history[code]
        # 同一天只更新，不重複新增
        if entries and entries[-1]["date"] == today:
            entries[-1]["rs"] = s["rs"]
        else:
            entries.append({"date": today, "rs": s["rs"]})
        # 只保留最近 N 天
        history[code] = entries[-HISTORY_DAYS:]

    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, separators=(",", ":"))
    print(f"  ✓ 歷史記錄已更新：{HISTORY_FILE}（{len(history)} 支股票）")


# ════════════════════════════════════════════════════════════════
#  主程式
# ════════════════════════════════════════════════════════════════
def main():
    args = parse_args()
    tw_tz = timezone(timedelta(hours=8))
    now   = datetime.now(tw_tz)

    print("=" * 62)
    print("  台股全市場 Minervini RS 計算器")
    print(f"  {now.strftime('%Y-%m-%d %H:%M')} (台灣時間)")
    print("=" * 62)

    print(f"\n▶ [0/4] 載入收盤價快取...")
    load_price_cache()

    bench  = load_benchmark()

    print(f"\n▶ [2/4] 抓取上市公司清單...")
    stocks = fetch_twse_listed()

    raw_results = run_parallel(stocks, bench, args.workers, args.verbose)

    save_price_cache()
    print(f"  ✓ 快取已儲存：{len(_price_cache)} 支股票")

    if not raw_results:
        print("  ❌ 沒有任何成功結果，中止")
        sys.exit(1)

    print(f"\n▶ [4/4] 換算百分位、判定 SEPA...")
    final   = finalize_results(raw_results)
    sectors = build_sectors(final)
    write_output(final, sectors, now, args.output)
    save_history(final, now)


if __name__ == "__main__":
    main()
