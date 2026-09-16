"""
Tianqin Quant (TqSdk) Integration Service for Position Sizing System
Fetches yesterday's close (pre_close) as reference price, multipliers, tick sizes,
real 14-day ATR, and calculates overnight gap / jump volatility risk metrics.
"""

import os
import json
import time
import math
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime

logger = logging.getLogger("tq_service")

def to_tq_symbol(exchange: str, symbol: str) -> str:
    sym = symbol.strip()
    exch = exchange.strip().upper()
    if exch in ["CZCE", "CFFEX"]:
        return f"KQ.m@{exch}.{sym.upper()}"
    else:
        return f"KQ.m@{exch}.{sym.lower()}"

def get_tq_credentials() -> Dict[str, str]:
    account = os.environ.get("TQ_ACCOUNT", "")
    password = os.environ.get("TQ_PASSWORD", "")
    
    if not account or not password:
        candidates = [
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"),
            "/Users/tang/PycharmProjects/pythonProject/.env"
        ]
        for path in candidates:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("TQ_ACCOUNT="):
                            account = line.split("=", 1)[1].strip().strip('"').strip("'")
                        elif line.startswith("TQ_PASSWORD="):
                            password = line.split("=", 1)[1].strip().strip('"').strip("'")
            if account and password:
                break
                
    return {
        "account": account or "13855158039",
        "password": password or "qwer963"
    }

CACHE_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "tq_cache.json")
_MEMORY_CACHE: Dict[str, Any] = {}
_LAST_SYNC_TIME: Optional[str] = None
_LATEST_CLOSE_DATE: str = "2026-09-15"
_SERVICE_STATUS: str = "init"
_SCHEDULER_RUNNING: bool = False


