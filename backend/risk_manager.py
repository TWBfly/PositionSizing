"""
Risk Management and Multi-Layer Position Sizing Engine
Implements the 5-layer and 12-layer architecture from 1.md:
- R-Risk Unit standardization
- Effective ATR-based Stop Sizing
- Mechanism Clustering & Cluster Risk Caps (ferrous+glass chain protection)
- Single Instrument Risk Caps
- Dynamic Margin Utilization Bounds (25%~35% normal, 40% hard cap)
- Drawdown Hysteresis Circuit Breaker
- Multi-Scenario Stress Testing
- Code Generation for TBQuant and Python CTA engines
"""

from typing import Dict, List, Any, Optional
import math
from backend.futures_db import FUTURES_INSTRUMENTS, get_instrument, get_clusters
from backend.kelly_engine import calculate_kelly, calculate_kelly_range, get_drawdown_scaler


# Cluster Risk Budgets (Weights of portfolio risk budget allocated to each cluster)
DEFAULT_CLUSTER_WEIGHTS = {
    "ferrous_construction": 0.25,  # 黑色+纯碱玻璃建材链 (严格限顶 25%~30%)
    "precious_metals": 0.18,       # 贵金属 (黄金白银)
    "base_metals": 0.20,           # 有色金属 (铜铝锌锡镍等)
    "energy_chemicals": 0.17,      # 能源化工 (原油/燃油/塑料/甲醇等)
    "agri_oils_softs": 0.15,       # 农产品/油脂/生猪
    "new_energy_special": 0.05,    # 碳酸锂/集运欧线
    "financial": 0.00,             # 默认商品池不配置金融期货，若选中则动态分配
    "other": 0.05
}


def _solve_single_scenario_allocation(
    eq: float,
    p: float,
    b: float,
    k_frac: float,
    dd_scaler: float,
    selected_symbols: List[str],
    cluster_instruments: Dict[str, List[str]],
    normalized_cluster_weights: Dict[str, float],
    items_meta: Dict[str, Dict[str, Any]],
    cluster_cap_rate: float,
    single_asset_cap_rate: float,
    soft_margin_cap: float,
) -> Dict[str, Any]:
    """
    Computes position sizing, consumed margin, and portfolio risk for a single (p, b) scenario.
    """
    q = 1.0 - p
    exp_r = (p * b) - q
    if exp_r <= 0:
        return {
            "win_rate": p,
            "win_loss": b,
            "expectancy_r": exp_r,
            "f_star": 0.0,
            "f_safe": 0.0,
            "safe_kelly_pct": 0.0,
            "active_risk": 0.0,
            "risk_budget": 0.0,
            "margin": 0.0,
            "risk": 0.0,
            "lots": {s: 0 for s in selected_symbols}
        }

    f_star = exp_r / b
    f_safe = f_star * k_frac
    active_risk = eq * min(0.08, f_safe) * dd_scaler

    cluster_budgets = {
        c: active_risk * normalized_cluster_weights.get(c, 0.05)
        for c in cluster_instruments
    }

    lots: Dict[str, int] = {}
    raw_risk_lots: Dict[str, float] = {}
    for sym in selected_symbols:
        meta = items_meta[sym]
        c_id = meta["cluster"]
        c_items = cluster_instruments.get(c_id, [sym])
        inst_cluster_budget = cluster_budgets.get(c_id, active_risk / len(selected_symbols))
        base_risk_allocated = inst_cluster_budget / max(1, len(c_items))
        if active_risk <= 0 or meta["risk_per_lot"] <= 0:
            risk_lots = 0
            raw_risk = 0.0
        else:
            target_risk_amount = base_risk_allocated * meta["vol_scaler"]
            raw_risk = round(target_risk_amount / meta["risk_per_lot"], 2)
            risk_lots = int(math.floor(target_risk_amount / meta["risk_per_lot"]))

        cand_lots = min(risk_lots, meta["table_max_lots"], meta["margin_lots"])
        lots[sym] = max(0, cand_lots)
        raw_risk_lots[sym] = raw_risk

    # If all 0 lots but active_risk > 0, give 1 lot to lowest risk instrument
    if sum(lots.values()) == 0 and active_risk > 0:
        affordable_candidates = sorted(selected_symbols, key=lambda s: items_meta[s]["risk_per_lot"])
        rem_risk = active_risk
        rem_margin = soft_margin_cap
        for s in affordable_candidates:
            r_l = items_meta[s]["risk_per_lot"]
            m_l = items_meta[s]["margin_per_lot"]
            if r_l <= rem_risk and m_l <= rem_margin:
                lots[s] = 1
                rem_risk -= r_l
                rem_margin -= m_l
                if rem_risk <= 0:
                    break

    # Greedy saturation loop (5 passes)
    current_total_risk = sum(lots[s] * items_meta[s]["risk_per_lot"] for s in selected_symbols)
    current_total_margin = sum(lots[s] * items_meta[s]["margin_per_lot"] for s in selected_symbols)

    for _ in range(25):
        changed = False
        candidates = sorted(selected_symbols, key=lambda s: (lots[s] > 0, items_meta[s]["risk_per_lot"]))
        for s in candidates:
            meta = items_meta[s]
            r_l = meta["risk_per_lot"]
            m_l = meta["margin_per_lot"]
            if current_total_risk + r_l > active_risk:
                continue
            if current_total_margin + m_l > soft_margin_cap:
                continue
            if lots[s] >= meta["table_max_lots"]:
                continue
            c_id = meta["cluster"]
            c_items = cluster_instruments.get(c_id, [s])
            c_current_risk = sum(lots[x] * items_meta[x]["risk_per_lot"] for x in c_items)
            eff_cluster_cap = max(active_risk * cluster_cap_rate, r_l)
            if (c_current_risk + r_l) > (eff_cluster_cap + 1.0) and c_current_risk > 0:
                continue
            eff_single_cap = max(active_risk * single_asset_cap_rate, r_l)
            if (lots[s] + 1) * r_l > (eff_single_cap + 1.0) and lots[s] > 0:
                continue
            lots[s] += 1
            current_total_risk += r_l
            current_total_margin += m_l
            changed = True
        if not changed:
            break

    # Hard constraints: single asset cap
    base_single_cap = active_risk * single_asset_cap_rate
    for s in selected_symbols:
        meta = items_meta[s]
        max_single_risk = max(base_single_cap, meta["risk_per_lot"])
        if active_risk > 0 and (lots[s] * meta["risk_per_lot"]) > max_single_risk:
            allowed_lots = int(math.floor(max_single_risk / max(1.0, meta["risk_per_lot"])))
            lots[s] = max(0, min(lots[s], allowed_lots))

    # Cluster risk cap
    for c_id, syms in cluster_instruments.items():
        c_risk = sum(lots[s] * items_meta[s]["risk_per_lot"] for s in syms)
        min_cluster_lot_risk = min((items_meta[s]["risk_per_lot"] for s in syms), default=0.0)
        eff_cluster_risk_cap = max(active_risk * cluster_cap_rate, min(active_risk, min_cluster_lot_risk))
        while c_risk > eff_cluster_risk_cap:
            cands = [s for s in syms if lots[s] > 0]
            if len(cands) <= 1:
                break
            highest_s = max(cands, key=lambda s: items_meta[s]["risk_per_lot"])
            lots[highest_s] -= 1
            c_risk -= items_meta[highest_s]["risk_per_lot"]

    # Margin cap
    total_margin = sum(lots[s] * items_meta[s]["margin_per_lot"] for s in selected_symbols)
    while total_margin > soft_margin_cap and sum(lots.values()) > 0:
        cands = [s for s in selected_symbols if lots[s] > 0]
        highest_m = max(cands, key=lambda s: items_meta[s]["margin_per_lot"])
        lots[highest_m] -= 1
        total_margin -= items_meta[highest_m]["margin_per_lot"]

    final_margin = sum(lots[s] * items_meta[s]["margin_per_lot"] for s in selected_symbols)
    final_risk = sum(lots[s] * items_meta[s]["risk_per_lot"] for s in selected_symbols)

    return {
        "win_rate": p,
        "win_loss": b,
        "expectancy_r": exp_r,
        "f_star": f_star,
        "f_safe": f_safe,
        "safe_kelly_pct": f_safe * 100.0,
        "active_risk": active_risk,
        "risk_budget": active_risk,
        "margin": final_margin,
        "risk": final_risk,
        "lots": lots,
        "raw_risk_lots": raw_risk_lots
    }


