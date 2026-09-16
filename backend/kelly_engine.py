"""
Kelly Criterion Calculation Engine & Fractional Kelly Risk Mapping
Implements full Kelly, fractional Kelly (0.10x ~ 0.25x), expected value,
and bounds for futures trading portfolio risk budget.
"""

from typing import Dict, Any
import math


def calculate_kelly(
    win_rate: float,
    win_loss_ratio: float,
    fractional_multiplier: float = 0.20,
    equity: float = 1000000.0,
    max_open_risk_cap_rate: float = 0.030,
) -> Dict[str, Any]:
    """
    Computes Kelly Criterion metrics and safe portfolio risk budget.

    Args:
        win_rate: p (e.g. 0.35 for 35%)
        win_loss_ratio: b (e.g. 3.0 for 3:1)
        fractional_multiplier: k_frac (e.g. 0.20 for 1/5 Kelly)
        equity: Total account equity in RMB (e.g. 1,000,000)
        max_open_risk_cap_rate: Hard upper bound on total portfolio open risk (default 3.0%)

    Returns:
        Dictionary with all mathematical Kelly metrics and safe risk budgets.
    """
    p = max(0.0, min(1.0, float(win_rate)))
    b = max(0.01, float(win_loss_ratio))
    k_frac = max(0.01, min(1.0, float(fractional_multiplier)))
    eq = max(10000.0, float(equity))

    q = 1.0 - p
    # Mathematical expectancy in R units: p * b - q
    expectancy_r = (p * b) - q

    # Full Kelly: f* = (p*(b+1) - 1) / b = (p*b - q) / b
    if expectancy_r <= 0:
        full_kelly = 0.0
        safe_kelly_rate = 0.0
        has_edge = False
        message = "策略期望值 <= 0 (无统计优势)，凯利公式计算结果为 0，系统强制禁止开仓！"
    else:
        full_kelly = (p * b - q) / b
        # Fractional Kelly
        safe_kelly_rate = full_kelly * k_frac
        has_edge = True
        message = "策略具备正数学期望，凯利公式已成功换算为组合安全开放风险预算。"

    # Clamp safe_kelly_rate to portfolio hard caps (1.md: Normal 2.5%, Hard Max 3.0%)
    # If safe_kelly_rate > max_open_risk_cap_rate, clamp it to protect equity
    effective_risk_rate = min(safe_kelly_rate, max_open_risk_cap_rate) if has_edge else 0.0

    # Total Portfolio Open Risk in RMB
    portfolio_open_risk_budget = eq * effective_risk_rate

    # Margin Budget guidelines from 1.md:
    # Normal 25%~35%, Soft Cap 35%, Hard Cap 40%
    normal_margin_budget = eq * 0.30
    soft_margin_cap = eq * 0.35
    hard_margin_cap = eq * 0.40
    cash_buffer_reserve = eq * 0.65

    # Drawdown probability estimations under Kelly
    # Under full Kelly, theoretical P(drawdown >= 50%) is approx 33%
    # Under f* / 2, P(drawdown >= 50%) is approx 11%
    # Under f* / 4 (k_frac=0.25), P(drawdown >= 50%) is approx 1.2%
    drawdown_50_prob = 0.0
    if has_edge and full_kelly > 0:
        ratio = safe_kelly_rate / full_kelly
        # Approximate risk of severe drawdown: (0.5) ** ((2 - ratio) / ratio)
        drawdown_50_prob = round(math.exp(-2.0 * (1.0 / max(0.05, ratio) - 1.0)) * 100.0, 2)
        drawdown_50_prob = min(99.0, max(0.1, drawdown_50_prob))

    return {
        "win_rate": p,
        "loss_rate": q,
        "win_loss_ratio": b,
        "expectancy_r": round(expectancy_r, 4),
        "has_edge": has_edge,
        "fractional_multiplier": k_frac,
        "full_kelly_rate": round(full_kelly, 4),
        "full_kelly_pct": round(full_kelly * 100.0, 2),
        "safe_kelly_rate": round(safe_kelly_rate, 4),
        "safe_kelly_pct": round(safe_kelly_rate * 100.0, 2),
        "effective_risk_rate": round(effective_risk_rate, 4),
        "effective_risk_pct": round(effective_risk_rate * 100.0, 2),
        "equity": eq,
        "portfolio_open_risk_budget": round(portfolio_open_risk_budget, 2),
        "safe_risk_budget": round(portfolio_open_risk_budget, 2),
        "normal_margin_budget": round(normal_margin_budget, 2),
        "soft_margin_cap": round(soft_margin_cap, 2),
        "hard_margin_cap": round(hard_margin_cap, 2),
        "cash_buffer_reserve": round(cash_buffer_reserve, 2),
        "drawdown_50_prob_pct": drawdown_50_prob,
        "message": message
    }


