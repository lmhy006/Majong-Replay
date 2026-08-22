"""ai_module.mjai_converter 单元测试（阶段五）。

验证雀魂事件 -> mjai 事件的基本结构；libriichi 驱动测试在 .venv 中单独执行。
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "proto"))

from proto.decoder import GameEvent  # noqa: E402
from ai_module.mjai_converter import events_to_mjai, tile_to_mjai  # noqa: E402


def _ev(step, type_, seat, data):
    return GameEvent(step=step, type=type_, full_name="", seat=seat, data=data)


class TestMjaiConverter(unittest.TestCase):
    def test_tile_to_mjai(self):
        self.assertEqual(tile_to_mjai("1m"), "1m")
        self.assertEqual(tile_to_mjai("1z"), "E")
        self.assertEqual(tile_to_mjai("7z"), "C")
        self.assertEqual(tile_to_mjai("0m"), "5mr")
        self.assertEqual(tile_to_mjai("m1"), "1m")

    def test_events_to_mjai_starts_with_start_kyoku(self):
        events = [
            _ev(1, "new_round", None, {
                "chang": 0, "ju": 0, "ben": 0, "liqibang": 0,
                "scores": [25000] * 4, "dora": "1m",
                "tiles0": ["1m", "2m", "3m", "4m", "5m", "6m", "7m", "8m", "9m",
                           "1p", "2p", "3p", "4p", "5p"],
                "tiles1": ["1m", "2m", "3m", "4m", "5m", "6m", "7m",
                           "8m", "9m", "1p", "2p", "3p", "4p"],
                "tiles2": ["1m", "2m", "3m", "4m", "5m", "6m", "7m",
                           "8m", "9m", "1p", "2p", "3p", "4p"],
                "tiles3": ["1m", "2m", "3m", "4m", "5m", "6m", "7m",
                           "8m", "9m", "1p", "2p", "3p", "4p"],
            }),
            _ev(2, "discard_tile", 0, {"seat": 0, "tile": "5p", "is_liqi": False}),
        ]
        mjai = events_to_mjai(events)
        self.assertEqual(mjai[0]["type"], "start_kyoku")
        self.assertEqual(mjai[0]["oya"], 0)
        self.assertEqual(mjai[0]["kyoku"], 1)
        # 庄家第 14 张 5p 被移出，tehais[0] 应为 13 张
        self.assertEqual(len(mjai[0]["tehais"][0]), 13)
        # start_kyoku 后先补庄家 tsumo，再打出第一张
        self.assertEqual(mjai[1]["type"], "tsumo")
        self.assertEqual(mjai[1]["pai"], "5p")
        self.assertEqual(mjai[2]["type"], "dahai")
        self.assertEqual(mjai[2]["pai"], "5p")


if __name__ == "__main__":
    unittest.main()