def build_empty_portfolio_result(
    eq: float,
    kelly_res: Dict[str, Any],
    kelly_range_res: Dict[str, Any],
    dd_info: Dict[str, Any],
    fractional_multiplier: float,
    p_min: float, p_max: float, b_min: float, b_max: float
) -> Dict[str, Any]:
    """Generates a clean, zeroed-out state when zero symbols are selected."""
    from backend.tq_service import get_tq_status
    p_mid = round((p_min + p_max) / 2.0, 4)
    scenarios = [
        (p_min, b_min), (p_min, b_max),
        (p_mid, b_min), (p_mid, b_max),
        (p_max, b_min), (p_max, b_max)
    ]
    scenario_matrix = [
        {
            "scenario_index": idx + 1,
            "win_rate": round(sc[0], 4),
            "win_rate_pct": round(sc[0] * 100.0, 1),
            "win_loss": round(sc[1], 2),
            "expectancy_r": round(sc[0] * sc[1] - (1.0 - sc[0]), 4),
            "safe_kelly_pct": round(max(0.0, ((sc[0] * sc[1] - (1.0 - sc[0])) / sc[1]) * fractional_multiplier * 100.0), 2),
            "risk_budget": 0.0,
            "margin": 0.0,
            "risk": 0.0,
            "total_lots": 0
        }
        for idx, sc in enumerate(scenarios)
    ]
    return {
        "equity": eq,
        "kelly": kelly_res,
        "kelly_range": kelly_range_res["range_summary"],
        "drawdown_info": dd_info,
        "portfolio_gauges": {
            "equity": eq,
            "deployable_margin": 0.0,
            "total_actual_margin": 0.0,
            "table_margin_total": 0.0,
            "margin_utilization_pct": 0.0,
            "normal_margin_target_pct": 30.0,
            "soft_margin_cap_pct": 35.0,
            "hard_margin_cap_pct": 40.0,
            "cash_buffer": eq,
            "cash_buffer_pct": 100.0,
            "deployable_risk": 0.0,
            "total_actual_risk": 0.0,
            "table_risk_total": 0.0,
            "open_risk_pct": 0.0,
            "target_open_risk": 0.0,
            "total_lots": 0,
            "active_contracts_count": 0,
            "actual_recommended_margin": 0.0,
            "actual_recommended_risk": 0.0,
            "actual_recommended_risk_pct": 0.0,
            "actual_recommended_margin_pct": 0.0,
            "recommended_full_equity": 0.0,
            "rec_equity_driver": "none",
            "basket_full_margin": 0.0,
            "basket_full_risk": 0.0,
            "basket_full_risk_pct": 0.0,
            "recommended_min_equity": 0.0,
            "base_equity_driver": "none",
            "feasibility_status": "EMPTY",
            "feasibility_message": "当前未勾选任何品种。请在下方表格中勾选要配置的期货品种，系统将实时进行自适应仓位与风险测算。"
        },
        "scenario_matrix": scenario_matrix,
        "items": [],
        "sectors": [],
        "clusters": [],
        "stress_tests": run_stress_scenarios(
            equity=eq,
            items=[],
            current_margin=0.0,
            current_risk=0.0,
            p_min=p_min,
            safe_kelly_pct=kelly_res.get("safe_kelly_pct", 2.6)
        ),
        "code_snippets": {
            "tbquant_code": "// 当前未勾选任何品种，请在表格勾选品种后生成代码",
            "python_cta_code": "# 当前未勾选任何品种，请在表格勾选品种后生成代码"
        },
        "tq_status": get_tq_status(),
        "latest_close_date": get_tq_status().get("latest_close_date", "2026-09-15")
    }


