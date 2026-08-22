"""ai_module.mortal_inference 单元测试（阶段五）。

不依赖 libriichi，只验证动作索引映射。
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ai_module.mortal_inference import _action_index_from_event  # noqa: E402


class TestActionIndexFromEvent(unittest.TestCase):
    def test_dahai(self):
        self.assertEqual(_action_index_from_event({"type": "dahai", "pai": "1m"}), 0)
        self.assertEqual(_action_index_from_event({"type": "dahai", "pai": "9m"}), 8)
        self.assertEqual(_action_index_from_event({"type": "dahai", "pai": "E"}), 27)
        self.assertEqual(_action_index_from_event({"type": "dahai", "pai": "5mr"}), 34)

    def test_reach(self):
        self.assertEqual(_action_index_from_event({"type": "reach"}), 37)

    def test_chi(self):
        # 被鸣牌 3m，consumed 1m/2m -> high（被鸣牌大于 consumed 两者）
        self.assertEqual(
            _action_index_from_event(
                {"type": "chi", "pai": "3m", "consumed": ["1m", "2m"]}
            ),
            40,
        )
        # 被鸣牌 5m，consumed 4m/6m -> mid
        self.assertEqual(
            _action_index_from_event(
                {"type": "chi", "pai": "5m", "consumed": ["4m", "6m"]}
            ),
            39,
        )
        # 被鸣牌 7m，consumed 8m/9m -> low
        self.assertEqual(
            _action_index_from_event(
                {"type": "chi", "pai": "7m", "consumed": ["8m", "9m"]}
            ),
            38,
        )

    def test_pon_and_kan(self):
        self.assertEqual(_action_index_from_event({"type": "pon"}), 41)
        self.assertEqual(_action_index_from_event({"type": "daiminkan"}), 42)
        self.assertEqual(_action_index_from_event({"type": "ankan"}), 42)
        self.assertEqual(_action_index_from_event({"type": "kakan"}), 42)

    def test_hora_ryukyoku(self):
        self.assertEqual(_action_index_from_event({"type": "hora"}), 43)
        self.assertEqual(_action_index_from_event({"type": "ryukyoku"}), 44)


if __name__ == "__main__":
    unittest.main()
