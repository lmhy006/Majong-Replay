"""ai_module.obs_encoder 单元测试（阶段五）。

当前验证基础编码逻辑；Mortal 官方对齐后需补充维度/通道级断言。
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ai_module.obs_encoder import (  # noqa: E402
    MORTAL_OBS_SHAPE,
    count_hand,
    encode_mortal_obs,
    encode_obs,
    obs_shape,
    tile_to_idx,
)
from game_state.state_model import GameSnapshot, PlayerState  # noqa: E402


def _make_snapshot():
    players = [PlayerState(seat=i) for i in range(4)]
    players[0].hand = [
        "1m", "1m", "2m", "3m", "4m", "5m", "6m", "7m", "8m", "9m",
        "1p", "1p", "1p", "1z",
    ]
    players[1].discards = ["1m", "2m", "3m"]
    players[2].discards = ["5z", "6z"]
    players[3].discards = ["9p"]
    return GameSnapshot(
        step=1,
        event_type="new_round",
        event_summary={},
        players=players,
        scores=[25000] * 4,
        doras=["1z"],
        left_tile_count=70,
        dealer_seat=0,
    )


class TestObsEncoder(unittest.TestCase):
    def test_tile_to_idx(self):
        self.assertEqual(tile_to_idx("1m"), 0)
        self.assertEqual(tile_to_idx("m1"), 0)
        self.assertEqual(tile_to_idx("0m"), 4)  # 赤5 -> 5m
        self.assertEqual(tile_to_idx("m0"), 4)
        self.assertEqual(tile_to_idx("1z"), 27)

    def test_count_hand(self):
        hand = ["1m", "1m", "2m"]
        arr = count_hand(hand)
        self.assertEqual(arr.shape, (34,))
        self.assertEqual(arr[0], 2)
        self.assertEqual(arr[1], 1)

    def test_encode_obs_shape(self):
        snap = _make_snapshot()
        obs = encode_obs(snap, 0)
        self.assertEqual(obs.shape, (obs_shape(),))
        self.assertEqual(obs.dtype.name, "float32")

    def test_encode_obs_contains_hand(self):
        snap = _make_snapshot()
        obs = encode_obs(snap, 0)
        # 手牌部分前 34 维：1m 有两张
        self.assertEqual(obs[0], 2)
        # 宝牌指示 1z 在 27
        # 手牌 34 + 副露 4*34 + 牌河 4*34 + 宝牌 34 起始
        dora_start = 34 + 4 * 34 + 4 * 34
        self.assertEqual(obs[dora_start + 27], 1)

    def test_encode_mortal_obs_shape(self):
        snap = _make_snapshot()
        obs = encode_mortal_obs(snap, 0)
        self.assertEqual(obs.shape, MORTAL_OBS_SHAPE)
        self.assertEqual(obs.dtype.name, "float32")


if __name__ == "__main__":
    unittest.main()
