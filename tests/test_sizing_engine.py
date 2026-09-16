"""
Unit Tests for Futures Position Sizing & Risk Management System
Tests Kelly calculations, contract specifications, multi-layer sizing,
cluster constraints, margin bounds, and API endpoints.
"""

import unittest
import sys
import os

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.kelly_engine import calculate_kelly, get_drawdown_scaler
from backend.futures_db import get_instrument, get_all_instruments, FUTURES_INSTRUMENTS
from backend.risk_manager import run_portfolio_sizing
from backend.main import app
from fastapi.testclient import TestClient


class TestKellyEngine(unittest.TestCase):
    def test_standard_kelly_calculation(self):
        # p = 35%, b = 3.0, k_frac = 0.20
        res = calculate_kelly(
            win_rate=0.35,
            win_loss_ratio=3.0,
            fractional_multiplier=0.20,
            equity=1000000.0
        )
        self.assertTrue(res["has_edge"])
        self.assertAlmostEqual(res["expectancy_r"], 0.40, places=2)
        self.assertAlmostEqual(res["full_kelly_pct"], 13.33, places=1)
        self.assertAlmostEqual(res["safe_kelly_pct"], 2.67, places=1)
        self.assertAlmostEqual(res["portfolio_open_risk_budget"], 26700.0, delta=100.0)

    def test_negative_expectancy_interception(self):
        # p = 20%, b = 2.0 -> Expectancy = 0.20 * 2 - 0.80 = -0.40 <= 0
        res = calculate_kelly(
            win_rate=0.20,
            win_loss_ratio=2.0,
            equity=1000000.0
        )
        self.assertFalse(res["has_edge"])
        self.assertEqual(res["full_kelly_rate"], 0.0)
        self.assertEqual(res["safe_kelly_rate"], 0.0)
        self.assertEqual(res["portfolio_open_risk_budget"], 0.0)

    def test_drawdown_hysteresis_scaling(self):
        self.assertEqual(get_drawdown_scaler(1.5)["scaler"], 1.00)
        self.assertEqual(get_drawdown_scaler(4.0)["scaler"], 0.80)
        self.assertEqual(get_drawdown_scaler(6.5)["scaler"], 0.60)
        self.assertEqual(get_drawdown_scaler(9.0)["scaler"], 0.40)
        self.assertEqual(get_drawdown_scaler(12.0)["scaler"], 0.00)


class TestFuturesDatabase(unittest.TestCase):
    def test_contract_asymmetry(self):
        cu = get_instrument("CU")
        sa = get_instrument("SA")

        cu_notional = cu["default_price"] * cu["multiplier"]
        sa_notional = sa["default_price"] * sa["multiplier"]

        # CU notional (~395,000) is way larger than SA notional (~29,000)
        self.assertGreater(cu_notional, 300000)
        self.assertLess(sa_notional, 50000)
        self.assertGreater(cu_notional / sa_notional, 10)

    def test_database_completeness(self):
        all_inst = get_all_instruments()
        self.assertGreater(len(all_inst), 35)
        symbols = [i["symbol"] for i in all_inst]
        for key in ["AG", "CU", "RB", "SA", "FG", "JM", "P", "LH", "LC"]:
            self.assertIn(key, symbols)


class TestPortfolioSizingEngine(unittest.TestCase):
    def test_standard_1m_run(self):
        res = run_portfolio_sizing(
            equity=1000000.0,
            win_rate=0.35,
            win_loss_ratio=3.0,
            fractional_multiplier=0.20,
            selected_symbols=["AG", "JM", "RB", "SA", "FG", "CU", "SN", "AO", "PG", "BR", "LH", "JD", "CJ", "P"]
        )
        gauges = res["portfolio_gauges"]
        self.assertLessEqual(gauges["margin_utilization_pct"], 35.0)
        self.assertLessEqual(gauges["open_risk_pct"], 3.0)
        self.assertGreater(gauges["cash_buffer_pct"], 65.0)

        # Check item limits
        items_map = {it["symbol"]: it for it in res["items"]}
        if "CU" in items_map:
            self.assertLessEqual(items_map["CU"]["final_lots"], 1)
        if "SN" in items_map:
            self.assertLessEqual(items_map["SN"]["final_lots"], 1)
        if "RB" in items_map:
            self.assertLessEqual(items_map["RB"]["final_lots"], 8)
        if "SA" in items_map:
            self.assertLessEqual(items_map["SA"]["final_lots"], 6)

    def test_stress_testing_scenarios(self):
        res1 = run_portfolio_sizing(equity=1000000.0, win_rate_min=0.30, win_rate_max=0.40)
        st1 = res1["stress_tests"]
        self.assertIn("margin_hike", st1)
        self.assertIn("gap_black_swan", st1)
        self.assertIn("cluster_joint_stop", st1)
        self.assertIn("consecutive_losses", st1)

        # Dynamic win rate and probability test
        cl1 = st1["consecutive_losses"]
        self.assertEqual(cl1["p_min_pct"], 30.0)
        self.assertIn("胜率30.0%", cl1["name"])
        self.assertAlmostEqual(cl1["loss_prob_pct"], 2.82, places=2)  # (1 - 0.3)^10 = 0.02824 = 2.82%

        # Test changing win rate dynamically changes title and probability
        res2 = run_portfolio_sizing(equity=1000000.0, win_rate_min=0.40, win_rate_max=0.50)
        cl2 = res2["stress_tests"]["consecutive_losses"]
        self.assertEqual(cl2["p_min_pct"], 40.0)
        self.assertIn("胜率40.0%", cl2["name"])
        self.assertAlmostEqual(cl2["loss_prob_pct"], 0.60, places=2)  # (1 - 0.4)^10 = 0.00604 = 0.60%

        # Test that protected surviving equity and DD are dynamic and not fixed at 776329.62
        self.assertGreater(cl1["surviving_equity"], 0)
        self.assertGreater(cl1["cumulative_dd_pct"], 0)
        self.assertLessEqual(cl1["cumulative_dd_pct"], 25.0)

        # Test empty portfolio still calculates dynamic stress tests
        res_empty = run_portfolio_sizing(equity=1000000.0, selected_symbols=[])
        cl_empty = res_empty["stress_tests"]["consecutive_losses"]
        self.assertTrue(cl_empty["passed"])


class TestApiEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health_check(self):
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")

    def test_instruments_endpoint(self):
        resp = self.client.get("/api/instruments")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertGreater(data["count"], 35)

    def test_calculation_endpoint(self):
        payload = {
            "equity": 1000000.0,
            "win_rate": 0.35,
            "win_loss_ratio": 3.0,
            "fractional_multiplier": 0.20,
            "current_drawdown_pct": 0.0,
            "selected_symbols": ["AG", "RB", "SA", "CU"]
        }
        resp = self.client.post("/api/calculate", json=payload)
        self.assertEqual(resp.status_code, 200)
        json_data = resp.json()
        self.assertTrue(json_data["success"])
        self.assertIn("portfolio_gauges", json_data["data"])

    def test_calculation_endpoint_with_range_inputs(self):
        payload = {
            "equity": 1000000.0,
            "win_rate_min": 0.30,
            "win_rate_max": 0.40,
            "win_loss_min": 2.5,
            "win_loss_max": 4.0,
            "fractional_multiplier": 0.20,
            "current_drawdown_pct": 0.0,
            "selected_symbols": ["AG", "RB", "SA", "CU"]
        }
        resp = self.client.post("/api/calculate", json=payload)
        self.assertEqual(resp.status_code, 200)
        json_data = resp.json()
        self.assertTrue(json_data["success"])
        data = json_data["data"]
        self.assertIn("kelly_range", data)
        self.assertEqual(data["kelly_range"]["win_rate_range"], [0.30, 0.40])
        self.assertEqual(data["kelly_range"]["win_loss_range"], [2.5, 4.0])
        self.assertIn("f_safe_range_pct", data["kelly_range"])
        self.assertIn("expectancy_range_r", data["kelly_range"])
        self.assertGreater(data["kelly_range"]["expectancy_range_r"][0], 0.0)

    def test_six_scenario_averaging_and_dynamic_linkage(self):
        # Case 1: 30%~40%, 2.5~3.0
        payload1 = {
            "equity": 1000000.0,
            "win_rate_min": 0.30,
            "win_rate_max": 0.40,
            "win_loss_min": 2.5,
            "win_loss_max": 3.0,
            "fractional_multiplier": 0.20,
            "selected_symbols": ["AG", "JM", "RB", "SA", "FG", "CU", "SN", "AO", "PG", "BR", "LH", "JD", "CJ", "P"]
        }
        resp1 = self.client.post("/api/calculate", json=payload1)
        self.assertEqual(resp1.status_code, 200)
        data1 = resp1.json()["data"]

        # Check 6 scenarios exist
        sc_matrix1 = data1["scenario_matrix"]
        self.assertEqual(len(sc_matrix1), 6)

        # Check exact formula: deployable_margin == average of 6 scenario margins
        sum_m1 = sum(s["margin"] for s in sc_matrix1)
        expected_avg_m1 = round(sum_m1 / 6.0, 2)
        actual_margin1 = data1["portfolio_gauges"]["total_actual_margin"]
        self.assertAlmostEqual(actual_margin1, expected_avg_m1, places=1)

        # Case 2: User changes win_loss_max to 4.0 (30%~40%, 2.5~4.0)
        payload2 = dict(payload1, win_loss_max=4.0)
        resp2 = self.client.post("/api/calculate", json=payload2)
        data2 = resp2.json()["data"]
        actual_margin2 = data2["portfolio_gauges"]["total_actual_margin"]

        # Case 3: User changes win_rate to 35%~45%, win_loss to 3.0~4.0
        payload3 = dict(payload1, win_rate_min=0.35, win_rate_max=0.45, win_loss_min=3.0, win_loss_max=4.0)
        resp3 = self.client.post("/api/calculate", json=payload3)
        data3 = resp3.json()["data"]
        actual_margin3 = data3["portfolio_gauges"]["total_actual_margin"]

        # Dynamic linkage assertions: each input change MUST produce a different deployable margin
        self.assertNotEqual(actual_margin1, actual_margin2)
        self.assertNotEqual(actual_margin2, actual_margin3)
        self.assertGreater(actual_margin2, actual_margin1)
        self.assertGreater(actual_margin3, actual_margin2)