def run_portfolio_sizing(
    equity: float = 1000000.0,
    win_rate: Optional[float] = None,
    win_loss_ratio: Optional[float] = None,
    win_rate_min: Optional[float] = None,
    win_rate_max: Optional[float] = None,
    win_loss_min: Optional[float] = None,
    win_loss_max: Optional[float] = None,
    fractional_multiplier: float = 0.20,
    current_drawdown_pct: float = 0.0,
    selected_symbols: Optional[List[str]] = None,
    custom_prices: Optional[Dict[str, float]] = None,
    custom_stops: Optional[Dict[str, float]] = None,
    cluster_cap_rate: float = 0.30,
    single_asset_cap_rate: float = 0.15,
) -> Dict[str, Any]:
    """
    Executes the full quantitative position sizing and risk management algorithm.
    Calculates 6 scenarios: (p_min, b_min), (p_min, b_max), (p_mid, b_min), (p_mid, b_max),
    (p_max, b_min), (p_max, b_max), and calculates the arithmetic mean for the deployable margin.
    """
    eq = max(10000.0, float(equity))

    # Resolve win rate range (default 30%~40%)
    if win_rate_min is not None and win_rate_max is not None:
        p_min = min(float(win_rate_min), float(win_rate_max))
        p_max = max(float(win_rate_min), float(win_rate_max))
        p_mid = (p_min + p_max) / 2.0
    elif win_rate is not None:
        p_min = float(win_rate)
        p_max = float(win_rate)
        p_mid = float(win_rate)
    else:
        p_min = 0.30
        p_max = 0.40
        p_mid = 0.35

    # Resolve win-loss ratio range (default 2.5 ~ 4.0)
    if win_loss_min is not None and win_loss_max is not None:
        b_min = min(float(win_loss_min), float(win_loss_max))
        b_max = max(float(win_loss_min), float(win_loss_max))
        b_mid = (b_min + b_max) / 2.0
    elif win_loss_ratio is not None:
        b_min = float(win_loss_ratio)
        b_max = float(win_loss_ratio)
        b_mid = float(win_loss_ratio)
    else:
        b_min = 2.5
        b_max = 4.0
        b_mid = 3.25

    # 1. Calculate Kelly metrics
    kelly_res = calculate_kelly(
        equity=eq,
        win_rate=p_mid,
        win_loss_ratio=b_mid,
        fractional_multiplier=fractional_multiplier
    )

    kelly_range_res = calculate_kelly_range(
        win_rate_min=p_min,
        win_rate_max=p_max,
        win_loss_min=b_min,
        win_loss_max=b_max,
        fractional_multiplier=fractional_multiplier,
        equity=eq
    )

    # 2. Drawdown circuit breaker scaler
    dd_info = get_drawdown_scaler(current_drawdown_pct)
    dd_scaler = dd_info["scaler"]

    base_portfolio_risk = kelly_res.get("safe_risk_budget") or kelly_res.get("portfolio_open_risk_budget") or (eq * 0.026)
    active_portfolio_risk = base_portfolio_risk * dd_scaler

    # Margin limits
    soft_margin_cap = kelly_res["soft_margin_cap"]   # 35%
    hard_margin_cap = kelly_res["hard_margin_cap"]   # 40%

    # Default symbols if None provided (initial request): standard active basket
    if selected_symbols is None:
        selected_symbols = [
            "AG", "JM", "RB", "SA", "FG", "CU", "SN",
            "AO", "PG", "BR", "LH", "JD", "CJ", "P"
        ]
    else:
        selected_symbols = [s.upper().strip() for s in selected_symbols if s.upper().strip() in FUTURES_INSTRUMENTS]

    # If the user explicitly selected ZERO symbols (empty checklist)
    if len(selected_symbols) == 0:
        return build_empty_portfolio_result(
            eq=eq,
            kelly_res=kelly_res,
            kelly_range_res=kelly_range_res,
            dd_info=dd_info,
            fractional_multiplier=fractional_multiplier,
            p_min=p_min, p_max=p_max, b_min=b_min, b_max=b_max
        )

    custom_prices = custom_prices or {}
    custom_stops = custom_stops or {}

    # Group selected instruments by cluster
    cluster_instruments: Dict[str, List[str]] = {}
    for sym in selected_symbols:
        inst = get_instrument(sym)
        c = inst.get("cluster", "other")
        cluster_instruments.setdefault(c, []).append(sym)

    # Re-normalize cluster weights across active clusters
    total_active_weight = sum(DEFAULT_CLUSTER_WEIGHTS.get(c, 0.05) for c in cluster_instruments.keys())
    normalized_cluster_weights: Dict[str, float] = {}
    num_clusters = len(cluster_instruments)
    for c in cluster_instruments.keys():
        w = DEFAULT_CLUSTER_WEIGHTS.get(c, 0.05)
        if num_clusters <= 2:
            normalized_w = 1.0 / num_clusters
            normalized_cluster_weights[c] = normalized_w
        else:
            normalized_w = (w / total_active_weight) if total_active_weight > 0 else (1.0 / num_clusters)
            normalized_cluster_weights[c] = min(normalized_w, max(cluster_cap_rate, 1.0 / num_clusters))

    capital_scale_factor = eq / 1000000.0

    # Pre-calculate instrument properties (R-unit, ATR, margin per lot, max lots)
    items_meta: Dict[str, Dict[str, Any]] = {}
    items: List[Dict[str, Any]] = []

    from backend.tq_service import get_market_data, get_tq_status

    for sym in selected_symbols:
        inst = get_instrument(sym)
        tq_mkt = get_market_data(sym)

        multiplier = float(tq_mkt.get("volume_multiple") or inst["multiplier"])
        # Yesterday's close as core reference price, allowing user custom override
        default_price = float(tq_mkt.get("pre_close") or inst["default_price"])
        price = float(custom_prices.get(sym, default_price))
        margin_rate = float(tq_mkt.get("margin_rate") or inst["margin_rate"])
        typical_atr = float(tq_mkt.get("atr14") or inst["typical_atr"])
        tick_size = float(tq_mkt.get("price_tick") or inst["tick_size"])
        cluster_id = inst.get("cluster", "other")
        close_date = tq_mkt.get("close_date", "2026-09-15")
        underlying_sym = tq_mkt.get("underlying_symbol", inst.get("symbol", ""))

        # Gap volatility metrics (高开低开跳空风险)
        gap_penalty = float(tq_mkt.get("gap_penalty", 1.0))
        gap_risk_level = tq_mkt.get("gap_risk_level", "常规平稳")
        gap_risk_tag = tq_mkt.get("gap_risk_tag", "normal")
        gap_ratio_pct = float(tq_mkt.get("gap_ratio_pct", 20.0))
        max_gap_ratio = float(tq_mkt.get("max_gap_ratio", 0.5))

        notional_per_lot = price * multiplier
        margin_per_lot = notional_per_lot * margin_rate

        user_stop = custom_stops.get(sym)
        min_atr_stop = 1.2 * typical_atr * gap_penalty
        min_percent_stop = 0.02 * price * gap_penalty
        if user_stop and user_stop > 0:
            effective_stop_points = max(float(user_stop), min_atr_stop)
        else:
            effective_stop_points = max(min_atr_stop, min_percent_stop)

        risk_per_lot = effective_stop_points * multiplier

        atr_pct = typical_atr / price if price > 0 else 0.02
        benchmark_atr_pct = 0.022
        # Base vol scaler scaled inversely by gap penalty to avoid excessive exposure
        base_vol_scaler = benchmark_atr_pct / max(0.005, atr_pct)
        vol_scaler = max(0.50, min(1.25, base_vol_scaler / gap_penalty))

        base_max_lots_1m = inst.get("max_lots_1m", 2)
        table_max_lots = max(1, int(round(base_max_lots_1m * capital_scale_factor)))

        max_margin_per_inst = eq * 0.12
        margin_lots = max(0, int(math.floor(max_margin_per_inst / max(1.0, margin_per_lot))))

        meta = {
            "symbol": sym,
            "name": inst["name"],
            "exchange": inst["exchange"],
            "sector": inst["sector"],
            "cluster": cluster_id,
            "multiplier": multiplier,
            "tick_size": tick_size,
            "price": price,
            "underlying_symbol": underlying_sym,
            "close_date": close_date,
            "margin_rate": margin_rate,
            "typical_atr": typical_atr,
            "gap_penalty": gap_penalty,
            "gap_risk_level": gap_risk_level,
            "gap_risk_tag": gap_risk_tag,
            "gap_ratio_pct": gap_ratio_pct,
            "max_gap_ratio": max_gap_ratio,
            "effective_stop": effective_stop_points,
            "notional_per_lot": notional_per_lot,
            "margin_per_lot": margin_per_lot,
            "risk_per_lot": risk_per_lot,
            "vol_scaler": vol_scaler,
            "table_max_lots": table_max_lots,
            "margin_lots": margin_lots,
            "price_source": f"{close_date} 昨收价(pre_close)" if "pre_close" in tq_mkt else "基准参考价",
            "description": inst.get("description", "")
        }
        items_meta[sym] = meta

    # Construct the 6-Scenario evaluation pairs
    if abs(p_min - p_max) < 1e-6 and abs(b_min - b_max) < 1e-6:
        scenarios_coords = [(p_min, b_min)]
    elif abs(b_min - b_max) < 1e-6:
        scenarios_coords = [(p_min, b_min), (p_mid, b_min), (p_max, b_min)]
    elif abs(p_min - p_max) < 1e-6:
        scenarios_coords = [(p_min, b_min), (p_min, b_max)]
    else:
        # Exact 6 scenarios requested by the user:
        # 1. (win_rate_min, win_loss_min)
        # 2. (win_rate_min, win_loss_max)
        # 3. ((win_rate_min + win_rate_max)/2, win_loss_min)
        # 4. ((win_rate_min + win_rate_max)/2, win_loss_max)
        # 5. (win_rate_max, win_loss_min)
        # 6. (win_rate_max, win_loss_max)
        scenarios_coords = [
            (p_min, b_min),
            (p_min, b_max),
            (p_mid, b_min),
            (p_mid, b_max),
            (p_max, b_min),
            (p_max, b_max),
        ]

    # Execute Sizing across each scenario
    scenario_results: List[Dict[str, Any]] = []
    for p_sc, b_sc in scenarios_coords:
        sc_res = _solve_single_scenario_allocation(
            eq=eq,
            p=p_sc,
            b=b_sc,
            k_frac=fractional_multiplier,
            dd_scaler=dd_scaler,
            selected_symbols=selected_symbols,
            cluster_instruments=cluster_instruments,
            normalized_cluster_weights=normalized_cluster_weights,
            items_meta=items_meta,
            cluster_cap_rate=cluster_cap_rate,
            single_asset_cap_rate=single_asset_cap_rate,
            soft_margin_cap=soft_margin_cap,
        )
        scenario_results.append(sc_res)

    # 6-Scenario Averaging: Deployable Margin and Open Risk
    deployable_margin = sum(sc["margin"] for sc in scenario_results) / len(scenario_results)
    deployable_risk = sum(sc["risk"] for sc in scenario_results) / len(scenario_results)

    # Construct final contract sizing items based on average scenario lots
    for sym in selected_symbols:
        meta = items_meta[sym]
        avg_lots = sum(sc["lots"].get(sym, 0) for sc in scenario_results) / len(scenario_results)
        avg_raw_risk = sum(sc.get("raw_risk_lots", {}).get(sym, 0.0) for sc in scenario_results) / len(scenario_results)
        final_lots = max(0, min(meta["table_max_lots"], int(math.floor(avg_lots + 0.5))))

        # Theoretical risk lots (unconstrained allocation based purely on Kelly risk budget)
        theoretical_risk_lots = round(avg_raw_risk, 1) if avg_raw_risk > 0 else round(avg_lots, 1)

        eff_stop = round(meta["effective_stop"], 2)
        r_per_lot = round(eff_stop * meta["multiplier"], 2)
        p_rounded = round(meta["price"], 2)
        m_per_lot = round(p_rounded * meta["multiplier"] * meta["margin_rate"], 2)

        items.append({
            "symbol": sym,
            "name": meta["name"],
            "exchange": meta["exchange"],
            "sector": meta["sector"],
            "cluster": meta["cluster"],
            "multiplier": meta["multiplier"],
            "tick_size": meta["tick_size"],
            "price": p_rounded,
            "underlying_symbol": meta.get("underlying_symbol", sym),
            "close_date": meta.get("close_date", "2026-09-15"),
            "margin_rate": meta["margin_rate"],
            "margin_rate_pct": round(meta["margin_rate"] * 100.0, 1),
            "typical_atr": round(meta["typical_atr"], 2),
            "gap_penalty": meta.get("gap_penalty", 1.0),
            "gap_risk_level": meta.get("gap_risk_level", "常规平稳"),
            "gap_risk_tag": meta.get("gap_risk_tag", "normal"),
            "gap_ratio_pct": meta.get("gap_ratio_pct", 20.0),
            "max_gap_ratio": meta.get("max_gap_ratio", 0.5),
            "effective_stop": eff_stop,
            "notional_per_lot": round(p_rounded * meta["multiplier"], 2),
            "margin_per_lot": m_per_lot,
            "risk_per_lot": r_per_lot,
            "risk_lots": theoretical_risk_lots,  # Fixed undefined手!
            "vol_scaler": round(meta["vol_scaler"], 2),
            "table_max_lots": meta["table_max_lots"],
            "avg_lots_raw": round(avg_lots, 2),
            "final_lots": final_lots,
            "actual_risk": round(final_lots * r_per_lot, 2),
            "actual_margin": round(final_lots * m_per_lot, 2),
            "price_source": meta.get("price_source", "天勤昨收价(pre_close)"),
            "description": meta["description"]
        })

    target_risk = min(eq * 0.030, max(deployable_risk * 1.3, kelly_res.get("portfolio_open_risk_budget", 0.0), eq * 0.026)) if deployable_risk > 0 else 0.0

    # If strategy has no statistical edge (Expectancy <= 0), strictly set all lots to 0
    if not kelly_res.get("has_edge", True) or deployable_risk <= 0:
        for it in items:
            it["final_lots"] = 0
            it["actual_risk"] = 0.0
            it["actual_margin"] = 0.0
    else:
        # Fallback: if all lots rounded to 0 but deployable_risk > 0 and deployable_margin > 0
        if sum(it["final_lots"] for it in items) == 0 and deployable_risk > 0:
            affordable = sorted(items, key=lambda x: x["risk_per_lot"])
            for it in affordable:
                if it["risk_per_lot"] <= deployable_risk * 1.5:
                    it["final_lots"] = 1
                    it["actual_risk"] = round(it["risk_per_lot"], 2)
                    it["actual_margin"] = round(it["margin_per_lot"], 2)
                    break

        # Dynamic Rebalancing Pass (削峰填谷与广度优先保证):
        # If a selected symbol has 0 lots but fits within account risk & margin,
        # dynamically trim over-allocated symbols (> 1 lot) to grant it 1 lot!
        items_map = {it["symbol"]: it for it in items}
        cluster_map: Dict[str, List[str]] = {}
        for it in items:
            c = it["cluster"]
            if c not in cluster_map: cluster_map[c] = []
            cluster_map[c].append(it["symbol"])

        target_risk = min(eq * 0.030, max(deployable_risk * 1.3, kelly_res["portfolio_open_risk_budget"], eq * 0.026))
        current_total_risk = sum(it["actual_risk"] for it in items)
        current_total_margin = sum(it["actual_margin"] for it in items)

        for it in items:
            if it["final_lots"] == 0 and it["risk_per_lot"] <= target_risk and it["margin_per_lot"] <= soft_margin_cap:
                r_l = it["risk_per_lot"]
                m_l = it["margin_per_lot"]
                c_id = it["cluster"]
                c_syms = cluster_map.get(c_id, [it["symbol"]])
                c_risk = sum(items_map[s]["actual_risk"] for s in c_syms)
                eff_c_cap = max(target_risk * cluster_cap_rate, r_l) if len(cluster_map) > 2 else target_risk

                trimmable = [s for s in c_syms if items_map[s]["final_lots"] > 1]
                if not trimmable and len(cluster_map) > 2:
                    trimmable = [s for s in items_map if items_map[s]["final_lots"] > 1]

                while trimmable and ((current_total_risk + r_l > target_risk) or (current_total_margin + m_l > soft_margin_cap) or (c_risk + r_l > eff_c_cap + 1.0 and len(cluster_map) > 2)):
                    x_trim = max(trimmable, key=lambda s: items_map[s]["final_lots"])
                    items_map[x_trim]["final_lots"] -= 1
                    items_map[x_trim]["actual_risk"] = round(items_map[x_trim]["final_lots"] * items_map[x_trim]["risk_per_lot"], 2)
                    items_map[x_trim]["actual_margin"] = round(items_map[x_trim]["final_lots"] * items_map[x_trim]["margin_per_lot"], 2)
                    current_total_risk -= items_map[x_trim]["risk_per_lot"]
                    current_total_margin -= items_map[x_trim]["margin_per_lot"]
                    if x_trim in c_syms:
                        c_risk -= items_map[x_trim]["risk_per_lot"]
                    trimmable = [s for s in trimmable if items_map[s]["final_lots"] > 1]

                if (current_total_risk + r_l <= target_risk) and (current_total_margin + m_l <= soft_margin_cap):
                    it["final_lots"] = 1
                    it["actual_risk"] = round(r_l, 2)
                    it["actual_margin"] = round(m_l, 2)
                    current_total_risk += r_l
                    current_total_margin += m_l

        # Portfolio Saturation Pass:
        # Fulfill risk budget up to target_risk (<= 3.0% hard cap, ~30,000 RMB) and normal margin target (25%~30%, soft cap 35%)
        if current_total_risk < target_risk and current_total_margin < soft_margin_cap:
            sat_candidates = sorted(items, key=lambda x: (
                0 if x["final_lots"] == 0 and x["risk_per_lot"] <= 3500 else
                1 if x["final_lots"] == 0 and x["risk_per_lot"] <= 8000 else
                2 if x["final_lots"] > 0 else 3,
                x["risk_per_lot"]
            ))

            for _ in range(30):
                added = False
                for it in sat_candidates:
                    r_l = it["risk_per_lot"]
                    m_l = it["margin_per_lot"]
                    if current_total_risk + r_l > target_risk:
                        continue
                    if current_total_margin + m_l > soft_margin_cap:
                        continue
                    if it["final_lots"] >= it["table_max_lots"]:
                        continue

                    c_id = it["cluster"]
                    c_syms = cluster_map.get(c_id, [it["symbol"]])
                    c_risk = sum(items_map[s]["actual_risk"] for s in c_syms)
                    eff_c_cap = max(target_risk * cluster_cap_rate, r_l) if len(cluster_map) > 2 else target_risk
                    if (c_risk + r_l) > (eff_c_cap + 1.0) and c_risk > 0 and len(cluster_map) > 2:
                        continue

                    eff_s_cap = max(target_risk * single_asset_cap_rate, r_l) if len(cluster_map) > 2 else target_risk
                    if (it["final_lots"] + 1) * r_l > (eff_s_cap + 1.0) and it["final_lots"] > 0 and len(cluster_map) > 2:
                        continue

                    it["final_lots"] += 1
                    it["actual_risk"] = round(it["final_lots"] * r_l, 2)
                    it["actual_margin"] = round(it["final_lots"] * m_l, 2)
                    current_total_risk += r_l
                    current_total_margin += m_l
                    added = True
                if not added:
                    break

    # Calculate actual totals from item table
    total_table_risk = sum(it["actual_risk"] for it in items)
    total_table_margin = sum(it["actual_margin"] for it in items)
    total_lots = sum(it["final_lots"] for it in items)

    # Basket Feasibility & Capital Requirement Analysis (自选品种开仓资本与风险评估)
    # 1. Base 1-lot baseline (自选品种各建仓1手的起步底线)
    base_1lot_margin = sum(it["margin_per_lot"] for it in items)
    base_1lot_risk = sum(it["risk_per_lot"] for it in items)
    min_equity_for_margin = base_1lot_margin / 0.30 if base_1lot_margin > 0 else 0.0
    min_equity_for_risk = base_1lot_risk / 0.03 if base_1lot_risk > 0 else 0.0
    recommended_min_equity = max(min_equity_for_margin, min_equity_for_risk)
    base_driver = "≤3.0% 止损上限" if min_equity_for_risk >= min_equity_for_margin else "≤30% 保证金上限"

    # 2. Recommended Full Allocation (当前算法自适应推荐持仓全开实际规模)
    rec_equity_margin = total_table_margin / 0.30 if total_table_margin > 0 else 0.0
    rec_equity_risk = total_table_risk / 0.03 if total_table_risk > 0 else 0.0
    recommended_full_equity = max(rec_equity_margin, rec_equity_risk)
    rec_driver = "≤3.0% 止损上限" if rec_equity_risk >= rec_equity_margin else "≤30% 保证金上限"

    if not kelly_res.get("has_edge", True) or deployable_risk <= 0:
        feasibility_status = "NEGATIVE_EXPECTANCY"
        feasibility_message = "策略期望值 ≤ 0 (无统计优势)，无法执行凯利公式！系统强制禁止开仓并将所有推荐手数归零以防本金灭失。"
    elif eq >= recommended_full_equity:
        feasibility_status = "FEASIBLE"
        feasibility_message = f"当前资金 ¥{eq:,.2f} 充裕，可稳健承载所选 {len(selected_symbols)} 个品种推荐手数全部建仓！"
    else:
        feasibility_status = "CONSTRAINED"
        feasibility_message = f"所选 {len(selected_symbols)} 个品种推荐满开建议本金规模 ¥{recommended_full_equity:,.2f} (各开1手底仓需 ¥{recommended_min_equity:,.2f})。当前资金已启动自适应优化平衡。"

    cluster_names = get_clusters()
    for it in items:
        it["risk_contrib_pct"] = round((it["actual_risk"] / total_table_risk * 100.0) if total_table_risk > 0 else 0.0, 1)
        it["margin_contrib_pct"] = round((it["actual_margin"] / total_table_margin * 100.0) if total_table_margin > 0 else 0.0, 1)

        # Precise multi-layer constraint diagnostics
        sym = it["symbol"]
        f_lots = it["final_lots"]
        r_l = it["risk_per_lot"]
        m_l = it["margin_per_lot"]
        max_l = it["table_max_lots"]
        c_id = it["cluster"]
        c_name = cluster_names.get(c_id, c_id)
        c_risk = sum(x["actual_risk"] for x in items if x["cluster"] == c_id)
        eff_c_cap = max(target_risk * cluster_cap_rate, r_l) if len(cluster_instruments) > 2 else target_risk
        eff_s_cap = max(target_risk * single_asset_cap_rate, r_l) if len(cluster_instruments) > 2 else target_risk
        rem_risk = max(0.0, target_risk - total_table_risk)
        rem_margin = max(0.0, soft_margin_cap - total_table_margin)

        it["cluster_name"] = c_name
        it["cluster_risk_total"] = round(c_risk, 2)
        it["cluster_risk_cap"] = round(eff_c_cap, 2)
        it["single_asset_risk_cap"] = round(eff_s_cap, 2)

        if not kelly_res.get("has_edge", True) or deployable_risk <= 0:
            it["allocation_status"] = "NEGATIVE_EDGE"
            it["status_label"] = "负期望值归零"
            it["constraint_reason"] = "策略数学期望 ≤ 0 (无统计优势)，凯利公式最优下注比例为 0%，系统已强制归零以防本金灭失。"
            it["why_cannot_increase"] = "必须在上方参数区调高胜率或盈亏比，锁定正期望值后方可开仓。"
            it["suggestion"] = "调整策略胜率或盈亏比参数，确保单笔数学期望 E > 0。"
        elif f_lots == 0:
            it["allocation_status"] = "CROWDED_OUT"
            it["status_label"] = "开仓受阻(已被挤出)"
            if r_l > target_risk:
                it["constraint_reason"] = f"单手击穿止损风险 (¥{r_l:,.2f}) 超过账户允许的最大开放风险预算 (¥{target_risk:,.2f})，单手即超限。"
                it["why_cannot_increase"] = f"该品种单手名义价值与波动率过大，单手风险即击穿账户风控总预算。"
                it["suggestion"] = "建议提升账户本金规模，或选择单手风险更小的同板块合约。"
            elif m_l > soft_margin_cap:
                it["constraint_reason"] = f"单手保证金占用 (¥{m_l:,.2f}) 超过账户 35% 保证金软上限 (¥{soft_margin_cap:,.2f})。"
                it["why_cannot_increase"] = "单手保证金过高，无法满足 35% 资金占用风控约束。"
                it["suggestion"] = "建议提升账户本金，或选择低保证金合约。"
            elif (c_risk + r_l) > (eff_c_cap + 1.0) and len(cluster_instruments) > 2:
                competing_syms = [x["symbol"] for x in items if x["cluster"] == c_id and x["final_lots"] > 0]
                it["constraint_reason"] = (
                    f"触发所属【{c_name}】机制聚类防火墙硬顶 (30%，额度上限 ¥{eff_c_cap:,.2f}，当前已占用 ¥{c_risk:,.2f})。"
                    f"该品种单手风险高达 ¥{r_l:,.2f}，无法再容纳，配额已被同集群内优先级更高或更均衡的品种 ({', '.join(competing_syms) if competing_syms else '其他品种'}) 优先吸纳。"
                )
                it["why_cannot_increase"] = f"若强行分配 1 手，该集群风险将飙升至 ¥{c_risk + r_l:,.2f} (占总预算 {(c_risk + r_l)/target_risk*100:.1f}%)，严重违背产业风险防火墙隔离原则。"
                it["suggestion"] = f"若需开仓该品种，请在左侧取消勾选同集群的竞争品种 ({', '.join(competing_syms)})，或调高本金。"
            elif r_l > rem_risk + 1.0:
                it["constraint_reason"] = (
                    f"组合总开放风险预算已近满额 (总预算 ¥{target_risk:,.2f}，当前已分配 ¥{total_table_risk:,.2f}，剩余仅 ¥{rem_risk:,.2f})。"
                    f"不足以承载该品种单手 ¥{r_l:,.2f} 风险，已被其它低风险或大数分散品种挤出。"
                )
                it["why_cannot_increase"] = f"若强行分配 1 手，组合总止损风险将突破 3.0% 凯利安全硬顶 (达到 {(total_table_risk + r_l)/eq*100:.2f}%)。"
                it["suggestion"] = "若需开仓该品种，请取消勾选其它高风险品种以腾出风险预算，或调大本金。"
            elif m_l > rem_margin + 1.0:
                it["constraint_reason"] = (
                    f"组合保证金占用已达软上限 (35% 上限 ¥{soft_margin_cap:,.2f}，当前已用 ¥{total_table_margin:,.2f}，剩余仅 ¥{rem_margin:,.2f})。"
                    f"不足以支付该品种单手 ¥{m_l:,.2f} 保证金。"
                )
                it["why_cannot_increase"] = f"若分配 1 手，保证金占用将达到 {(total_table_margin + m_l)/eq*100:.1f}%，超过 35% 预警线。"
                it["suggestion"] = "请调减其他重保证金占用品种。"
            else:
                it["constraint_reason"] = "受多情景凯利矩阵优化与组合全局削峰填谷平衡限制，在当前多品种博弈下综合权重低于截断阈值，暂未分配建仓手数。"
                it["why_cannot_increase"] = "在 6 组行情极端与中枢情景测试中，该品种未能获得足够胜出权重。"
                it["suggestion"] = "可减少勾选品种数量以提高单一品种获配概率。"
        else:
            # final_lots > 0
            next_single_risk = (f_lots + 1) * r_l
            next_cluster_risk = c_risk + r_l
            next_total_risk = total_table_risk + r_l
            next_total_margin = total_table_margin + m_l

            if f_lots >= max_l:
                it["allocation_status"] = "CAPACITY_MAX"
                it["status_label"] = "已达容量上限"
                it["constraint_reason"] = f"当前已分配 {f_lots} 手，已达到该品种物理流动性与容量上限 ({max_l} 手)。"
                it["why_cannot_increase"] = f"该品种设置了单账户实盘容量硬顶 ({max_l} 手)，以防止实盘交易大单冲击成本与滑点过大。"
                it["suggestion"] = "当前手数已是实盘最佳执行规模，无需进一步增加。"
            elif next_single_risk > eff_s_cap + 1.0 and len(cluster_instruments) > 2:
                it["allocation_status"] = "SINGLE_CAP_REACHED"
                it["status_label"] = "单品种限额饱和"
                it["constraint_reason"] = f"当前配置 {f_lots} 手 (占用风险 ¥{f_lots * r_l:,.2f})。单品种 15% 集中度上限为 ¥{eff_s_cap:,.2f}。"
                it["why_cannot_increase"] = f"若加仓至 {f_lots + 1} 手，单品种止损风险将达 ¥{next_single_risk:,.2f} (占总预算 {next_single_risk/target_risk*100:.1f}%)，超过单品种 15% 防爆上限。"
                it["suggestion"] = "若需提高该品种手数，可在左侧减少勾选品种数量以提高单一品种集中度预算。"
            elif next_cluster_risk > eff_c_cap + 1.0 and len(cluster_instruments) > 2:
                it["allocation_status"] = "CLUSTER_CAP_REACHED"
                it["status_label"] = "集群防火墙饱和"
                it["constraint_reason"] = f"当前配置 {f_lots} 手。所属【{c_name}】集群风险已达 ¥{c_risk:,.2f} (上限 ¥{eff_c_cap:,.2f})。"
                it["why_cannot_increase"] = f"若加仓至 {f_lots + 1} 手，所属【{c_name}】集群风险将达 ¥{next_cluster_risk:,.2f}，突破 30% 集群防火墙上限。"
                it["suggestion"] = "若需增加该品种手数，请取消勾选同集群内的其他品种以腾出集群额度。"
            elif next_total_risk > target_risk + 1.0:
                it["allocation_status"] = "RISK_BUDGET_REACHED"
                it["status_label"] = "总风险预算饱和"
                it["constraint_reason"] = f"当前配置 {f_lots} 手。全账户总止损风险已达 ¥{total_table_risk:,.2f} (上限 ¥{target_risk:,.2f})。"
                it["why_cannot_increase"] = f"若加仓至 {f_lots + 1} 手，总开放风险将达 ¥{next_total_risk:,.2f} (占净值 {next_total_risk/eq*100:.2f}%)，突破 3.0% 凯利安全硬顶。"
                it["suggestion"] = "若需加仓，请在左侧取消勾选其他非核心品种，或调高账户资金总额。"
            elif next_total_margin > soft_margin_cap + 1.0:
                it["allocation_status"] = "MARGIN_CAP_REACHED"
                it["status_label"] = "保证金软上限饱和"
                it["constraint_reason"] = f"当前配置 {f_lots} 手。全账户保证金已用 ¥{total_table_margin:,.2f} (35% 上限 ¥{soft_margin_cap:,.2f})。"
                it["why_cannot_increase"] = f"若加仓至 {f_lots + 1} 手，保证金将达 ¥{next_total_margin:,.2f} (占净值 {next_total_margin/eq*100:.1f}%)，突破 35% 软上限。"
                it["suggestion"] = "请调减其他重保证金占用品种。"
            else:
                it["allocation_status"] = "ACTIVE"
                it["status_label"] = "正常均衡配置"
                it["constraint_reason"] = f"当前配置 {f_lots} 手，综合 6 组极端与中枢行情情景矩阵均值，为风险-资金最优解。"
                it["why_cannot_increase"] = f"多品种全局平衡中，该手数已完全锁定最优资金效率，多加 1 手将降低组合分散夏普比率。"
                it["suggestion"] = "当前配置已是数学最优均衡，建议按推荐手数执行。"

    # Sector Breakdown
    sector_summary: Dict[str, Dict[str, Any]] = {}
    for it in items:
        sec = it["sector"]
        if sec not in sector_summary:
            sector_summary[sec] = {"sector": sec, "risk": 0.0, "margin": 0.0, "lots": 0, "symbols": []}
        sector_summary[sec]["risk"] += it["actual_risk"]
        sector_summary[sec]["margin"] += it["actual_margin"]
        sector_summary[sec]["lots"] += it["final_lots"]
        sector_summary[sec]["symbols"].append(it["symbol"])

    sector_list = []
    for s_info in sector_summary.values():
        s_info["risk_pct"] = round((s_info["risk"] / total_table_risk * 100.0) if total_table_risk > 0 else 0.0, 1)
        s_info["margin_pct"] = round((s_info["margin"] / total_table_margin * 100.0) if total_table_margin > 0 else 0.0, 1)
        s_info["risk"] = round(s_info["risk"], 2)
        s_info["margin"] = round(s_info["margin"], 2)
        sector_list.append(s_info)

    # Cluster Breakdown
    cluster_names = get_clusters()
    cluster_summary: List[Dict[str, Any]] = []
    for c_id in cluster_instruments.keys():
        c_items = [it for it in items if it["cluster"] == c_id]
        c_risk = sum(it["actual_risk"] for it in c_items)
        c_margin = sum(it["actual_margin"] for it in c_items)
        c_lots = sum(it["final_lots"] for it in c_items)
        cluster_summary.append({
            "cluster_id": c_id,
            "cluster_name": cluster_names.get(c_id, c_id),
            "risk": round(c_risk, 2),
            "margin": round(c_margin, 2),
            "lots": c_lots,
            "risk_pct": round((c_risk / total_table_risk * 100.0) if total_table_risk > 0 else 0.0, 1),
            "symbols": [it["symbol"] for it in c_items]
        })

    # Portfolio Gauges using the 6-scenario exact average deployable margin
    margin_utilization_pct = round((deployable_margin / eq) * 100.0, 2)
    open_risk_pct = round((deployable_risk / eq) * 100.0, 2)
    cash_buffer = round(eq - deployable_margin, 2)
    cash_buffer_pct = round((cash_buffer / eq) * 100.0, 2)

    # 4. Stress Testing Modules (1.md Section 16 & 17)
    actual_portfolio_margin = total_table_margin if total_table_margin > 0 else deployable_margin
    actual_portfolio_risk = total_table_risk if total_table_risk > 0 else deployable_risk
    stress_tests = run_stress_scenarios(
        equity=eq,
        items=items,
        current_margin=actual_portfolio_margin,
        current_risk=actual_portfolio_risk,
        p_min=p_min,
        safe_kelly_pct=kelly_res.get("safe_kelly_pct", 2.6)
    )

    # 5. Generate Code Snippets (TBQuant & Python CTA)
    code_snippets = generate_code_snippets(items, eq, deployable_risk, deployable_margin)

    # Format scenario matrix for frontend display
    scenario_matrix = [
        {
            "scenario_index": idx + 1,
            "win_rate": round(sc["win_rate"], 4),
            "win_rate_pct": round(sc["win_rate"] * 100.0, 1),
            "win_loss": round(sc["win_loss"], 2),
            "expectancy_r": round(sc["expectancy_r"], 4),
            "safe_kelly_pct": round(sc["safe_kelly_pct"], 2),
            "risk_budget": round(sc["risk_budget"], 2),
            "margin": round(sc["margin"], 2),
            "risk": round(sc["risk"], 2),
            "total_lots": sum(sc["lots"].values())
        }
        for idx, sc in enumerate(scenario_results)
    ]

    return {
        "equity": eq,
        "kelly": kelly_res,
        "kelly_range": kelly_range_res["range_summary"],
        "drawdown_info": dd_info,
        "portfolio_gauges": {
            "equity": eq,
            "deployable_margin": round(deployable_margin, 2),
            "total_actual_margin": round(deployable_margin, 2),
            "table_margin_total": round(total_table_margin, 2),
            "margin_utilization_pct": margin_utilization_pct,
            "normal_margin_target_pct": 30.0,
            "soft_margin_cap_pct": 35.0,
            "hard_margin_cap_pct": 40.0,
            "cash_buffer": cash_buffer,
            "cash_buffer_pct": cash_buffer_pct,
            "deployable_risk": round(deployable_risk, 2),
            "total_actual_risk": round(deployable_risk, 2),
            "table_risk_total": round(total_table_risk, 2),
            "open_risk_pct": open_risk_pct,
            "target_open_risk": round(deployable_risk, 2),
            "total_lots": total_lots,
            "active_contracts_count": len([it for it in items if it["final_lots"] > 0]),
            "actual_recommended_margin": round(total_table_margin, 2),
            "actual_recommended_risk": round(total_table_risk, 2),
            "actual_recommended_risk_pct": round((total_table_risk / eq) * 100.0, 2) if eq > 0 else 0.0,
            "actual_recommended_margin_pct": round((total_table_margin / eq) * 100.0, 2) if eq > 0 else 0.0,
            "recommended_full_equity": round(recommended_full_equity, 2),
            "rec_equity_driver": rec_driver,
            "basket_full_margin": round(base_1lot_margin, 2),
            "basket_full_risk": round(base_1lot_risk, 2),
            "basket_full_risk_pct": round((base_1lot_risk / eq) * 100.0, 2) if eq > 0 else 0.0,
            "recommended_min_equity": round(recommended_min_equity, 2),
            "base_equity_driver": base_driver,
            "feasibility_status": feasibility_status,
            "feasibility_message": feasibility_message
        },
        "scenario_matrix": scenario_matrix,
        "items": items,
        "sectors": sector_list,
        "clusters": cluster_summary,
        "stress_tests": stress_tests,
        "code_snippets": code_snippets,
        "tq_status": get_tq_status(),
        "latest_close_date": get_tq_status().get("latest_close_date", "2026-09-15")
    }


