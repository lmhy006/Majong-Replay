"""replay.adapter 单元测试（阶段四）。

验证事件流 -> majiang-ui paipu 对象的基本结构。
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "proto"))

from proto.decoder import GameEvent  # noqa: E402
from replay.adapter import events_to_paipu  # noqa: E402


def _events_from_dicts(items):
    return [
        GameEvent(
            step=int(e.get("step", i + 1)),
            type=str(e.get("type", "")),
            full_name=str(e.get("full_name", "")),
            seat=e.get("seat"),
            data=dict(e.get("data", {}) or {}),
        )
        for i, e in enumerate(items)
    ]


def _build_events():
    return [
        {
            "step": 1,
            "type": "new_round",
            "seat": None,
            "data": {
                "chang": 0, "ju": 0, "ben": 0,
                "scores": [25000] * 4,
                "liqibang": 0,
                "tiles0": ["1m", "2m", "3m", "4m", "5m", "6m", "7m", "8m", "9m",
                            "1m", "2m", "3m", "4m", "5m"],
                "tiles1": ["1m", "1m", "2p", "2p", "2p", "2p",
                            "3p", "4p", "5p", "6p", "7p", "8p", "9p"],
                "tiles2": ["1s", "2s", "3s", "4s", "5s", "6s", "7s",
                            "8s", "9s", "1s", "2s", "3s", "4s"],
                "tiles3": ["1z", "2z", "3z", "4z", "5z", "6z", "7z",
                            "1z", "2z", "3z", "4z", "5z", "6z"],
                "dora": "1z",
                "left_tile_count": 70,
            },
        },
        {
            "step": 2,
            "type": "discard_tile", "seat": 0,
            "data": {"seat": 0, "tile": "1m", "is_liqi": False},
        },
        {
            "step": 3,
            "type": "chi_peng_gang", "seat": 1,
            "data": {"seat": 1, "type": 1, "tiles": ["1m", "1m", "1m"], "froms": [1, 1, 0]},
        },
        {
            "step": 4,
            "type": "an_gang_add_gang", "seat": 1,
            "data": {"seat": 1, "type": 3, "tiles": "2p"},
        },
        {
            "step": 5,
            "type": "deal_tile", "seat": 1,
            "data": {"seat": 1, "tile": "5m", "left_tile_count": 69},
        },
        {
            "step": 6,
            "type": "discard_tile", "seat": 1,
            "data": {"seat": 1, "tile": "5m", "is_liqi": True, "is_wliqi": False},
        },
        {
            "step": 7,
            "type": "hu", "seat": 1,
            "data": {"seat": 1, "hules": [{"seat": 1, "zimo": True}],
                     "scores": [25000, 24000, 25000, 25000]},
        },
        {
            "step": 8,
            "type": "new_round", "seat": None,
            "data": {
                "chang": 0, "ju": 1, "ben": 0,
                "scores": [25000, 24000, 25000, 25000],
                "liqibang": 0,
                "tiles0": ["1m", "2m", "3m", "4m", "5m", "6m", "7m",
                            "8m", "9m", "1m", "2m", "3m", "4m"],
                "tiles1": ["1p", "2p", "3p", "4p", "5p", "6p", "7p",
                            "8p", "9p", "1p", "2p", "3p", "4p", "5p"],
                "tiles2": ["1s", "2s", "3s", "4s", "5s", "6s", "7s",
                            "8s", "9s", "1s", "2s", "3s", "4s"],
                "tiles3": ["1z", "2z", "3z", "4z", "5z", "6z", "7z",
                            "1z", "2z", "3z", "4z", "5z", "6z"],
                "dora": "2z",
                "left_tile_count": 70,
            },
        },
        {
            "step": 9,
            "type": "discard_tile", "seat": 1,
            "data": {"seat": 1, "tile": "1p", "is_liqi": False},
        },
        {
            "step": 10,
            "type": "no_tile", "seat": None,
            "data": {"gameend": True,
                     "scores": [{"seat": 0, "delta_scores": [1000, 1000, -1000, -1000]}]},
        },
    ]


class TestAdapter(unittest.TestCase):
    def setUp(self):
        self.paipu = events_to_paipu(_events_from_dicts(_build_events()))

    def test_top_level_fields(self):
        self.assertEqual(self.paipu["qijia"], 0)
        self.assertEqual(len(self.paipu["player"]), 4)
        self.assertEqual(len(self.paipu["log"]), 2)
        self.assertEqual(len(self.paipu["defen"]), 4)

    def test_first_log_starts_with_qipai(self):
        first_log = self.paipu["log"][0]
        self.assertIn("qipai", first_log[0])
        qipai = first_log[0]["qipai"]
        self.assertEqual(qipai["jushu"], 0)
        self.assertEqual(qipai["changbang"], 0)
        self.assertEqual(len(qipai["shoupai"]), 4)
        self.assertEqual(len(qipai["defen"]), 4)

    def test_event_types_present(self):
        first_log = self.paipu["log"][0]
        types = []
        for item in first_log:
            types.append(next(iter(item)))
        self.assertIn("dapai", types)
        self.assertIn("fulou", types)
        self.assertIn("gang", types)
        self.assertIn("gangzimo", types)
        self.assertIn("hule", types)

    def test_liqi_star_marker(self):
        first_log = self.paipu["log"][0]
        liqi_dapai = [
            item["dapai"]
            for item in first_log
            if "dapai" in item and item["dapai"]["p"].endswith("*")
        ]
        self.assertTrue(liqi_dapai)

    def test_pingju_in_second_log(self):
        second_log = self.paipu["log"][1]
        self.assertIn("pingju", second_log[-1])
        pingju = second_log[-1]["pingju"]
        self.assertEqual(len(pingju["shoupai"]), 4)
        self.assertEqual(len(pingju["fenpei"]), 4)


if __name__ == "__main__":
    unittest.main()