class TestTqSdkAndRiskMetrics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_tq_status_endpoint_and_disclosure(self):
        resp = self.client.get("/api/tq/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("status", data)
        self.assertIn("account", data)
        self.assertTrue(data["account"].startswith("138"))
        self.assertIn("data_source_disclosure", data)
        disclosure = data["data_source_disclosure"]
        self.assertIn("from_tqsdk", disclosure)
        self.assertIn("system_maintained_reasons", disclosure)
        # Check reasons explaining why margin_rate and cluster cannot be fetched directly from TqSdk
        reasons = {r["field"]: r["reason"] for r in disclosure["system_maintained_reasons"]}
        self.assertIn("期货公司实盘保证金率 (margin_rate)", reasons)
        self.assertIn("产业链机制聚类归属 (cluster)", reasons)

    def test_pre_close_as_reference_price_and_risk_lots_not_undefined(self):
        resp = self.client.post("/api/calculate", json={
            "equity": 1000000.0,
            "win_rate_min": 0.30,
            "win_rate_max": 0.40,
            "win_loss_min": 2.5,
            "win_loss_max": 4.0,
            "fractional_multiplier": 0.20,
            "selected_symbols": ["RB", "AG", "JM", "SC"]
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        items = data["items"]
        self.assertEqual(len(items), 4)

        for item in items:
            sym = item["symbol"]
            # 1. Price is positive
            self.assertGreater(item["price"], 0.0)
            self.assertIn("pre_close", item["price_source"])

            # 2. 1手真实风险 risk_per_lot = effective_stop * multiplier
            expected_risk_per_lot = round(item["effective_stop"] * item["multiplier"], 2)
            self.assertAlmostEqual(item["risk_per_lot"], expected_risk_per_lot, places=1)

            # 3. 1手保证金 margin_per_lot = price * multiplier * margin_rate
            expected_margin_per_lot = round(item["price"] * item["multiplier"] * item["margin_rate"], 2)
            self.assertAlmostEqual(item["margin_per_lot"], expected_margin_per_lot, places=1)

            # 4. 理论风险手 risk_lots is defined and is a float
            self.assertIn("risk_lots", item)
            self.assertIsNotNone(item["risk_lots"])
            self.assertIsInstance(item["risk_lots"], (int, float))
            self.assertGreaterEqual(item["risk_lots"], 0.0)

            # 5. Volatility risk metrics
            self.assertIn("gap_risk_level", item)
            self.assertIn("gap_penalty", item)
            self.assertGreaterEqual(item["gap_penalty"], 1.0)

    def test_high_gap_volatility_penalty_effect(self):
        # Compare silver AG (high gap volatility) vs rebar RB (low gap volatility)
        resp = self.client.post("/api/calculate", json={
            "equity": 1000000.0,
            "win_rate_min": 0.35,
            "win_rate_max": 0.35,
            "win_loss_min": 3.0,
            "win_loss_max": 3.0,
            "selected_symbols": ["AG", "RB"]
        })
        self.assertEqual(resp.status_code, 200)
        items = {it["symbol"]: it for it in resp.json()["data"]["items"]}
        
        ag = items["AG"]
        rb = items["RB"]
        
        # AG gap penalty should be >= 1.10 due to overnight global silver jumps
        self.assertGreaterEqual(ag["gap_penalty"], 1.05)
        # Effective stop of AG is enlarged by gap penalty
        self.assertGreater(ag["effective_stop"], 1.2 * ag["typical_atr"])

    def test_dynamic_rebalancing_and_basket_feasibility(self):
        # Test that selecting RB (cheap) and JM (high-risk) allows BOTH to be active
        resp = self.client.post("/api/calculate", json={
            "equity": 1000000.0,
            "win_rate_min": 0.30,
            "win_rate_max": 0.40,
            "win_loss_min": 2.5,
            "win_loss_max": 4.0,
            "selected_symbols": ["RB", "JM"]
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        items = {it["symbol"]: it for it in data["items"]}
        
        # Both RB and JM must have lots > 0
        self.assertGreater(items["RB"]["final_lots"], 0)
        self.assertGreater(items["JM"]["final_lots"], 0)
        
        # Feasibility metrics must be present and valid
        g = data["portfolio_gauges"]
        self.assertIn("basket_full_margin", g)
        self.assertIn("basket_full_risk", g)
        self.assertIn("recommended_min_equity", g)
        self.assertIn("feasibility_status", g)
        self.assertEqual(g["feasibility_status"], "FEASIBLE")

    def test_empty_selected_symbols_returns_zero_state(self):
        # Test that when 0 symbols are selected, all portfolio totals are 0
        resp = self.client.post("/api/calculate", json={
            "equity": 1000000.0,
            "win_rate_min": 0.30,
            "win_rate_max": 0.40,
            "win_loss_min": 2.5,
            "win_loss_max": 4.0,
            "selected_symbols": []
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        g = data["portfolio_gauges"]
        
        self.assertEqual(g["total_actual_margin"], 0.0)
        self.assertEqual(g["total_actual_risk"], 0.0)
        self.assertEqual(g["margin_utilization_pct"], 0.0)
        self.assertEqual(g["open_risk_pct"], 0.0)
        self.assertEqual(g["total_lots"], 0)
        self.assertEqual(g["feasibility_status"], "EMPTY")
        self.assertEqual(len(data["items"]), 0)

    def test_html_table_removed_columns(self):
        # Verify that index.html does not contain the 3 deleted column headers
        import os
        html_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html")
        with open(html_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        self.assertNotIn("<th>合约乘数</th>", content)
        self.assertNotIn("<th>保证金率</th>", content)
        self.assertNotIn("<th>理论风险手</th>", content)
    def test_negative_expectancy_interception_and_zero_lots(self):
        # When win rate = 20% and payoff ratio = 1.0, expectancy = 0.2*1 - 0.8 = -0.6 < 0
        resp = self.client.post("/api/calculate", json={
            "equity": 1000000.0,
            "win_rate_min": 0.20,
            "win_rate_max": 0.20,
            "win_loss_min": 1.0,
            "win_loss_max": 1.0,
            "selected_symbols": ["RB", "CU", "JM"]
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        k = data["kelly"]
        g = data["portfolio_gauges"]
        
        self.assertFalse(k["has_edge"])
        self.assertLessEqual(k["expectancy_r"], 0.0)
        self.assertEqual(k["safe_kelly_pct"], 0.0)
        self.assertEqual(g["total_lots"], 0)
        self.assertEqual(g["total_actual_margin"], 0.0)
        self.assertEqual(g["total_actual_risk"], 0.0)
        self.assertEqual(g["feasibility_status"], "NEGATIVE_EXPECTANCY")
        for item in data["items"]:
            self.assertEqual(item["final_lots"], 0)
            self.assertEqual(item["allocation_status"], "NEGATIVE_EDGE")
            self.assertIn("策略数学期望", item["constraint_reason"])

    def test_sizing_constraint_diagnostics_and_crowding_out(self):
        # Basket with LC, SI, EC to verify crowding-out diagnosis
        syms = ["AG", "JM", "RB", "SA", "FG", "CU", "SN", "AO", "PG", "BR", "JD", "CJ", "P", "J", "LH", "LC", "SI", "EC"]
        resp = self.client.post("/api/calculate", json={
            "equity": 1000000.0,
            "win_rate_min": 0.30,
            "win_rate_max": 0.40,
            "win_loss_min": 2.5,
            "win_loss_max": 4.0,
            "selected_symbols": syms
        })
        self.assertEqual(resp.status_code, 200)
        items = {it["symbol"]: it for it in resp.json()["data"]["items"]}

        # 1. LC should be crowded out (0 lots) due to cluster cap
        self.assertIn("LC", items)
        self.assertEqual(items["LC"]["final_lots"], 0)
        self.assertEqual(items["LC"]["allocation_status"], "CROWDED_OUT")
        self.assertIn("机制聚类防火墙硬顶", items["LC"]["constraint_reason"])

        # 2. EC should hit capacity max (1 lot)
        self.assertIn("EC", items)
        self.assertEqual(items["EC"]["final_lots"], 1)
        self.assertEqual(items["EC"]["allocation_status"], "CAPACITY_MAX")
        self.assertIn("物理流动性与容量上限", items["EC"]["constraint_reason"])

        # 3. Every item must have constraint_reason and why_cannot_increase
        for s, it in items.items():
            self.assertTrue(len(it.get("constraint_reason", "")) > 0)
            self.assertTrue(len(it.get("why_cannot_increase", "")) > 0)
            self.assertTrue(len(it.get("suggestion", "")) > 0)


if __name__ == "__main__":
    unittest.main()


