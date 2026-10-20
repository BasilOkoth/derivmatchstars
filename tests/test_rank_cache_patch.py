"""Regression checks for the pre-ranked / 200-history patch.

Run: python -m unittest discover -s tests -v
"""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "app" / "engine.py").read_text()


class RankPipelineChecks(unittest.TestCase):
    def test_history_retains_200(self):
        self.assertIn("deque(maxlen=200)", SOURCE)
        self.assertIn("prices[-200:]", SOURCE)

    def test_stable_v1_uses_100(self):
        self.assertIn("list(self._digit_history(sid))[-100:]", SOURCE)

    def test_cached_selection(self):
        self.assertIn("prepared_snapshot if prepared_snapshot is not None", SOURCE)

    def test_recovery_uses_pretrigger_snapshot(self):
        handler = SOURCE.split("async def _handle_strategy_tick(", 1)[1].split(
            "async def ", 1
        )[0]
        self.assertLess(handler.index("prepared_for_this_tick ="),
                        handler.index("history.append(int(digit))"))
        self.assertIn("current_snapshot = prepared_for_this_tick", handler)
        self.assertIn("prepared_snapshot=prepared_for_this_tick", handler)

    def test_final_buy_gate_respects_locked_digit(self):
        gate = SOURCE.split("def _claim_account_buy(", 1)[1].split("def ", 1)[0]
        self.assertIn("locked_snapshot", gate)
        self.assertIn("gate_minimum <= 0", gate)

    def test_claim_does_not_recompute(self):
        claim = SOURCE.split("def _claim_account_buy(", 1)[1].split("def ", 1)[0]
        self.assertNotIn("self._score_all_digits(", claim)

    def test_precision_fallback_in_live_path(self):
        self.assertIn("tick, fallback_decimals=self.tick_precision.get(int(sid))", SOURCE)

    def test_shadow_200_exists(self):
        self.assertIn('snapshot["shadow_200"]', SOURCE)


if __name__ == "__main__":
    unittest.main()