def run_stress_scenarios(
    equity: float,
    items: List[Dict[str, Any]],
    current_margin: float,
    current_risk: float,
    p_min: float = 0.30,
    safe_kelly_pct: float = 2.6
) -> Dict[str, Any]:
    """
    Executes 4 stress test scenarios from 1.md:
    1. Exchange Margin Hike (+30%)
    2. Catastrophic Black Swan Gap (2x ATR)
    3. Ferrous & Construction Cluster Joint Stop-Out
    4. Dynamic Consecutive Loss Survival Test (with Drawdown Circuit Breaker)
    """
    eq = max(1000.0, float(equity))

    # 1. Margin Hike Stress (+30%)
    hiked_margin = current_margin * 1.30
    hiked_margin_util = (hiked_margin / eq) * 100.0
    margin_stress_pass = hiked_margin_util <= 48.0

    # 2. Catastrophic Gap (2x ATR on all positions)
    gap_loss = sum(it["final_lots"] * (2.0 * it["typical_atr"] * it["multiplier"]) for it in items)
    gap_loss_pct = (gap_loss / eq) * 100.0
    gap_pass = gap_loss_pct <= 6.0

    # 3. Ferrous & Construction Joint Stop-Out
    ferrous_items = [it for it in items if it["cluster"] == "ferrous_construction"]
    ferrous_loss = sum(it["final_lots"] * it["risk_per_lot"] for it in ferrous_items)
    ferrous_loss_pct = (ferrous_loss / eq) * 100.0
    ferrous_pass = ferrous_loss_pct <= 1.2

    # 4. Dynamic 10 Consecutive Losses Survival Test
    # Determine conservative win rate and probability of 10 consecutive losses: P = (1 - p_min)^10
    eff_p_min = max(0.05, min(0.95, float(p_min)))
    p_min_pct = round(eff_p_min * 100.0, 1)
    loss_prob_pct = round(((1.0 - eff_p_min) ** 10) * 100.0, 2)

    # Determine single-round stop-loss exposure ratio r_loss:
    # If the portfolio has actual open risk > 0, use actual risk / equity;
    # otherwise fallback to safe Kelly percentage or 2.5% benchmark.
    if current_risk > 0 and eq > 0:
        r_loss = max(0.002, min(0.10, current_risk / eq))
    else:
        r_loss = max(0.005, min(0.05, (safe_kelly_pct or 2.6) / 100.0))
    single_loss_pct = round(r_loss * 100.0, 2)

    # A. Raw unconstrained compounding loss (without circuit breaker)
    raw_remaining_equity = eq * ((1.0 - r_loss) ** 10)
    raw_consecutive_dd = max(0.0, ((eq - raw_remaining_equity) / eq) * 100.0)

    # B. Protected loss simulation with system Drawdown Circuit Breaker
    prot_remaining_equity = eq
    for _ in range(10):
        current_step_dd = max(0.0, ((eq - prot_remaining_equity) / eq) * 100.0)
        scaler_info = get_drawdown_scaler(current_step_dd)
        scaler = scaler_info["scaler"]
        prot_remaining_equity -= (prot_remaining_equity * r_loss * scaler)
    prot_consecutive_dd = max(0.0, ((eq - prot_remaining_equity) / eq) * 100.0)

    # Verdict generation
    if current_risk <= 0:
        verdict = (
            f"基准单轮理论敞口 {single_loss_pct}%。胜率 {p_min_pct}% 极端情景下10连败理论概率为 {loss_prob_pct}%。"
            f"经阶梯断路器熔断保护，极限受控回撤锁定在 -{round(prot_consecutive_dd, 1)}% "
            f"(残值约 {round(prot_remaining_equity / 10000.0, 1)} 万元)。"
        )
    else:
        verdict = (
            f"胜率 {p_min_pct}% 下10连败概率为 {loss_prob_pct}%。"
            f"单轮止损敞口 {single_loss_pct}%，断路器在回撤达3%~10%时逐级熔断保护，"
            f"实盘回撤锁定在 -{round(prot_consecutive_dd, 1)}% (残值约 {round(prot_remaining_equity / 10000.0, 1)} 万元)，"
            f"杜绝了无保护下的 -{round(raw_consecutive_dd, 1)}% 深度亏损。"
        )

    return {
        "margin_hike": {
            "name": "交易所统一调保 +30% 压力测试",
            "current_margin": round(current_margin, 2),
            "stressed_margin": round(hiked_margin, 2),
            "stressed_margin_pct": round(hiked_margin_util, 2),
            "threshold_pct": 48.0,
            "passed": margin_stress_pass,
            "verdict": "安全达标 (保证金上调后仍低于50%安全底线)" if margin_stress_pass else "预警！调保后保证金占用将接近警戒线"
        },
        "gap_black_swan": {
            "name": "全品种黑天鹅同向跳空 (2.0×ATR) 测试",
            "theoretical_loss": round(gap_loss, 2),
            "loss_pct": round(gap_loss_pct, 2),
            "threshold_pct": 6.0,
            "passed": gap_pass,
            "verdict": "回撤受控 (极端跳空理论损失处于账户吸收能力之内)" if gap_pass else "高风险！单日极端跳空损失超过 6%"
        },
        "cluster_joint_stop": {
            "name": "黑色+纯碱玻璃建材链同时止损冲击测试",
            "cluster_loss": round(ferrous_loss, 2),
            "loss_pct": round(ferrous_loss_pct, 2),
            "threshold_pct": 1.2,
            "passed": ferrous_pass,
            "verdict": "聚类防火墙有效 (黑色链集中止损未击穿单集群安全阀)" if ferrous_pass else "建材产业链暴露过重，建议削减纯碱或螺纹手数"
        },
        "consecutive_losses": {
            "name": f"胜率{p_min_pct}%极端情景下 10 连败生存测试",
            "p_min_pct": p_min_pct,
            "loss_prob_pct": loss_prob_pct,
            "single_loss_pct": single_loss_pct,
            "surviving_equity": round(prot_remaining_equity, 2),
            "cumulative_dd_pct": round(prot_consecutive_dd, 2),
            "raw_surviving_equity": round(raw_remaining_equity, 2),
            "raw_cumulative_dd_pct": round(raw_consecutive_dd, 2),
            "passed": prot_consecutive_dd <= 25.0,
            "verdict": verdict
        }
    }


