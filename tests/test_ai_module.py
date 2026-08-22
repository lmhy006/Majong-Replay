"""ai_module 骨架单元测试（阶段五）。

当前主要验证错误处理与接口骨架；推理核心待 Mortal 权重/网络对齐后补充。
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ai_module.infer_engine import InferEngine  # noqa: E402
from ai_module.mortal_model_adapter import MortalModelAdapter, MortalModelError  # noqa: E402
from ai_module.replay_analyzer import ReplayAnalyzer  # noqa: E402
from game_state.state_model import GameSnapshot, PlayerState  # noqa: E402


def _make_snapshot():
    players = [PlayerState(seat=i) for i in range(4)]
    players[0].hand = ["1m", "2m", "3m", "4m", "5m", "6m", "7m", "8m", "9m",
                       "1p", "2p", "3p", "4p", "5p"]
    return GameSnapshot(
        step=1,
        event_type="new_round",
        event_summary={},
        players=players,
        scores=[25000] * 4,
        doras=["1z"],
        dealer_seat=0,
    )


class TestAiModule(unittest.TestCase):
    def test_adapter_missing_weight(self):
        adapter = MortalModelAdapter(ROOT / "weights" / "no-such-weight.pth")
        with self.assertRaises(MortalModelError):
            adapter.load()

    def test_infer_engine_requires_loaded_model(self):
        adapter = MortalModelAdapter(ROOT / "weights" / "no-such-weight.pth")
        engine = InferEngine(adapter)
        with self.assertRaises(RuntimeError):
            engine.evaluate_actions(_make_snapshot(), 0)

    def test_analyzer_graceful_when_inference_not_ready(self):
        adapter = MortalModelAdapter(ROOT / "weights" / "no-such-weight.pth")
        analyzer = ReplayAnalyzer(adapter)
        result = analyzer.analyze_replay([], 0)
        self.assertEqual(result["decision_count"], 0)


if __name__ == "__main__":
    unittest.main()
