"""
FastAPI Server for Position Sizing and Futures Risk Management System
Mounts REST API and serves Frontend Web UI
"""

import os
from typing import Dict, List, Optional, Any
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend.futures_db import (
    get_all_instruments,
    get_sectors,
    get_clusters,
    FUTURES_INSTRUMENTS
)
from backend.risk_manager import run_portfolio_sizing
from backend.kelly_engine import calculate_kelly, get_drawdown_scaler

app = FastAPI(
    title="Futures Position Sizing & Risk Management System",
    description="Based on 1.md quantitative architecture, Fractional Kelly, and active Chinese commodity futures.",
    version="1.0.0"
)

# Current file directory and frontend static path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend")


class CalculationRequest(BaseModel):
    equity: float = Field(default=1000000.0, ge=10000.0, description="账户总权益 (元)")
    win_rate: Optional[float] = Field(default=None, description="策略胜率 (可选，若不传则由区间中枢决定)")
    win_loss_ratio: Optional[float] = Field(default=None, description="策略盈亏比 (可选，若不传则由区间中枢决定)")
    win_rate_min: Optional[float] = Field(default=0.30, ge=0.05, le=0.95, description="策略胜率下限 (如 30%)")
    win_rate_max: Optional[float] = Field(default=0.40, ge=0.05, le=0.95, description="策略胜率上限 (如 40%)")
    win_loss_min: Optional[float] = Field(default=2.5, ge=0.5, le=20.0, description="盈亏比下限 (如 2.5)")
    win_loss_max: Optional[float] = Field(default=4.0, ge=0.5, le=20.0, description="盈亏比上限 (如 4.0)")
    fractional_multiplier: float = Field(default=0.20, ge=0.05, le=1.0, description="分数凯利乘数 (实战推荐 0.10~0.25)")
    current_drawdown_pct: float = Field(default=0.0, ge=0.0, le=50.0, description="当前账户回撤百分比 (0~50%)")
    selected_symbols: Optional[List[str]] = Field(default=None, description="参与计算的品种代码列表")
    custom_prices: Optional[Dict[str, float]] = Field(default=None, description="自定义最新价格")
    custom_stops: Optional[Dict[str, float]] = Field(default=None, description="自定义止损点数")
    cluster_cap_rate: float = Field(default=0.30, ge=0.10, le=0.60, description="单机制聚类最大开放风险上限率")
    single_asset_cap_rate: float = Field(default=0.15, ge=0.05, le=0.40, description="单品种最大开放风险上限率")


@app.get("/api/health")
def health_check() -> Dict[str, Any]:
    return {"status": "ok", "version": "1.0.0", "message": "Position Sizing Engine is operational."}


from backend.tq_service import get_market_data, get_tq_status, sync_market_data, start_background_sync_scheduler, load_cache_from_disk


@app.on_event("startup")
def startup_event():
    load_cache_from_disk()
    start_background_sync_scheduler()


@app.get("/api/tq/status")
def tq_status_endpoint() -> Dict[str, Any]:
    """Returns TqSdk connection status, reference price info, and data source disclosure."""
    return get_tq_status()


@app.post("/api/tq/refresh")
def tq_refresh_endpoint() -> Dict[str, Any]:
    """Manually triggers refresh of TqSdk quotes, ATR, and jump volatility metrics."""
    try:
        updated = sync_market_data()
        return {"success": True, "count": len(updated), "status": get_tq_status()}
    except Exception as e:
        return {"success": False, "error": str(e), "status": get_tq_status()}


@app.get("/api/instruments")
def list_instruments() -> Dict[str, Any]:
    """Returns database of active Chinese futures contracts enriched with TqSdk market data."""
    raw_instruments = get_all_instruments()
    enriched = []
    for inst in raw_instruments:
        item = dict(inst)
        mkt = get_market_data(item["symbol"])
        if mkt:
            item["pre_close"] = mkt.get("pre_close", item["default_price"])
            item["default_price"] = mkt.get("pre_close", item["default_price"]) # 昨日收盘价当做参考现价
            item["last_price"] = mkt.get("last_price", item["default_price"])
            item["multiplier"] = mkt.get("volume_multiple", item["multiplier"])
            item["tick_size"] = mkt.get("price_tick", item["tick_size"])
            item["typical_atr"] = mkt.get("atr14", item["typical_atr"])
            item["margin_rate"] = mkt.get("margin_rate", item["margin_rate"])
            item["margin_per_lot"] = mkt.get("margin_per_lot", round(item["default_price"] * item["multiplier"] * item["margin_rate"], 2))
            item["close_date"] = mkt.get("close_date", "")
            item["underlying_symbol"] = mkt.get("underlying_symbol", item.get("symbol", ""))
            item["gap_risk_level"] = mkt.get("gap_risk_level", "常规平稳")
            item["gap_risk_tag"] = mkt.get("gap_risk_tag", "normal")
            item["gap_penalty"] = mkt.get("gap_penalty", 1.0)
            item["gap_ratio_pct"] = mkt.get("gap_ratio_pct", 20.0)
            item["max_gap_ratio"] = mkt.get("max_gap_ratio", 0.5)
            item["data_source"] = mkt.get("source", "tqsdk")
        enriched.append(item)

    tq_stat = get_tq_status()
    return {
        "count": len(enriched),
        "instruments": enriched,
        "sectors": get_sectors(),
        "clusters": get_clusters(),
        "tq_status": tq_stat,
        "latest_close_date": tq_stat.get("latest_close_date", "2026-09-15")
    }