def get_drawdown_scaler(current_drawdown_pct: float) -> Dict[str, Any]:
    """
    Implements 1.md section 20-21 Hysteresis Circuit Breaker.
    0 ~ -3%: 1.0x
    -3% ~ -5%: 0.8x
    -5% ~ -8%: 0.6x
    -8% ~ -10%: 0.4x
    < -10%: 0.0x (Risk-Off)
    """
    dd = abs(float(current_drawdown_pct))
    if dd <= 3.0:
        return {
            "drawdown_pct": dd,
            "scaler": 1.00,
            "status": "NORMAL",
            "description": "回撤处于安全区间(0%~-3%)，全额开放标准风险预算 (1.0x)"
        }
    elif dd <= 5.0:
        return {
            "drawdown_pct": dd,
            "scaler": 0.80,
            "status": "DEFENSIVE_L1",
            "description": "轻度回撤(-3%~-5%)，启动一级防御，新开仓风险预算下调至 0.80x"
        }
    elif dd <= 8.0:
        return {
            "drawdown_pct": dd,
            "scaler": 0.60,
            "status": "DEFENSIVE_L2",
            "description": "中度回撤(-5%~-8%)，启动二级防御，新开仓风险预算压缩至 0.60x"
        }
    elif dd <= 10.0:
        return {
            "drawdown_pct": dd,
            "scaler": 0.40,
            "status": "DEFENSIVE_L3",
            "description": "重度回撤(-8%~-10%)，启动三级防御，新开仓风险预算深压至 0.40x"
        }
    else:
        return {
            "drawdown_pct": dd,
            "scaler": 0.00,
            "status": "RISK_OFF",
            "description": "回撤突破10%止损线，触发熔断停开新仓，进入策略审计与诊断模式"
        }


def calculate_kelly_range(
    win_rate_min: float,
    win_rate_max: float,
    win_loss_min: float,
    win_loss_max: float,
    fractional_multiplier: float = 0.20,
    equity: float = 1000000.0,
    max_open_risk_cap_rate: float = 0.030,
) -> Dict[str, Any]:
    """
    Computes Kelly interval for a range of win rates and payoff ratios.
    Evaluates conservative (min, min), midpoint (avg, avg), and optimistic (max, max).
    """
    p_min = min(win_rate_min, win_rate_max)
    p_max = max(win_rate_min, win_rate_max)
    b_min = min(win_loss_min, win_loss_max)
    b_max = max(win_loss_min, win_loss_max)

    p_mid = (p_min + p_max) / 2.0
    b_mid = (b_min + b_max) / 2.0

    conservative = calculate_kelly(p_min, b_min, fractional_multiplier, equity, max_open_risk_cap_rate)
    midpoint = calculate_kelly(p_mid, b_mid, fractional_multiplier, equity, max_open_risk_cap_rate)
    optimistic = calculate_kelly(p_max, b_max, fractional_multiplier, equity, max_open_risk_cap_rate)

    return {
        "midpoint": midpoint,
        "conservative": conservative,
        "optimistic": optimistic,
        "range_summary": {
            "win_rate_range": [round(p_min, 4), round(p_max, 4)],
            "win_rate_min_pct": round(p_min * 100.0, 1),
            "win_rate_max_pct": round(p_max * 100.0, 1),
            "win_rate_mid_pct": round(p_mid * 100.0, 1),
            "win_loss_range": [round(b_min, 2), round(b_max, 2)],
            "win_loss_min": round(b_min, 2),
            "win_loss_max": round(b_max, 2),
            "win_loss_mid": round(b_mid, 2),
            "f_safe_range_pct": [conservative["safe_kelly_pct"], optimistic["safe_kelly_pct"]],
            "expectancy_range_r": [conservative["expectancy_r"], optimistic["expectancy_r"]],
            "safe_kelly_min_pct": conservative["safe_kelly_pct"],
            "safe_kelly_max_pct": optimistic["safe_kelly_pct"],
            "safe_kelly_mid_pct": midpoint["safe_kelly_pct"],
            "risk_budget_min": conservative["portfolio_open_risk_budget"],
            "risk_budget_max": optimistic["portfolio_open_risk_budget"],
            "risk_budget_mid": midpoint["portfolio_open_risk_budget"]
        }
    }
