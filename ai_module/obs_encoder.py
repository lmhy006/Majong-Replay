"""Mortal 标准局面编码器（阶段五）。

注意：当前为基于公开日麻 AI 常见特征的初步实现，
后续需要根据 Mortal 官方 obs_encoder 源码/权重进行逐字段对齐。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

import numpy as np

from game_state.state_model import GameSnapshot

NUM_TILES = 34

# Mortal v4 官方 obs 形状：(通道数, 34)
MORTAL_OBS_SHAPE = (1012, 34)
MORTAL_VERSION = 4

# 雀魂格式：1m~9m, 1p~9p, 1s~9s, 1z~7z
TILE_ORDER = [
    f"{n}m" for n in range(1, 10)
] + [
    f"{n}p" for n in range(1, 10)
] + [
    f"{n}s" for n in range(1, 10)
] + [
    f"{n}z" for n in range(1, 8)
]

_TILE_TO_IDX = {t: i for i, t in enumerate(TILE_ORDER)}
# 兼容 majiang-ui 格式 "m1"
_TILE_TO_IDX.update({t[1] + t[0]: i for i, t in enumerate(TILE_ORDER)})


def tile_to_idx(tile: str) -> int:
    """将牌字符串转为 0~33 索引，兼容 '1m' 与 'm1'，赤 0 视为 5。"""
    tile = tile.strip()
    base = tile[:2]
    if base in _TILE_TO_IDX:
        return _TILE_TO_IDX[base]
    # 赤5：0m -> 5m / m0 -> m5
    if base[0] == '0' and base[1] in 'mps':
        base = '5' + base[1]
    elif base[1] == '0' and base[0] in 'mps':
        base = base[0] + '5'
    if base in _TILE_TO_IDX:
        return _TILE_TO_IDX[base]
    raise ValueError(f"未知牌: {tile!r}")


def count_hand(hand: Sequence[str]) -> np.ndarray:
    """手牌/牌列表 -> 34 维计数向量。"""
    arr = np.zeros(NUM_TILES, dtype=np.float32)
    for t in hand:
        arr[tile_to_idx(t)] += 1
    return arr


def count_tiles(tiles: Sequence[str]) -> np.ndarray:
    return count_hand(tiles)


def encode_obs(snapshot: GameSnapshot, seat: int) -> np.ndarray:
    """编码某个视角的完整局面。

    当前输出一个 1D float32 向量（占位实现，后续对齐 Mortal）。
    """
    features: List[np.ndarray] = []

    # 自家手牌
    features.append(count_hand(snapshot.players[seat].hand))

    # 四家副露（每种牌出现次数）
    for p in snapshot.players:
        meld_tiles: List[str] = []
        for m in p.melds:
            meld_tiles.extend(m.tiles)
        features.append(count_tiles(meld_tiles))

    # 四家牌河（每种牌出现次数）
    for p in snapshot.players:
        features.append(count_tiles(p.discards))

    # 宝牌指示
    dora = np.zeros(NUM_TILES, dtype=np.float32)
    for t in snapshot.doras:
        dora[tile_to_idx(t)] += 1
    features.append(dora)

    # 场况标量
    scores = list(snapshot.scores)
    feat_scalar = np.array([
        snapshot.chang,
        snapshot.ju,
        snapshot.ben,
        snapshot.liqibang,
        snapshot.left_tile_count,
        scores[seat],
        scores[(seat + 1) % 4],
        scores[(seat + 2) % 4],
        scores[(seat + 3) % 4],
        snapshot.dealer_seat,
    ], dtype=np.float32)
    features.append(feat_scalar)

    return np.concatenate(features).astype(np.float32)


def obs_shape() -> int:
    """当前占位编码的向量长度。"""
    return NUM_TILES + 4 * NUM_TILES + 4 * NUM_TILES + NUM_TILES + 10


def encode_mortal_obs(snapshot: GameSnapshot, seat: int) -> np.ndarray:
    """Mortal v4 官方 obs 编码（占位实现）。

    官方 obs 形状为 (1012, 34)。当前返回全零矩阵，
    后续需按 Mortal/libriichi/src/state/obs_repr.rs 逐通道填充。
    """
    obs = np.zeros(MORTAL_OBS_SHAPE, dtype=np.float32)
    # TODO: 按 obs_repr.rs 的 v4 分支实现：
    #   tehai / akas / scores / rank / kyoku / honba / kyotaku / bakaze / jikaze
    #   dora_indicators / kawa / tiles_left / doras_owned / doras_seen
    #   kawa_overview / fuuro_overview / ankan_overview / tiles_seen
    #   last_tedashis / riichi_sutehais / riichi_declared / riichi_accepted
    #   waits / furiten / shanten / action features / sp_table 等
    return obs
