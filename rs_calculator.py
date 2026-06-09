#!/usr/bin/env python3
"""
Taiwan + US Minervini RS Ranking generator.

Outputs:
  docs/rs_data.json
  docs/rs_history.json

Method:
  RS raw = Q1 * 50% + Q2 * 25% + Q3 * 15% + Q4 * 10%
  Q1 = last 63 sessions, Q2 = prior 63, Q3 = prior 63, Q4 = prior 63.
  RS = percentile inside each market. rs_global = percentile across all selected markets.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import os
import re
import sys
import time
import warnings
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import requests
import urllib3
import yfinance as yf


warnings.filterwarnings("ignore")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


OUTPUT_DIR = Path("docs")
OUTPUT_FILE = OUTPUT_DIR / "rs_data.json"
HISTORY_FILE = OUTPUT_DIR / "rs_history.json"

MIN_DAYS = 252
DEFAULT_PERIOD = "620d"
HISTORY_DAYS = 220
HISTORY_MIN_RS = 50

BENCHMARKS = {
    "tw": "^TWII",
    "us": "^GSPC",
}

BENCHMARK_ALTERNATES = {
    "tw": ["^TWII", "0050.TW", "EWT"],
    "us": ["^GSPC", "SPY", "VOO"],
}

MARKET_NAMES = {
    "tw": "台股",
    "us": "美股",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}


TW_SECTOR_MAP = {
    "01": "水泥",
    "02": "食品",
    "03": "塑膠",
    "04": "紡織",
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
    "20": "化學",
    "21": "生技醫療",
    "22": "油電燃氣",
    "23": "半導體",
    "24": "電腦週邊",
    "25": "光電",
    "26": "通信網路",
    "27": "電子零組件",
    "28": "電子通路",
    "29": "資訊服務",
    "30": "其他電子",
    "31": "文化創意",
    "32": "農業科技",
    "33": "農業科技",
    "35": "綠能環保",
    "36": "數位雲端",
    "37": "運動休閒",
    "38": "居家生活",
    "80": "管理股票",
    "91": "存託憑證",
}

US_EXCHANGE_MAP = {
    "Q": "NASDAQ",
    "G": "NASDAQ",
    "S": "NASDAQ",
    "N": "NYSE",
    "A": "NYSEAMERICAN",
    "P": "NYSEARCA",
    "Z": "BATS",
    "V": "IEX",
}

BAD_US_NAME_PATTERNS = re.compile(
    r"\b("
    r"warrant|right|unit|units|preferred|preference|depositary share|"
    r"note due|senior note|debenture|subordinated|contingent value right"
    r")\b",
    re.IGNORECASE,
)


@dataclass
class StockMeta:
    market: str
    code: str
    name: str
    sector: str
    industry: str
    cap: str
    market_cap: float
    shares: int
    yf_symbol: str
    tv_symbol: str
    exchange: str
    currency: str


def parse_int(value: object) -> int:
    text = str(value or "").replace(",", "").replace("$", "").strip()
    if not text or text in {"-", "None", "nan"}:
        return 0
    try:
        return int(float(text))
    except ValueError:
        return 0


def parse_float(value: object) -> float:
    text = str(value or "").replace(",", "").replace("$", "").replace("%", "").strip()
    if not text or text in {"-", "None", "nan"}:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def safe_pct(current: object, base: object) -> float:
    try:
        current_f = float(current)
        base_f = float(base)
        if base_f == 0 or np.isnan(current_f) or np.isnan(base_f):
            return 0.0
        return round((current_f / base_f - 1) * 100, 2)
    except Exception:
        return 0.0


def clean_symbol_for_yahoo(symbol: str) -> str:
    return symbol.strip().replace(".", "-").replace("/", "-")


def get_with_retry(
    url: str,
    *,
    headers: dict | None = None,
    timeout: int = 30,
    verify: bool = True,
    attempts: int = 3,
) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = requests.get(url, headers=headers or HEADERS, timeout=timeout, verify=verify)
            response.raise_for_status()
            return response
        except Exception as exc:
            last_error = exc
            if attempt == attempts:
                break
            wait = attempt * 2
            print(f"  Request failed ({attempt}/{attempts}) for {url}; retrying in {wait}s: {exc}")
            time.sleep(wait)
    raise last_error  # type: ignore[misc]


def json_safe(value: object) -> object:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        value_f = float(value)
        return value_f if math.isfinite(value_f) else None
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    return value


def cap_bucket_tw(market_cap_ntd: float) -> str:
    if market_cap_ntd >= 100_000_000_000:
        return "L"
    if market_cap_ntd >= 10_000_000_000:
        return "M"
    return "S"


def cap_bucket_us(market_cap_usd: float) -> str:
    if market_cap_usd >= 200_000_000_000:
        return "L"
    if market_cap_usd >= 10_000_000_000:
        return "M"
    return "S"


def normalize_market_list(raw: str) -> list[str]:
    markets = [m.strip().lower() for m in raw.split(",") if m.strip()]
    invalid = [m for m in markets if m not in MARKET_NAMES]
    if invalid:
        raise SystemExit(f"Unsupported market(s): {', '.join(invalid)}")
    return list(dict.fromkeys(markets))


def normalize_board_list(raw: str) -> list[str]:
    boards = [b.strip().lower() for b in raw.split(",") if b.strip()]
    invalid = [b for b in boards if b not in {"listed", "otc"}]
    if invalid:
        raise SystemExit(f"Unsupported Taiwan board(s): {', '.join(invalid)}")
    return list(dict.fromkeys(boards))


def fetch_twse_listed() -> list[StockMeta]:
    url = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
    print("Fetching TWSE listed universe...")
    response = get_with_retry(url, headers=HEADERS, timeout=30)
    rows = response.json()

    stocks: list[StockMeta] = []
    for item in rows:
        code = str(item.get("公司代號", "")).strip()
        if not code.isdigit() or len(code) != 4:
            continue
        industry_code = str(item.get("產業別", "")).strip()
        sector = TW_SECTOR_MAP.get(industry_code, "其他")
        shares = parse_int(item.get("已發行普通股數或TDR原股發行股數"))
        name = str(item.get("公司簡稱") or item.get("公司名稱") or code).strip()
        stocks.append(
            StockMeta(
                market="tw",
                code=code,
                name=name,
                sector=sector,
                industry=industry_code,
                cap="S",
                market_cap=0.0,
                shares=shares,
                yf_symbol=f"{code}.TW",
                tv_symbol=f"TWSE:{code}",
                exchange="TWSE",
                currency="TWD",
            )
        )
    print(f"  TWSE: {len(stocks)} symbols")
    return stocks


def fetch_tpex_otc() -> list[StockMeta]:
    url = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"
    print("Fetching TPEx OTC universe...")
    response = get_with_retry(url, headers=HEADERS, timeout=30, verify=False)
    rows = response.json()

    stocks: list[StockMeta] = []
    for item in rows:
        code = str(item.get("SecuritiesCompanyCode", "")).strip()
        if not code.isdigit() or len(code) != 4:
            continue
        industry_code = str(item.get("SecuritiesIndustryCode", "")).strip()
        sector = TW_SECTOR_MAP.get(industry_code, "其他")
        shares = parse_int(item.get("IssueShares"))
        name = str(item.get("CompanyAbbreviation") or item.get("CompanyName") or code).strip()
        stocks.append(
            StockMeta(
                market="tw",
                code=code,
                name=name,
                sector=sector,
                industry=industry_code,
                cap="S",
                market_cap=0.0,
                shares=shares,
                yf_symbol=f"{code}.TWO",
                tv_symbol=f"TPEX:{code}",
                exchange="TPEX",
                currency="TWD",
            )
        )
    print(f"  TPEx OTC: {len(stocks)} symbols")
    return stocks


def fallback_universe_from_existing_data(market: str) -> list[StockMeta]:
    if not OUTPUT_FILE.exists():
        return []
    try:
        data = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []

    stocks: list[StockMeta] = []
    for row in data.get("stocks", []):
        if row.get("market") != market:
            continue
        code = str(row.get("code") or "").strip()
        yf_symbol = str(row.get("yf_symbol") or code).strip()
        if not code or not yf_symbol:
            continue
        stocks.append(
            StockMeta(
                market=market,
                code=code,
                name=str(row.get("name") or code),
                sector=str(row.get("sector") or "Other"),
                industry=str(row.get("industry") or ""),
                cap=str(row.get("cap") or "S"),
                market_cap=float(row.get("market_cap") or 0),
                shares=0,
                yf_symbol=yf_symbol,
                tv_symbol=str(row.get("tv_symbol") or code),
                exchange=str(row.get("exchange") or ""),
                currency=str(row.get("currency") or ("USD" if market == "us" else "TWD")),
            )
        )
    if stocks:
        print(f"  Fallback {MARKET_NAMES.get(market, market)} universe from existing rs_data.json: {len(stocks)} symbols")
    return stocks


def fetch_us_exchange_map() -> dict[str, str]:
    exchange_by_symbol: dict[str, str] = {}

    urls = [
        "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
        "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt",
    ]
    for url in urls:
        try:
            response = get_with_retry(url, headers=HEADERS, timeout=30)
        except Exception as exc:
            print(f"  Warning: exchange map failed for {url}: {exc}")
            continue

        frame = pd.read_csv(io.StringIO(response.text), sep="|")
        frame = frame.dropna(how="all")
        if "Symbol" in frame.columns:
            for _, row in frame.iterrows():
                symbol = str(row.get("Symbol", "")).strip()
                if symbol and symbol != "File Creation Time":
                    exchange_by_symbol[symbol] = "NASDAQ"
        elif "ACT Symbol" in frame.columns:
            for _, row in frame.iterrows():
                symbol = str(row.get("ACT Symbol", "")).strip()
                exchange_code = str(row.get("Exchange", "")).strip()
                if symbol and symbol != "File Creation Time":
                    exchange_by_symbol[symbol] = US_EXCHANGE_MAP.get(exchange_code, exchange_code or "US")
    return exchange_by_symbol


def fetch_us_screener() -> list[StockMeta]:
    url = "https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=25&offset=0&download=true"
    headers = {
        **HEADERS,
        "Origin": "https://www.nasdaq.com",
        "Referer": "https://www.nasdaq.com/market-activity/stocks/screener",
    }
    print("Fetching US listed universe from NASDAQ screener...")
    response = get_with_retry(url, headers=headers, timeout=45)
    payload = response.json()
    rows = payload.get("data", {}).get("rows", [])
    exchange_map = fetch_us_exchange_map()

    stocks: list[StockMeta] = []
    for row in rows:
        symbol = str(row.get("symbol", "")).strip()
        name = str(row.get("name", "")).strip()
        if not symbol or not name:
            continue
        if "^" in symbol or "/" in symbol:
            continue
        if BAD_US_NAME_PATTERNS.search(name):
            continue

        market_cap = parse_float(row.get("marketCap"))
        sector = str(row.get("sector") or "Other").strip() or "Other"
        industry = str(row.get("industry") or "").strip()
        exchange = exchange_map.get(symbol, "US")
        tv_symbol = f"{exchange}:{symbol}" if exchange not in {"US", ""} else symbol
        stocks.append(
            StockMeta(
                market="us",
                code=symbol,
                name=name,
                sector=sector,
                industry=industry,
                cap=cap_bucket_us(market_cap),
                market_cap=market_cap,
                shares=0,
                yf_symbol=clean_symbol_for_yahoo(symbol),
                tv_symbol=tv_symbol,
                exchange=exchange,
                currency="USD",
            )
        )

    stocks.sort(key=lambda s: s.market_cap, reverse=True)
    print(f"  US screener: {len(stocks)} symbols after filters")
    return stocks


def fetch_sp500_symbols() -> set[str]:
    print("Fetching S&P 500 symbol filter from Wikipedia...")
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    response = get_with_retry(url, headers=HEADERS, timeout=30)
    tables = pd.read_html(io.StringIO(response.text))
    frame = tables[0]
    return {clean_symbol_for_yahoo(str(s)) for s in frame["Symbol"].tolist()}


def fetch_universe(args: argparse.Namespace) -> list[StockMeta]:
    markets = normalize_market_list(args.markets)
    universe: list[StockMeta] = []

    if "tw" in markets:
        tw_stocks: list[StockMeta] = []
        boards = normalize_board_list(args.tw_boards)
        try:
            if "listed" in boards:
                tw_stocks.extend(fetch_twse_listed())
            if "otc" in boards:
                try:
                    tw_stocks.extend(fetch_tpex_otc())
                except Exception as exc:
                    print(f"  Warning: TPEx fetch failed, continuing with TWSE only: {exc}")
        except Exception as exc:
            print(f"  Warning: Taiwan universe fetch failed: {exc}")
            tw_stocks = fallback_universe_from_existing_data("tw")
            if not tw_stocks:
                raise
        tw_stocks = dedupe_by_key(tw_stocks, "yf_symbol")
        if args.tw_limit:
            tw_stocks = tw_stocks[: args.tw_limit]
        universe.extend(tw_stocks)

    if "us" in markets:
        try:
            us_stocks = fetch_us_screener()
            if args.us_universe == "sp500":
                sp500 = fetch_sp500_symbols()
                us_stocks = [s for s in us_stocks if s.yf_symbol in sp500]
        except Exception as exc:
            print(f"  Warning: US universe fetch failed: {exc}")
            us_stocks = fallback_universe_from_existing_data("us")
            if not us_stocks:
                raise
        if args.min_us_market_cap:
            us_stocks = [s for s in us_stocks if s.market_cap >= args.min_us_market_cap]
        if args.us_limit:
            us_stocks = us_stocks[: args.us_limit]
        universe.extend(us_stocks)

    universe = dedupe_by_key(universe, "yf_symbol")
    if not universe:
        raise SystemExit("No symbols in selected universe.")

    print(f"Total universe: {len(universe)} symbols")
    return universe


def dedupe_by_key(items: Iterable[StockMeta], attr: str) -> list[StockMeta]:
    out: list[StockMeta] = []
    seen: set[str] = set()
    for item in items:
        key = str(getattr(item, attr))
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def extract_close_from_download(df: pd.DataFrame, symbol: str, chunk_len: int) -> pd.Series | None:
    if df is None or df.empty:
        return None

    try:
        if chunk_len == 1:
            close = df["Close"]
        elif isinstance(df.columns, pd.MultiIndex):
            if (symbol, "Close") in df.columns:
                close = df[(symbol, "Close")]
            elif ("Close", symbol) in df.columns:
                close = df[("Close", symbol)]
            else:
                return None
        else:
            close = df["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.squeeze()
        close = close.dropna()
        return close if len(close) >= MIN_DAYS else None
    except Exception:
        return None


def download_single_price(symbol: str, period: str) -> pd.Series | None:
    for attempt in range(1, 4):
        try:
            df = yf.download(
                tickers=symbol,
                period=period,
                auto_adjust=True,
                progress=False,
                group_by="ticker",
                threads=False,
                timeout=30,
            )
            close = extract_close_from_download(df, symbol, 1)
            if close is not None:
                return close
        except Exception as exc:
            if attempt == 3:
                print(f"  Single download failed for {symbol}: {exc}")
        time.sleep(attempt * 1.5)
    return None


def build_synthetic_benchmark(
    market: str,
    universe: list[StockMeta],
    prices: dict[str, pd.Series],
    max_components: int = 300,
) -> pd.Series | None:
    components: list[pd.Series] = []
    seen: set[str] = set()
    for stock in universe:
        if stock.market != market or stock.yf_symbol in seen:
            continue
        seen.add(stock.yf_symbol)
        close = prices.get(stock.yf_symbol)
        if close is None:
            continue
        close = close.dropna()
        if len(close) < MIN_DAYS:
            continue
        base = close.iloc[0]
        if not base or np.isnan(base):
            continue
        components.append((close / base).rename(stock.yf_symbol))
        if len(components) >= max_components:
            break

    if not components:
        return None

    synthetic = pd.concat(components, axis=1).mean(axis=1).dropna()
    return synthetic if len(synthetic) >= MIN_DAYS else None


def download_prices(symbols: list[str], period: str, chunk_size: int) -> dict[str, pd.Series]:
    prices: dict[str, pd.Series] = {}
    total_chunks = math.ceil(len(symbols) / chunk_size)
    for idx in range(0, len(symbols), chunk_size):
        chunk = symbols[idx : idx + chunk_size]
        chunk_no = idx // chunk_size + 1
        print(f"Downloading prices chunk {chunk_no}/{total_chunks} ({len(chunk)} symbols)...")

        df = pd.DataFrame()
        for attempt in range(2):
            try:
                df = yf.download(
                    tickers=chunk,
                    period=period,
                    auto_adjust=True,
                    progress=False,
                    group_by="ticker",
                    threads=True,
                    timeout=30,
                )
                if not df.empty:
                    break
            except Exception as exc:
                print(f"  yfinance chunk failed on attempt {attempt + 1}: {exc}")
            time.sleep(1.5)

        for symbol in chunk:
            close = extract_close_from_download(df, symbol, len(chunk))
            if close is not None:
                prices[symbol] = close

    missing = [symbol for symbol in symbols if symbol not in prices]
    if missing:
        retry_cap = len(missing) if len(symbols) <= 10 else min(len(missing), 250)
        print(f"Retrying {retry_cap}/{len(missing)} missing symbols individually...")
        for idx, symbol in enumerate(missing[:retry_cap], start=1):
            close = download_single_price(symbol, period)
            if close is not None:
                prices[symbol] = close
            if idx % 50 == 0 or idx == retry_cap:
                print(f"  single retry {idx}/{retry_cap}")

    print(f"Downloaded usable price series: {len(prices)}/{len(symbols)}")
    return prices


def download_benchmarks(
    markets: list[str],
    period: str,
    universe: list[StockMeta],
    prices: dict[str, pd.Series],
) -> dict[str, pd.Series]:
    benchmarks: dict[str, pd.Series] = {}
    for market in markets:
        series = None
        for symbol in BENCHMARK_ALTERNATES.get(market, [BENCHMARKS[market]]):
            print(f"Downloading benchmark {symbol}...")
            series = download_single_price(symbol, period)
            if series is not None:
                print(f"Benchmark {symbol}: {len(series)} bars")
                break
            print(f"  Benchmark unavailable: {symbol}")
        if series is None:
            print(f"Building synthetic benchmark for {MARKET_NAMES.get(market, market)} from downloaded prices...")
            series = build_synthetic_benchmark(market, universe, prices)
        if series is None:
            raise SystemExit(f"Benchmark download failed: {BENCHMARKS[market]}")
        benchmarks[market] = series
        print(f"Benchmark ready for {MARKET_NAMES.get(market, market)}: {len(series)} bars")
    return benchmarks


def quarterly_returns(series: pd.Series) -> dict[str, float]:
    def qpct(end_idx: int, start_idx: int) -> float:
        n = len(series)
        end = min(abs(end_idx), n)
        start = min(abs(start_idx), n)
        return safe_pct(series.iloc[-end], series.iloc[-start])

    return {
        "q1": qpct(1, 63),
        "q2": qpct(63, 126),
        "q3": qpct(126, 189),
        "q4": qpct(189, 252),
    }


def calc_rs_raw(close: pd.Series) -> dict[str, float] | None:
    close = close.dropna()
    if len(close) < MIN_DAYS:
        return None

    q = quarterly_returns(close)
    raw = q["q1"] * 0.50 + q["q2"] * 0.25 + q["q3"] * 0.15 + q["q4"] * 0.10
    c1 = safe_pct(close.iloc[-1], close.iloc[-2]) if len(close) >= 2 else 0.0
    c5 = safe_pct(close.iloc[-1], close.iloc[-6]) if len(close) >= 6 else 0.0
    c1m = safe_pct(close.iloc[-1], close.iloc[-22]) if len(close) >= 22 else 0.0
    c3m = safe_pct(close.iloc[-1], close.iloc[-63]) if len(close) >= 63 else 0.0

    return {
        "rs_raw": round(float(raw), 3),
        "q1": q["q1"],
        "q2": q["q2"],
        "q3": q["q3"],
        "q4": q["q4"],
        "c1": round(c1, 2),
        "c5": round(c5, 2),
        "c1m": round(c1m, 2),
        "c3m": round(c3m, 2),
        "price": round(float(close.iloc[-1]), 2),
    }


def calc_rs_line_high(close: pd.Series, benchmark: pd.Series, window: int = 252) -> bool:
    close_aligned, bench_aligned = close.align(benchmark, join="inner")
    close_aligned = close_aligned.dropna()
    bench_aligned = bench_aligned.dropna()
    if len(close_aligned) < 63 or len(bench_aligned) < 63:
        return False
    rs_line = close_aligned / bench_aligned
    rs_line = rs_line.dropna()
    if rs_line.empty:
        return False
    window = min(window, len(rs_line))
    peak = float(rs_line.rolling(window).max().iloc[-1])
    current = float(rs_line.iloc[-1])
    return current >= peak * 0.999


def check_sepa(close: pd.Series) -> dict[str, bool]:
    close = close.dropna()
    n = len(close)
    checks = {
        "rs70": False,
        "above_150ma": False,
        "above_200ma": False,
        "ma200_up": False,
        "ma150_gt_200": False,
        "near_52w_high": False,
    }
    if n < 200:
        return checks

    price = float(close.iloc[-1])
    ma150_series = close.rolling(150).mean()
    ma200_series = close.rolling(200).mean()
    ma150 = float(ma150_series.iloc[-1])
    ma200 = float(ma200_series.iloc[-1])
    ma200_prev = float(ma200_series.iloc[-22]) if n >= 222 else ma200
    high52 = float(close.rolling(min(252, n)).max().iloc[-1])

    checks["above_150ma"] = price > ma150
    checks["above_200ma"] = price > ma200
    checks["ma200_up"] = ma200 > ma200_prev
    checks["ma150_gt_200"] = ma150 > ma200
    checks["near_52w_high"] = price >= high52 * 0.75
    return checks


def raw_to_percentile(raws: list[float]) -> list[int]:
    if not raws:
        return []
    arr = np.array(raws, dtype=float)
    out: list[int] = []
    for value in arr:
        pct = np.sum(arr <= value) / len(arr) * 98 + 1
        out.append(int(round(pct)))
    return out


def process_results(
    universe: list[StockMeta],
    prices: dict[str, pd.Series],
    benchmarks: dict[str, pd.Series],
) -> list[dict]:
    results: list[dict] = []
    missing = 0
    for stock in universe:
        close = prices.get(stock.yf_symbol)
        if close is None:
            missing += 1
            continue

        rs_data = calc_rs_raw(close)
        if rs_data is None:
            missing += 1
            continue

        price = rs_data["price"]
        market_cap = stock.market_cap
        cap = stock.cap
        if stock.market == "tw" and stock.shares and price:
            market_cap = float(stock.shares) * float(price)
            cap = cap_bucket_tw(market_cap)
        elif stock.market == "us":
            cap = cap_bucket_us(market_cap) if market_cap else stock.cap

        sepa_detail = check_sepa(close)
        rs_high = calc_rs_line_high(close, benchmarks[stock.market])

        results.append(
            {
                "market": stock.market,
                "market_name": MARKET_NAMES[stock.market],
                "code": stock.code,
                "name": stock.name,
                "sector": stock.sector or "Other",
                "industry": stock.industry or "",
                "cap": cap,
                "market_cap": round(market_cap, 0),
                "currency": stock.currency,
                "exchange": stock.exchange,
                "yf_symbol": stock.yf_symbol,
                "tv_symbol": stock.tv_symbol,
                "rs_raw": rs_data["rs_raw"],
                "q1": rs_data["q1"],
                "q2": rs_data["q2"],
                "q3": rs_data["q3"],
                "q4": rs_data["q4"],
                "c1": rs_data["c1"],
                "c5": rs_data["c5"],
                "c1m": rs_data["c1m"],
                "c3m": rs_data["c3m"],
                "price": price,
                "rsHigh": rs_high,
                "sepa_detail": sepa_detail,
            }
        )

    print(f"Processed results: {len(results)} usable, {missing} skipped")
    if not results:
        raise SystemExit("No usable price series. Try a smaller universe or rerun later.")
    return finalize_results(results)


def finalize_results(results: list[dict]) -> list[dict]:
    global_pcts = raw_to_percentile([r["rs_raw"] for r in results])
    for row, pct in zip(results, global_pcts):
        row["rs_global"] = pct

    by_market: dict[str, list[dict]] = defaultdict(list)
    for row in results:
        by_market[row["market"]].append(row)

    for market_rows in by_market.values():
        pcts = raw_to_percentile([r["rs_raw"] for r in market_rows])
        for row, pct in zip(market_rows, pcts):
            row["rs"] = pct
            row["sepa_detail"]["rs70"] = pct >= 70
            technical_passes = [v for k, v in row["sepa_detail"].items() if k != "rs70"]
            row["sepa"] = row["sepa_detail"]["rs70"] and sum(bool(v) for v in technical_passes) >= 4

    results.sort(key=lambda x: (x["rs"], x["rs_global"], x["rs_raw"]), reverse=True)
    return results


def build_sector_flow(results: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in results:
        grouped[(row["market"], row["sector"])].append(row)

    sectors: list[dict] = []
    for (market, sector), rows in grouped.items():
        rs_vals = [r["rs"] for r in rows]
        avg_rs = float(np.mean(rs_vals))
        avg_c5 = float(np.mean([r["c5"] for r in rows]))
        sectors.append(
            {
                "market": market,
                "market_name": MARKET_NAMES[market],
                "name": sector,
                "label": f"{MARKET_NAMES[market]} / {sector}",
                "count": len(rows),
                "avg_rs": round(avg_rs, 1),
                "median_rs": round(float(np.median(rs_vals)), 1),
                "rs90_count": sum(1 for value in rs_vals if value >= 90),
                "rs70_count": sum(1 for value in rs_vals if value >= 70),
                "avg_c1": round(float(np.mean([r["c1"] for r in rows])), 2),
                "avg_c5": round(avg_c5, 2),
                "avg_c1m": round(float(np.mean([r["c1m"] for r in rows])), 2),
                "flow": round(avg_rs, 1),
                "flow5": round(avg_c5 * 40, 1),
                "weeks": [],
            }
        )
    sectors.sort(key=lambda x: (x["avg_rs"], x["count"]), reverse=True)
    return sectors


def summarize(results: list[dict]) -> dict:
    by_market = {}
    for market in MARKET_NAMES:
        rows = [r for r in results if r["market"] == market]
        by_market[market] = {
            "name": MARKET_NAMES[market],
            "total": len(rows),
            "rs90": sum(1 for r in rows if r["rs"] >= 90),
            "rs70": sum(1 for r in rows if r["rs"] >= 70),
            "sepa": sum(1 for r in rows if r["sepa"]),
            "rs_line_high": sum(1 for r in rows if r["rsHigh"]),
        }

    return {
        "rs90": sum(1 for r in results if r["rs"] >= 90),
        "rs70": sum(1 for r in results if r["rs"] >= 70),
        "sepa": sum(1 for r in results if r["sepa"]),
        "rs_line_high": sum(1 for r in results if r["rsHigh"]),
        "by_market": by_market,
    }


def load_history() -> dict:
    if not HISTORY_FILE.exists():
        return {}
    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_history(results: list[dict], now: datetime) -> None:
    today = now.strftime("%Y-%m-%d")
    history = load_history()

    for row in results:
        if row["rs"] < HISTORY_MIN_RS:
            continue
        key = f"{row['market']}:{row['code']}"
        entries = history.setdefault(key, [])
        if entries and entries[-1].get("date") == today:
            entries[-1]["rs"] = row["rs"]
            entries[-1]["rs_global"] = row.get("rs_global")
        else:
            entries.append({"date": today, "rs": row["rs"], "rs_global": row.get("rs_global")})
        history[key] = entries[-HISTORY_DAYS:]

    HISTORY_FILE.write_text(
        json.dumps(json_safe(history), ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"History saved: {HISTORY_FILE} ({len(history)} symbols)")


def history_needs_backfill() -> bool:
    history = load_history()
    if not history:
        return True
    max_len = max((len(entries) for entries in history.values()), default=0)
    return max_len < 2


def build_backfilled_history(
    results: list[dict],
    prices: dict[str, pd.Series],
    benchmarks: dict[str, pd.Series],
    days: int,
) -> dict:
    print(f"Backfilling RS history for last {days} benchmark sessions...")
    by_market: dict[str, list[dict]] = defaultdict(list)
    for row in results:
        by_market[row["market"]].append(row)

    history: dict[str, list[dict]] = {}
    for market, market_rows in by_market.items():
        benchmark = benchmarks.get(market)
        if benchmark is None or benchmark.empty:
            continue
        trade_dates = benchmark.dropna().index[-days:]
        print(f"  {MARKET_NAMES.get(market, market)}: {len(market_rows)} symbols, {len(trade_dates)} dates")

        for idx, trade_date in enumerate(trade_dates, start=1):
            raw_rows: list[tuple[dict, float]] = []
            for row in market_rows:
                close = prices.get(row["yf_symbol"])
                if close is None:
                    continue
                close_slice = close.loc[:trade_date]
                rs_data = calc_rs_raw(close_slice)
                if rs_data is not None:
                    raw_rows.append((row, rs_data["rs_raw"]))

            if not raw_rows:
                continue

            pcts = raw_to_percentile([raw for _, raw in raw_rows])
            date_str = pd.Timestamp(trade_date).strftime("%Y-%m-%d")
            for (row, _), rs in zip(raw_rows, pcts):
                if rs < HISTORY_MIN_RS:
                    continue
                key = f"{row['market']}:{row['code']}"
                history.setdefault(key, []).append(
                    {
                        "date": date_str,
                        "rs": rs,
                    }
                )

            if idx % 20 == 0 or idx == len(trade_dates):
                print(f"    {idx}/{len(trade_dates)} dates")

    return history


def write_history(history: dict) -> None:
    HISTORY_FILE.write_text(
        json.dumps(json_safe(history), ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"History saved: {HISTORY_FILE} ({len(history)} symbols)")


def write_output(results: list[dict], sectors: list[dict], now: datetime, args: argparse.Namespace) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    markets = normalize_market_list(args.markets)
    output = {
        "schema_version": 2,
        "updated_at": now.strftime("%Y-%m-%d %H:%M"),
        "timezone": "Asia/Taipei",
        "total": len(results),
        "markets": {m: {"name": MARKET_NAMES[m], "benchmark": BENCHMARKS[m]} for m in markets},
        "formula": "RS raw = Q1*50% + Q2*25% + Q3*15% + Q4*10%; RS = market percentile",
        "sources": {
            "prices": "yfinance",
            "tw": "TWSE OpenAPI + TPEx OpenAPI",
            "us": "NASDAQ screener + NASDAQ Trader symbol directory",
        },
        "summary": summarize(results),
        "stocks": results,
        "sectors": sectors,
    }
    OUTPUT_FILE.write_text(
        json.dumps(json_safe(output), ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"Data saved: {OUTPUT_FILE} ({OUTPUT_FILE.stat().st_size / 1024:.0f} KB)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Taiwan + US RS ranking JSON for GitHub Pages.")
    parser.add_argument("--markets", default="tw,us", help="Comma-separated markets: tw,us")
    parser.add_argument("--tw-boards", default="listed,otc", help="Taiwan boards: listed,otc")
    parser.add_argument("--us-universe", choices=["all", "sp500"], default="all")
    parser.add_argument("--tw-limit", type=int, default=0, help="Limit Taiwan symbols for testing.")
    parser.add_argument("--us-limit", type=int, default=0, help="Limit US symbols for testing.")
    parser.add_argument("--min-us-market-cap", type=float, default=0, help="Filter US by market cap in USD.")
    parser.add_argument("--period", default=DEFAULT_PERIOD)
    parser.add_argument("--chunk-size", type=int, default=80)
    parser.add_argument("--backfill-history", action="store_true", help="Force rebuilding rs_history.json.")
    parser.add_argument("--history-days", type=int, default=90, help="Benchmark sessions to backfill for RS history.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tw_tz = timezone(timedelta(hours=8))
    now = datetime.now(tw_tz)
    markets = normalize_market_list(args.markets)

    print("=" * 72)
    print("Taiwan + US Minervini RS Ranking")
    print(now.strftime("%Y-%m-%d %H:%M Asia/Taipei"))
    print("=" * 72)

    universe = fetch_universe(args)
    symbols = [stock.yf_symbol for stock in universe]
    prices = download_prices(symbols, period=args.period, chunk_size=args.chunk_size)
    benchmarks = download_benchmarks(markets, args.period, universe, prices)
    results = process_results(universe, prices, benchmarks)
    sectors = build_sector_flow(results)
    write_output(results, sectors, now, args)
    if args.backfill_history or history_needs_backfill():
        history = build_backfilled_history(results, prices, benchmarks, args.history_days)
        write_history(history)
    else:
        save_history(results, now)

    top = results[0]
    print("\nDone")
    print(f"  Total: {len(results)}")
    print(f"  RS>=70: {sum(1 for r in results if r['rs'] >= 70)}")
    print(f"  SEPA: {sum(1 for r in results if r['sepa'])}")
    print(f"  Top: {top['market_name']} {top['code']} {top['name']} RS {top['rs']}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted", file=sys.stderr)
        raise SystemExit(130)
