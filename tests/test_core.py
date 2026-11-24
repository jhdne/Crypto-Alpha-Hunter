from datetime import datetime, timezone, timedelta
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import config
import job2_project_hunter as job2
import job3_self_evolver as job3
import llm_engine
import models
import notifier


class TestCorePipelineV72(unittest.TestCase):
    def test_extract_json_handles_think_and_fences(self):
        raw = '<think>reasoning...</think>\n```json\n{"ai_score": 85, "ok": true}\n```'
        parsed = llm_engine.extract_json(raw)
        self.assertEqual(parsed, {"ai_score": 85, "ok": True})

    def test_ask_ai_accepts_role_and_json_mode(self):
        with patch.object(llm_engine, "call_llm", return_value='{"ok": true}') as mock_call:
            res = llm_engine.ask_ai("test prompt", role="evolver_agent", json_mode=True)
            self.assertEqual(res, '{"ok": true}')
            mock_call.assert_called_once()
            _, kwargs = mock_call.call_args
            self.assertEqual(kwargs["agent_role"], "evolver_agent")
            self.assertTrue(kwargs["json_mode"])

    def test_v71_flexible_momentum_allows_healthy_high_pump_runner(self):
        guard = config.DEFAULT_EVOLUTION_STATE["guardrails"]
        healthy_runner = {
            "chg_1h": 8.0,
            "chg_6h": 25.0,
            "chg_24h": 85.0,
            "buy_ratio": 60.0,
            "mc_usd": 1200000.0,
            "vol_24h": 400000.0,
            "vol_1h": 35000.0,
            "buys_24h": 500,
            "sells_24h": 300,
            "pool_age_hours": 36.0,
        }
        ok, label, score, _ = job2.assess_entry_position(healthy_runner, guard, True)
        self.assertTrue(ok)
        self.assertIn("加速", label)
        self.assertGreater(score, 70.0)

    def test_price_cross_verification_blocks_single_source_90_dollar_outlier(self):
        # 模拟 $CLAUDIA 原价 $0.006882，单源错误返回 $90.5000（>50倍偏离且无第二源确认）-> 必须熔断拒收！
        resolved = job3.verify_and_resolve_price(
            symbol="CLAUDIA",
            chain="solana",
            contract="2j5SaS7xy776qCBpyPQbZjyQSAtKiFgrwjfErthnW2ZM",
            coin_id="",
            ref_price=0.006882,
            dex_quote=(90.5, 50000.0),
            gecko_quote=None,
        )
        self.assertIsNone(resolved)

        # 双源一致（Dex $0.0092 vs Gecko $0.0091）-> 正常采信高流动性报价！
        resolved_ok = job3.verify_and_resolve_price(
            symbol="CLAUDIA",
            chain="solana",
            contract="2j5SaS7xy776qCBpyPQbZjyQSAtKiFgrwjfErthnW2ZM",
            coin_id="",
            ref_price=0.006882,
            dex_quote=(0.0092, 380000.0),
            gecko_quote=(0.0091, 350000.0),
        )
        self.assertEqual(resolved_ok, 0.0092)

    def test_job3_cleans_corrupted_peak_and_records_verified_roi(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            orig_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                os.makedirs("docs", exist_ok=True)
                sample_db = {
                    "evolution_state": dict(config.DEFAULT_EVOLUTION_STATE, generation=1),
                    "projects": [
                        {
                            "name": "Claudia",
                            "symbol": "CLAUDIA",
                            "chain": "solana",
                            "contract": "2j5SaS7xy776qCBpyPQbZjyQSAtKiFgrwjfErthnW2ZM",
                            "price": 0.006882,
                            "recommended_price": 0.006882,
                            "peak_price": 90.5,
                            "peak_roi_pct": 1315007.4,
                            "mc_wan": 50.0,
                            "chg_24h": 15.0,
                            "buy_ratio": 58.0,
                            "roi_history": [0.0, 1315007.4],
                        }
                    ],
                }
                with open("docs/alpha_db.json", "w", encoding="utf-8") as f:
                    json.dump(sample_db, f)

                key = ("solana", "2j5sas7xy776qcbpypqbzjyqsatkifgrwjferthnw2zm")
                with patch.object(job3, "_batch_fetch_dexscreener_prices", return_value={key: (0.0092, 370000.0)}), \
                     patch.object(llm_engine, "ask_ai", return_value=""), \
                     patch.object(config, "TABLE_ID_ALPHA", ""), \
                     patch.object(config, "TABLE_ID_CONFIG", ""):
                    job3.run()

                with open("docs/alpha_db.json", "r", encoding="utf-8") as f:
                    updated = json.load(f)
                p0 = updated["projects"][0]
                self.assertEqual(p0["live_price"], 0.0092)
                self.assertAlmostEqual(p0["live_roi_pct"], 33.68, places=1)
                self.assertEqual(p0["peak_price"], 0.0092)
                self.assertEqual(p0["trend_status"], "主升浪")
            finally:
                os.chdir(orig_cwd)

    def test_notifier_splits_today_and_collapsible_history_with_sparkline(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            orig_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                os.makedirs("docs", exist_ok=True)
                tz_bj = timezone(timedelta(hours=8))
                today_str = datetime.now(tz_bj).strftime("%Y-%m-%d")

                sample_db = {
                    "updated_at": f"{today_str} 12:00:00",
                    "evolution_state": config.DEFAULT_EVOLUTION_STATE,
                    "allocation_matrix": [],
                    "hot_keywords": [],
                    "vc_And_news": [],
                    "tracks": [],
                    "projects": [
                        {
                            "name": "TodayGem",
                            "symbol": "TDY",
                            "chain": "solana",
                            "contract": "0xtoday",
                            "price": 0.01,
                            "mc_wan": 80.0,
                            "liq_wan": 15.0,
                            "vol_wan": 40.0,
                            "score": 88.0,
                            "found_at": f"{today_str} 11:05",
                        },
                        {
                            "name": "HistGem",
                            "symbol": "HST",
                            "chain": "bsc",
                            "contract": "0xhist",
                            "price": 0.02,
                            "recommended_price": 0.02,
                            "live_price": 0.03,
                            "live_roi_pct": 50.0,
                            "roi_history": [0.0, 20.0, 50.0],
                            "trend_status": "主升浪",
                            "mc_wan": 120.0,
                            "liq_wan": 25.0,
                            "vol_wan": 60.0,
                            "score": 84.5,
                            "found_at": "2026-11-20 09:05",
                        },
                    ],
                }
                with open("docs/alpha_db.json", "w", encoding="utf-8") as f:
                    json.dump(sample_db, f)

                notifier.build_dashboard()
                with open("docs/index.html", "r", encoding="utf-8") as f:
                    html_out = f.read()

                self.assertIn("TDY", html_out)
                self.assertIn("2026-11-20", html_out)
                self.assertIn("<details class=\"history-day", html_out)
                self.assertIn("<polyline", html_out)
                self.assertIn("主升浪", html_out)
            finally:
                os.chdir(orig_cwd)


if __name__ == "__main__":
    unittest.main()