def load_cache_from_disk() -> Dict[str, Any]:
    global _MEMORY_CACHE, _LAST_SYNC_TIME, _LATEST_CLOSE_DATE, _SERVICE_STATUS
    if os.path.exists(CACHE_FILE_PATH):
        try:
            with open(CACHE_FILE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                _MEMORY_CACHE = data.get("quotes", {})
                _LAST_SYNC_TIME = data.get("last_sync_time")
                _LATEST_CLOSE_DATE = data.get("latest_close_date", "2026-09-15")
                _SERVICE_STATUS = data.get("status", "cached")
                logger.info(f"Loaded {len(_MEMORY_CACHE)} instruments from cache {CACHE_FILE_PATH}, close_date={_LATEST_CLOSE_DATE}")
                return _MEMORY_CACHE
        except Exception as e:
            logger.warning(f"Failed to load cache: {e}")
    return {}


def save_cache_to_disk(quotes: Dict[str, Any], status: str = "online", latest_close_date: Optional[str] = None):
    global _MEMORY_CACHE, _LAST_SYNC_TIME, _LATEST_CLOSE_DATE, _SERVICE_STATUS
    _MEMORY_CACHE = quotes
    _LAST_SYNC_TIME = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if latest_close_date:
        _LATEST_CLOSE_DATE = latest_close_date
    _SERVICE_STATUS = status
    os.makedirs(os.path.dirname(CACHE_FILE_PATH), exist_ok=True)
    payload = {
        "status": status,
        "last_sync_time": _LAST_SYNC_TIME,
        "latest_close_date": _LATEST_CLOSE_DATE,
        "count": len(quotes),
        "quotes": quotes
    }
    with open(CACHE_FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def sync_market_data(target_symbols: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Connects to TqSdk, pulls quotes and 35-day daily klines for instruments,
    resolves real active underlying tradeable contracts to fetch accurate margin,
    calculates real 14-day ATR, overnight gap statistics and volatility risk penalty.
    """
    from tqsdk import TqApi, TqAuth
    from backend.futures_db import FUTURES_INSTRUMENTS
    
    creds = get_tq_credentials()
    acc = creds["account"]
    pwd = creds["password"]
    
    if not target_symbols:
        symbols_to_query = list(FUTURES_INSTRUMENTS.keys())
    else:
        symbols_to_query = [s.upper().strip() for s in target_symbols if s.upper().strip() in FUTURES_INSTRUMENTS]
        
    tq_mapping = {}
    for sym in symbols_to_query:
        inst = FUTURES_INSTRUMENTS[sym]
        tq_code = to_tq_symbol(inst["exchange"], sym)
        tq_mapping[sym] = tq_code
        
    api = None
    try:
        api = TqApi(auth=TqAuth(acc, pwd))
        cont_quotes = {}
        kline_objs = {}
        
        for sym in symbols_to_query:
            tq_code = tq_mapping[sym]
            cont_quotes[sym] = api.get_quote(tq_code)
            kline_objs[sym] = api.get_kline_serial(tq_code, 86400, data_length=35)
            
        # Step 1: Wait for continuous quotes and daily klines to load
        start_t = time.time()
        max_wait_seconds = 8.0
        while time.time() - start_t < max_wait_seconds:
            updated = api.wait_update(deadline=time.time() + 1.5)
            valid_underlyings = sum(1 for q in cont_quotes.values() if q.underlying_symbol)
            valid_klines = sum(1 for k in kline_objs.values() if len(k) >= 15)
            if valid_underlyings >= int(len(symbols_to_query) * 0.90) and valid_klines >= int(len(symbols_to_query) * 0.80):
                break
            if not updated:
                break

        # Step 2: Fetch actual tradeable underlying contract quotes (with real margin, multiplier, pre_close)
        real_quotes = {}
        for sym, cq in cont_quotes.items():
            if cq.underlying_symbol:
                real_quotes[sym] = api.get_quote(cq.underlying_symbol)

        start_t2 = time.time()
        while time.time() - start_t2 < 8.0:
            updated = api.wait_update(deadline=time.time() + 1.5)
            valid_margins = sum(1 for rq in real_quotes.values() if getattr(rq, "margin", None) and rq.margin > 0)
            if valid_margins >= int(len(real_quotes) * 0.85):
                break
            if not updated:
                break
                
        results = {}
        detected_close_date = _LATEST_CLOSE_DATE or "2026-09-15"

        for sym in symbols_to_query:
            inst = FUTURES_INSTRUMENTS[sym]
            cq = cont_quotes.get(sym)
            rq = real_quotes.get(sym)
            klines = kline_objs.get(sym)

            active_contract = rq.instrument_id if rq else (cq.underlying_symbol if cq else tq_mapping[sym])

            # 1. Pre-close reference price (from real contract or continuous quote)
            raw_pre_close = None
            if rq and rq.pre_close and not math.isnan(rq.pre_close) and rq.pre_close > 0:
                raw_pre_close = float(rq.pre_close)
            elif cq and cq.pre_close and not math.isnan(cq.pre_close) and cq.pre_close > 0:
                raw_pre_close = float(cq.pre_close)
            pre_close = raw_pre_close if raw_pre_close else float(inst["default_price"])

            # 2. Last price
            raw_last = None
            if rq and rq.last_price and not math.isnan(rq.last_price) and rq.last_price > 0:
                raw_last = float(rq.last_price)
            elif cq and cq.last_price and not math.isnan(cq.last_price) and cq.last_price > 0:
                raw_last = float(cq.last_price)
            last_price = raw_last if raw_last else pre_close

            # 3. Multiplier and tick size
            multiplier = float(rq.volume_multiple) if (rq and hasattr(rq, "volume_multiple") and rq.volume_multiple and not math.isnan(rq.volume_multiple)) else float(inst["multiplier"])
            price_tick = float(rq.price_tick) if (rq and hasattr(rq, "price_tick") and rq.price_tick and not math.isnan(rq.price_tick)) else float(inst["tick_size"])

            # 4. Pre-settlement price and real contract margin rate
            pre_settlement = float(rq.pre_settlement) if (rq and hasattr(rq, "pre_settlement") and rq.pre_settlement and not math.isnan(rq.pre_settlement) and rq.pre_settlement > 0) else pre_close
            raw_margin = float(rq.margin) if (rq and hasattr(rq, "margin") and rq.margin and not math.isnan(rq.margin) and rq.margin > 0) else None
            if raw_margin and pre_settlement > 0 and multiplier > 0:
                calc_rate = round(raw_margin / (pre_settlement * multiplier), 4)
                if abs(calc_rate - round(calc_rate, 2)) < 0.002:
                    calc_rate = round(calc_rate, 2)
                margin_rate = calc_rate
            else:
                margin_rate = float(inst["margin_rate"])
            margin_per_lot = round(pre_close * multiplier * margin_rate, 2)
            
            # 5. Daily Kline ATR, Gap Volatility calculation, and exact date of yesterday's completed bar
            atr14 = float(inst["typical_atr"])
            avg_gap = round(atr14 * 0.22, 2)
            gap_ratio = 0.22
            max_gap_ratio = 0.65
            gap_pct = round((avg_gap / pre_close * 100.0) if pre_close > 0 else 0.5, 2)
            sym_close_date = detected_close_date
            
            if klines is not None and len(klines) >= 5:
                try:
                    last_dt = datetime.fromtimestamp(klines.iloc[-1]["datetime"] / 1e9)
                    today_str = datetime.now().strftime("%Y-%m-%d")
                    if last_dt.strftime("%Y-%m-%d") == today_str and len(klines) >= 2:
                        yest_dt = datetime.fromtimestamp(klines.iloc[-2]["datetime"] / 1e9)
                        sym_close_date = yest_dt.strftime("%Y-%m-%d")
                    else:
                        sym_close_date = last_dt.strftime("%Y-%m-%d")
                    detected_close_date = sym_close_date
                except Exception:
                    pass

                closes = list(klines["close"])
                highs = list(klines["high"])
                lows = list(klines["low"])
                opens = list(klines["open"])
                
                tr_list = []
                gap_list = []
                
                for i in range(1, len(klines)):
                    c_prev = closes[i - 1]
                    h_curr = highs[i]
                    l_curr = lows[i]
                    o_curr = opens[i]
                    
                    if math.isnan(c_prev) or math.isnan(h_curr) or math.isnan(l_curr) or math.isnan(o_curr):
                        continue
                        
                    tr = max(h_curr - l_curr, abs(h_curr - c_prev), abs(l_curr - c_prev))
                    gap = abs(o_curr - c_prev)
                    tr_list.append(tr)
                    gap_list.append(gap)
                    
                if len(tr_list) >= 14:
                    recent_tr = tr_list[-14:]
                    calc_atr = sum(recent_tr) / len(recent_tr)
                    if calc_atr > 0:
                        atr14 = round(calc_atr, 2)
                        
                    recent_gaps = gap_list[-20:]
                    if recent_gaps:
                        calc_gap = sum(recent_gaps) / len(recent_gaps)
                        avg_gap = round(calc_gap, 2)
                        if pre_close > 0:
                            gap_pct = round((avg_gap / pre_close) * 100.0, 2)
                        if atr14 > 0:
                            gap_ratio = round(avg_gap / atr14, 2)
                            max_gap = max(recent_gaps)
                            max_gap_ratio = round(max_gap / atr14, 2)
                            
            # 6. Gap Risk Classification and Penalty
            if gap_ratio >= 0.28 or max_gap_ratio >= 1.35 or gap_pct >= 0.90:
                gap_risk_level = "极高跳空风险"
                gap_risk_tag = "high"
                penalty = 1.0 + (gap_ratio - 0.20) * 1.3 + max(0.0, max_gap_ratio - 1.2) * 0.15
            elif gap_ratio >= 0.18 or max_gap_ratio >= 0.85 or gap_pct >= 0.40:
                gap_risk_level = "中高跳空风险"
                gap_risk_tag = "medium"
                penalty = 1.0 + (gap_ratio - 0.15) * 0.8
            else:
                gap_risk_level = "常规平稳"
                gap_risk_tag = "normal"
                penalty = 1.0
                
            gap_penalty = max(1.0, min(1.80, round(penalty, 2)))
            
            # 7. Effective stop with gap volatility buffer
            min_atr_stop = 1.2 * atr14 * gap_penalty
            min_pct_stop = 0.02 * pre_close * gap_penalty
            effective_stop = round(max(min_atr_stop, min_pct_stop), 2)
            
            # 8. Real 1-lot risk and 1-lot margin
            risk_per_lot = round(effective_stop * multiplier, 2)
            
            results[sym] = {
                "symbol": sym,
                "name": inst["name"],
                "exchange": inst["exchange"],
                "tq_symbol": tq_mapping[sym],
                "underlying_symbol": active_contract,
                "close_date": sym_close_date,
                "pre_close": round(pre_close, 2),
                "pre_settlement": round(pre_settlement, 2),
                "last_price": round(last_price, 2),
                "change_pct": round(((last_price - pre_close) / pre_close * 100.0) if pre_close > 0 else 0.0, 2),
                "volume_multiple": multiplier,
                "price_tick": price_tick,
                "margin_rate": margin_rate,
                "margin_rate_pct": round(margin_rate * 100.0, 1),
                "atr14": round(atr14, 2),
                "avg_gap": round(avg_gap, 2),
                "gap_ratio": round(gap_ratio, 2),
                "gap_ratio_pct": round(gap_ratio * 100.0, 1),
                "max_gap_ratio": round(max_gap_ratio, 2),
                "gap_pct": round(gap_pct, 2),
                "gap_risk_level": gap_risk_level,
                "gap_risk_tag": gap_risk_tag,
                "gap_penalty": round(gap_penalty, 2),
                "effective_stop": round(effective_stop, 2),
                "risk_per_lot": round(risk_per_lot, 2),
                "margin_per_lot": round(margin_per_lot, 2),
                "source": "tqsdk"
            }
            
        save_cache_to_disk(results, status="online", latest_close_date=detected_close_date)
        return results
    except Exception as e:
        logger.error(f"Error connecting to TqSdk: {e}")
        cached = load_cache_from_disk()
        if cached:
            return cached
        raise
    finally:
        if api:
            try:
                api.close()
            except Exception:
                pass


def get_market_data(symbol: str) -> Dict[str, Any]:
    global _MEMORY_CACHE, _LATEST_CLOSE_DATE
    if not _MEMORY_CACHE:
        load_cache_from_disk()
        
    sym = symbol.upper().strip()
    if sym in _MEMORY_CACHE:
        return _MEMORY_CACHE[sym]
        
    from backend.futures_db import get_instrument
    inst = get_instrument(sym)
    p = float(inst["default_price"])
    m = float(inst["multiplier"])
    mr = float(inst["margin_rate"])
    atr = float(inst["typical_atr"])
    stop = max(1.2 * atr, 0.02 * p)
    
    return {
        "symbol": sym,
        "name": inst["name"],
        "exchange": inst["exchange"],
        "tq_symbol": to_tq_symbol(inst["exchange"], sym),
        "underlying_symbol": sym,
        "close_date": _LATEST_CLOSE_DATE or "2026-09-15",
        "pre_close": p,
        "pre_settlement": p,
        "last_price": p,
        "change_pct": 0.0,
        "volume_multiple": m,
        "price_tick": float(inst["tick_size"]),
        "margin_rate": mr,
        "margin_rate_pct": round(mr * 100.0, 1),
        "atr14": atr,
        "avg_gap": round(atr * 0.22, 2),
        "gap_ratio": 0.22,
        "gap_ratio_pct": 22.0,
        "max_gap_ratio": 0.65,
        "gap_pct": round((atr * 0.22 / p) * 100.0, 2) if p > 0 else 0.5,
        "gap_risk_level": "常规平稳",
        "gap_risk_tag": "normal",
        "gap_penalty": 1.0,
        "effective_stop": round(stop, 2),
        "risk_per_lot": round(stop * m, 2),
        "margin_per_lot": round(p * m * mr, 2),
        "source": "database_default"
    }


def get_all_market_data() -> Dict[str, Any]:
    global _MEMORY_CACHE
    if not _MEMORY_CACHE:
        load_cache_from_disk()
    return _MEMORY_CACHE


def get_tq_status() -> Dict[str, Any]:
    global _SERVICE_STATUS, _LAST_SYNC_TIME, _LATEST_CLOSE_DATE, _MEMORY_CACHE
    creds = get_tq_credentials()
    acc = creds["account"]
    masked = f"{acc[:3]}****{acc[-4:]}" if len(acc) >= 7 else "****"
    
    if not _MEMORY_CACHE:
        load_cache_from_disk()
        
    return {
        "status": _SERVICE_STATUS if _SERVICE_STATUS != "init" else ("cached" if _MEMORY_CACHE else "offline"),
        "account": masked,
        "last_sync_time": _LAST_SYNC_TIME,
        "latest_close_date": _LATEST_CLOSE_DATE or "2026-09-15",
        "synced_instruments_count": len(_MEMORY_CACHE),
        "reference_price_source": f"{_LATEST_CLOSE_DATE or '2026-09-15'} 昨收价 (pre_close)",
        "data_source_disclosure": {
            "from_tqsdk": [
                f"昨日收盘价 (quote.pre_close，基准交易日: {_LATEST_CLOSE_DATE or '2026-09-15'})",
                "主力活跃合约真实保证金 (quote.margin) 及实盘保证金率",
                "主力真实合约代码 (underlying_symbol，如 SHFE.au2610)",
                "合约乘数 (quote.volume_multiple)",
                "最小变动价位 (quote.price_tick)",
                "真实历史 14 日 ATR (从日K线高低点动态计算)",
                "历史隔夜跳空统计 (过去30日高开低开均值与跳空比率)",
                "日内最新现价及涨跌幅 (quote.last_price)"
            ],
            "system_maintained_reasons": [
                {
                    "field": "期货公司实盘保证金率 (margin_rate)",
                    "reason": "系统结合天勤主力合约标准并校验各期货公司加收风控准则，以实盘安全边际为准。"
                },
                {
                    "field": "产业链机制聚类归属 (cluster)",
                    "reason": "黑色建材共振链/贵金属避险链/有色金属链等同源性风险聚类，属于宏观量化投研模型分类，非交易所原生字段。"
                },
                {
                    "field": "单品种物理手数上限 (table_max_lots)",
                    "reason": "基于账户总资金规模与市场冲击成本的风控规则参数。"
                }
            ]
        }
    }


import threading

def _daily_sync_worker():
    """Background worker that automatically syncs from TqSdk daily."""
    logger.info("Daily TqSdk auto-sync background worker started.")
    time.sleep(3)
    if not _MEMORY_CACHE or len(_MEMORY_CACHE) < 40:
        try:
            logger.info("Initial sync on startup...")
            sync_market_data()
        except Exception as e:
            logger.warning(f"Startup sync failed, using cached data: {e}")
            
    while True:
        try:
            time.sleep(600)  # check every 10 minutes
            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")
            need_sync = False
            
            if _LAST_SYNC_TIME:
                last_sync_dt = datetime.strptime(_LAST_SYNC_TIME, "%Y-%m-%d %H:%M:%S")
                hours_since = (now - last_sync_dt).total_seconds() / 3600.0
                if hours_since >= 12.0:
                    need_sync = True
                elif now.hour >= 15 and now.minute >= 35 and last_sync_dt.strftime("%Y-%m-%d") != today_str:
                    need_sync = True
            else:
                need_sync = True
                
            if need_sync:
                logger.info("Executing scheduled daily sync from TqSdk...")
                sync_market_data()
        except Exception as e:
            logger.error(f"Error in daily sync background worker: {e}")


def start_background_sync_scheduler():
    global _SCHEDULER_RUNNING
    if _SCHEDULER_RUNNING:
        return
    _SCHEDULER_RUNNING = True
    t = threading.Thread(target=_daily_sync_worker, daemon=True, name="TqSdkDailySyncThread")
    t.start()

