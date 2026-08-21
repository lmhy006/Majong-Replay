"""game_state 状态机单元测试（阶段三）。

使用自洽构造的事件流验证：
    * 快照数量与事件数一致
    * new_round 庄家判定（起手 14 张）
    * 立直状态记录（declared/tile/liqibang/扣分）
    * 吃碰、暗杠、加杠等手牌/副露更新
    * 多局切换时立直重置
    * dict 事件流入口与 JSON 往返
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "proto"))

from game_state.game_simulator import simulate_from_dicts  # noqa: E402
from game_state.snapshot import load_snapshots, save_snapshots, snapshots_to_dict  # noqa: E402
from game_state.state_model import GameSnapshot  # noqa: E402


def _build_events():
    """构造一个自洽的小牌谱：吃碰 -> 暗杠 -> 摸牌 -> 立直打牌 -> 和牌 -> 第二局 -> 流局。"""
    return [
        {
            "step": 1,
            "type": "new_round",
            "seat": None,
            "data": {
                "chang": 0,
                "ju": 0,
                "ben": 0,
                "scores": [25000, 25000, 25000, 25000],
                "liqibang": 0,
                # 庄家座位 0 起手 14 张
                "tiles0": ["A"] * 14,
                # 座位 1 含两张 A，可碰座位 0 打出的 A；其余为 B
                "tiles1": ["B"] * 11 + ["A", "A"],
                "tiles2": ["C"] * 13,
                "tiles3": ["D"] * 13,
                "dora": "1z",
                "left_tile_count": 70,
            },
        },
        {
            "step": 2,
            "type": "discard_tile",
            "seat": 0,
            "data": {"seat": 0, "tile": "A", "is_liqi": False},
        },
        {
            "step": 3,
            "type": "chi_peng_gang",
            "seat": 1,
            "data": {
                "seat": 1,
                "type": 1,
                "tiles": ["A", "A", "A"],
                "froms": [1, 1, 0],
            },
        },
        {
            "step": 4,
            "type": "an_gang_add_gang",
            "seat": 1,
            "data": {"seat": 1, "type": 3, "tiles": "B"},
        },
        {
            "step": 5,
            "type": "deal_tile",
            "seat": 1,
            "data": {"seat": 1, "tile": "E", "left_tile_count": 69},
        },
        {
            "step": 6,
            "type": "discard_tile",
            "seat": 1,
            "data": {"seat": 1, "tile": "E", "is_liqi": True, "is_wliqi": False},
        },
        {
            "step": 7,
            "type": "hu",
            "seat": 1,
            "data": {
                "seat": 1,
                "hules": [{"seat": 1, "zimo": True}],
                "scores": [25000, 24000, 25000, 25000],
            },
        },
        {
            "step": 8,
            "type": "new_round",
            "seat": None,
            "data": {
                "chang": 0,
                "ju": 1,
                "ben": 0,
                "scores": [25000, 24000, 25000, 25000],
                "liqibang": 0,
                # 第二局庄家为座位 1（起手 14 张）
                "tiles0": ["C"] * 13,
                "tiles1": ["D"] * 14,
                "tiles2": ["A"] * 13,
                "tiles3": ["B"] * 13,
                "dora": "2z",
                "left_tile_count": 70,
            },
        },
        {
            "step": 9,
            "type": "discard_tile",
            "seat": 1,
            "data": {"seat": 1, "tile": "D", "is_liqi": False},
        },
        {
            "step": 10,
            "type": "no_tile",
            "seat": None,
            "data": {
                "gameend": True,
                "scores": [
                    {
                        "seat": 0,
                        "delta_scores": [1000, 1000, -1000, -1000],
                    }
                ],
            },
        },
    ]


class TestGameSimulator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events = _build_events()
        cls.snapshots = simulate_from_dicts(cls.events)

    def test_snapshot_count_matches_events(self):
        self.assertEqual(len(self.snapshots), len(self.events))

    def test_new_round_dealer_by_14_tiles(self):
        snap = self.snapshots[0]
        self.assertEqual(snap.event_type, "new_round")
        self.assertEqual(snap.dealer_seat, 0)
        self.assertEqual(len(snap.players[0].hand), 14)
        self.assertEqual(len(snap.players[1].hand), 13)

    def test_discard_moves_hand_to_river(self):
        snap = self.snapshots[1]
        self.assertEqual(snap.event_type, "discard_tile")
        self.assertEqual(len(snap.players[0].hand), 13)
        self.assertEqual(snap.players[0].discards, ["A"])

    def test_chi_peng_gang_updates_hand_and_meld(self):
        snap = self.snapshots[2]
        self.assertEqual(snap.event_type, "chi_peng_gang")
        # 碰后座位 1 手牌减少 2 张（13 -> 11）
        self.assertEqual(len(snap.players[1].hand), 11)
        self.assertEqual(len(snap.players[1].melds), 1)
        meld = snap.players[1].melds[0]
        self.assertEqual(meld.type, 1)
        self.assertEqual(meld.tiles, ["A", "A", "A"])
        self.assertEqual(meld.froms, [1, 1, 0])
        # 座位 0 打出的 A 从牌河被鸣走
        self.assertEqual(snap.players[0].discards, [])

    def test_an_gang_updates_hand_and_meld(self):
        snap = self.snapshots[3]
        self.assertEqual(snap.event_type, "an_gang_add_gang")
        # 暗杠前手牌 11，移除 4 张 B 后为 7
        self.assertEqual(len(snap.players[1].hand), 7)
        self.assertEqual(len(snap.players[1].melds), 2)
        gang = snap.players[1].melds[1]
        self.assertEqual(gang.type, 3)
        self.assertEqual(gang.tiles, ["B", "B", "B", "B"])

    def test_add_gang_protocol_type_2(self):
        """协议 RecordAnGangAddGang.type=2 表示加杠，必须从手牌移除 1 张。"""
        events = [
            {
                "step": 1,
                "type": "new_round",
                "seat": None,
                "data": {
                    "chang": 0, "ju": 0, "ben": 0,
                    "scores": [25000] * 4,
                    "liqibang": 0,
                    # 座位 1 有 3 张 A：2 张用于碰，1 张用于加杠
                    "tiles0": ["A"] * 14,
                    "tiles1": ["A"] * 3 + ["B"] * 10,
                    "tiles2": ["C"] * 13,
                    "tiles3": ["D"] * 13,
                    "left_tile_count": 70,
                },
            },
            {
                "step": 2,
                "type": "discard_tile", "seat": 0,
                "data": {"seat": 0, "tile": "A", "is_liqi": False},
            },
            {
                "step": 3,
                "type": "chi_peng_gang", "seat": 1,
                "data": {"seat": 1, "type": 1, "tiles": ["A", "A", "A"], "froms": [1, 1, 0]},
            },
            {
                "step": 4,
                "type": "an_gang_add_gang", "seat": 1,
                "data": {"seat": 1, "type": 2, "tiles": "A"},
            },
        ]
        snaps = simulate_from_dicts(events)
        last = snaps[-1]
        # 碰后手牌 11，加杠后手牌 10
        self.assertEqual(len(last.players[1].hand), 10)
        self.assertEqual(len(last.players[1].melds), 1)
        meld = last.players[1].melds[0]
        self.assertEqual(meld.type, 4)
        self.assertEqual(meld.tiles, ["A", "A", "A", "A"])

    def test_liqi_recorded(self):
        snap = next(s for s in self.snapshots if s.step == 6)
        self.assertEqual(snap.event_type, "discard_tile")
        self.assertTrue(snap.event_summary.get("is_liqi"))

        liqi = snap.players[1].liqi
        self.assertIsNotNone(liqi)
        self.assertTrue(liqi.declared)
        self.assertEqual(liqi.tile, "E")
        self.assertEqual(liqi.declared_step, 6)
        self.assertEqual(snap.liqibang, 1)
        self.assertEqual(snap.players[1].score, 24000)

    def test_liqi_deal_then_discard_deduct_once(self):
        """真实牌谱顺序：deal_tile 携带 liqi 确认 -> discard_tile is_liqi=True。

        必须保证只扣一次 1000 点、只加一根立直棒，且 declared_step 为宣言步。
        """
        events = [
            {
                "step": 1,
                "type": "new_round",
                "seat": None,
                "data": {
                    "chang": 0,
                    "ju": 0,
                    "ben": 0,
                    "scores": [25000] * 4,
                    "liqibang": 0,
                    "tiles0": ["A"] * 14,
                    "tiles1": ["B"] * 13,
                    "tiles2": ["C"] * 13,
                    "tiles3": ["D"] * 13,
                },
            },
            {
                "step": 2,
                "type": "deal_tile",
                "seat": 1,
                "data": {
                    "seat": 1,
                    "tile": "E",
                    "liqi": {"seat": 1, "failed": False},
                },
            },
            {
                "step": 3,
                "type": "discard_tile",
                "seat": 1,
                "data": {
                    "seat": 1,
                    "tile": "E",
                    "is_liqi": True,
                    "is_wliqi": False,
                },
            },
        ]
        snaps = simulate_from_dicts(events)
        last = snaps[-1]
        self.assertEqual(last.players[1].score, 24000)
        self.assertEqual(last.liqibang, 1)
        self.assertTrue(last.players[1].liqi.declared)
        self.assertEqual(last.players[1].liqi.tile, "E")
        self.assertEqual(last.players[1].liqi.score_cost, 1000)
        self.assertEqual(last.players[1].liqi.declared_step, 3)

    def test_hu_updates_scores_and_ends_round(self):
        snap = next(s for s in self.snapshots if s.step == 7)
        self.assertEqual(snap.round_status, "ended")
        self.assertEqual(snap.scores, [25000, 24000, 25000, 25000])

    def test_new_round_resets_liqi_and_melds(self):
        second_new = next(s for s in self.snapshots if s.step == 8)
        self.assertEqual(second_new.dealer_seat, 1)
        for p in second_new.players:
            self.assertIsNone(p.liqi)
            self.assertEqual(p.melds, [])
            self.assertEqual(p.discards, [])

    def test_no_tile_ends_game(self):
        last = self.snapshots[-1]
        self.assertEqual(last.event_type, "no_tile")
        self.assertEqual(last.round_status, "ended")
        self.assertEqual(last.game_status, "ended")
        # delta_scores [1000,1000,-1000,-1000] 叠加到第二局起始分数
        self.assertEqual(last.scores, [26000, 25000, 24000, 24000])

    def test_snapshot_json_roundtrip(self):
        data = snapshots_to_dict(self.snapshots)
        self.assertEqual(data["snapshot_count"], len(self.snapshots))
        restored = [GameSnapshot.model_validate(s) for s in data["snapshots"]]
        self.assertEqual(restored[5].players[1].liqi.tile, "E")

    def test_snapshot_persistence_roundtrip(self):
        """验证 save_snapshots/load_snapshots 的 JSON 持久化链路（mock 文件 IO）。"""
        snaps = self.snapshots[:2]
        captured = {}

        with mock.patch("game_state.snapshot.Path") as mock_path_cls:
            mock_path = mock_path_cls.return_value
            mock_path.__truediv__.return_value.write_text.side_effect = (
                lambda *args, **kwargs: captured.update(text=args[0])
            )
            mock_path.__truediv__.return_value.read_text.return_value = ""

            save_snapshots("test-uuid", snaps, directory="fake-cache")
            # 让 read_text 返回刚写入的内容，模拟磁盘读回
            mock_path.__truediv__.return_value.read_text.return_value = captured["text"]
            loaded = load_snapshots("test-uuid", directory="fake-cache")

        self.assertEqual(len(loaded), len(snaps))
        self.assertEqual(loaded[0].step, snaps[0].step)
        self.assertEqual(loaded[1].event_type, snaps[1].event_type)

    def test_hand_size_sane(self):
        for snap in self.snapshots:
            for p in snap.players:
                self.assertLessEqual(len(p.hand), 14)
                self.assertGreaterEqual(len(p.hand), 0)


if __name__ == "__main__":
    unittest.main()