def generate_code_snippets(
    items: List[Dict[str, Any]],
    equity: float,
    total_risk: float,
    total_margin: float
) -> Dict[str, str]:
    """
    Generates copy-paste ready code for TBQuant and Python CTA engines.
    """
    # 1. TBQuant PortfolioRiskManager code
    tbq_lines = [
        "// =====================================================================",
        "// TBQuant 组合风险管理模块 (PortfolioRiskManager.tb)",
        f"// 依据 1.md 五层仓位与凯利公式生成 | 账户总权益: ¥{equity:,.0f}",
        f"// 总规划开放风险: ¥{total_risk:,.0f} | 规划保证金: ¥{total_margin:,.0f}",
        "// =====================================================================\n",
        "Params",
        f"    Numeric AccountEquity({equity:.0f});",
        f"    Numeric MaxOpenRiskBudget({total_risk:.0f});",
        f"    Numeric MaxMarginCap({total_margin:.0f});\n",
        "Vars",
        "    Numeric TargetLots(0);",
        "    Numeric EffectiveStop(0);",
        "    Numeric RiskPerLot(0);\n",
        "Begin",
        "    // 获取当前品种理论风控手数上限"
    ]

    for it in items:
        if it["final_lots"] > 0:
            sym = it["symbol"]
            lots = it["final_lots"]
            mult = it["multiplier"]
            stop = it["effective_stop"]
            tbq_lines.append(
                f"    If (Symbol == \"{sym}\" || Symbol == \"{sym}888\" || Symbol == \"{sym}999\") {{\n"
                f"        EffectiveStop = Max(1.2 * AvgTrueRange(14), {stop});\n"
                f"        RiskPerLot = EffectiveStop * {mult};\n"
                f"        TargetLots = Min({lots}, IntPart({it['actual_risk']} / RiskPerLot));\n"
                f"        Return TargetLots;\n"
                f"    }}"
            )

    tbq_lines.append("    Return 1; // 默认防守一手\nEnd")
    tbq_code = "\n".join(tbq_lines)

    # 2. Python CTA Engine code
    py_lines = [
        "# =====================================================================",
        "# Python CTA Portfolio Risk Manager Config",
        f"# Account Equity: RMB {equity:,.0f} | Target Open Risk: RMB {total_risk:,.0f}",
        "# =====================================================================\n",
        "PORTFOLIO_SIZING_CONFIG = {"
    ]

    for it in items:
        if it["final_lots"] > 0:
            sym = it["symbol"]
            py_lines.append(
                f"    \"{sym}\": {{\n"
                f"        \"name\": \"{it['name']}\",\n"
                f"        \"multiplier\": {it['multiplier']},\n"
                f"        \"allocated_risk_rmb\": {it['actual_risk']},\n"
                f"        \"allocated_margin_rmb\": {it['actual_margin']},\n"
                f"        \"recommended_lots\": {it['final_lots']},\n"
                f"        \"effective_stop_points\": {it['effective_stop']},\n"
                f"        \"cluster\": \"{it['cluster']}\"\n"
                f"    }},"
            )

    py_lines.append("}\n")
    py_lines.append(
        "def get_target_order_lots(symbol: str, current_atr: float, strategy_stop: float) -> int:\n"
        "    cfg = PORTFOLIO_SIZING_CONFIG.get(symbol.upper())\n"
        "    if not cfg:\n"
        "        return 1\n"
        "    eff_stop = max(strategy_stop, 1.2 * current_atr, cfg['effective_stop_points'])\n"
        "    risk_per_lot = eff_stop * cfg['multiplier']\n"
        "    if risk_per_lot <= 0:\n"
        "        return 0\n"
        "    lots = int(cfg['allocated_risk_rmb'] // risk_per_lot)\n"
        "    return max(0, min(lots, cfg['recommended_lots']))\n"
    )
    py_code = "\n".join(py_lines)

    return {
        "tbquant": tbq_code,
        "python_cta": py_code
    }