@app.post("/api/calculate")
def calculate_sizing(req: CalculationRequest) -> Dict[str, Any]:
    """
    Main calculation endpoint: runs full Kelly, portfolio budgeting,
    effective stops, lot sizing, cluster caps, stress tests, and code export.
    """
    try:
        results = run_portfolio_sizing(
            equity=req.equity,
            win_rate=req.win_rate,
            win_loss_ratio=req.win_loss_ratio,
            win_rate_min=req.win_rate_min,
            win_rate_max=req.win_rate_max,
            win_loss_min=req.win_loss_min,
            win_loss_max=req.win_loss_max,
            fractional_multiplier=req.fractional_multiplier,
            current_drawdown_pct=req.current_drawdown_pct,
            selected_symbols=req.selected_symbols,
            custom_prices=req.custom_prices,
            custom_stops=req.custom_stops,
            cluster_cap_rate=req.cluster_cap_rate,
            single_asset_cap_rate=req.single_asset_cap_rate
        )
        return {"success": True, "data": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Calculation error: {str(e)}")


@app.get("/api/presets")
def get_presets() -> Dict[str, Any]:
    """Returns typical scenario presets matching 1.md and different trading styles."""
    return {
        "presets": [
            {
                "id": "standard_1m",
                "name": "100万 CTA 主力实盘篮子",
                "equity": 1000000.0,
                "win_rate": 0.35,
                "win_loss_ratio": 3.0,
                "fractional_multiplier": 0.20,
                "current_drawdown_pct": 0.0,
                "selected_symbols": [
                    "AG", "JM", "RB", "SA", "FG", "CU", "SN",
                    "AO", "PG", "BR", "LH", "JD", "CJ", "P"
                ],
                "description": "精选 14 个主力活跃品种基准配置，覆盖贵金属、黑色链、有色、能化与生鲜。"
            },
            {
                "id": "defensive_500k",
                "name": "50万稳健防守型 (轻黑色/重农产)",
                "equity": 500000.0,
                "win_rate": 0.38,
                "win_loss_ratio": 2.6,
                "fractional_multiplier": 0.15,
                "current_drawdown_pct": 0.0,
                "selected_symbols": [
                    "AG", "RB", "SA", "M", "P", "Y", "SR", "CF", "MA", "JD"
                ],
                "description": "适合中低风险承受度，降低大合约与强共振黑色敞口，优选农产品与温和化工品。"
            },
            {
                "id": "macro_all_weather_2m",
                "name": "200万全天候全品种量化篮子",
                "equity": 2000000.0,
                "win_rate": 0.33,
                "win_loss_ratio": 3.5,
                "fractional_multiplier": 0.20,
                "current_drawdown_pct": 0.0,
                "selected_symbols": [
                    "AU", "AG", "CU", "AL", "ZN", "SN", "RB", "HC", "I", "JM",
                    "SA", "FG", "SC", "FU", "PG", "MA", "PP", "TA", "M", "P",
                    "CF", "SR", "LH", "LC", "SI"
                ],
                "description": "25 个主力活跃品种大组合，依靠高度机制分散压低组合波动率。"
            },
            {
                "id": "drawdown_circuit_test",
                "name": "回撤熔断压力测试 (-6.5%回撤)",
                "equity": 1000000.0,
                "win_rate": 0.35,
                "win_loss_ratio": 3.0,
                "fractional_multiplier": 0.20,
                "current_drawdown_pct": 6.5,
                "selected_symbols": [
                    "AG", "JM", "RB", "SA", "FG", "CU", "SN", "AO", "PG", "P"
                ],
                "description": "模拟账户遭遇 6.5% 回撤时，迟滞电路自动启动二级防御 (0.60x 杠杆衰减) 的实盘表现。"
            }
        ]
    }


# Static files mount
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/")
    def serve_index():
        index_file = os.path.join(FRONTEND_DIR, "index.html")
        if os.path.exists(index_file):
            return FileResponse(index_file)
        return {"message": "Frontend not found, please check /static directory."}
