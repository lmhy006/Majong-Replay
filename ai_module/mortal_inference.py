"""基于 libriichi + MortalEngine 的推理器（阶段五）。

在 mjai 事件流上驱动 PlayerState，并在每个可行动作点调用
MortalEngine 生成 AI 推荐动作，同时记录实战动作并标记是否一致。
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional, Sequence

from .mortal_model_adapter import MortalModelAdapter

# mjai 牌字符串 -> action index（0..36）
_TILE_ACTION_INDEX: Dict[str, int] = {}
for _i, _t in enumerate(
    [f"{n}m" for n in range(1, 10)]
    + [f"{n}p" for n in range(1, 10)]
    + [f"{n}s" for n in range(1, 10)]
    + ["E", "S", "W", "N", "P", "F", "C"]
    + ["5mr", "5pr", "5sr"]
):
    _TILE_ACTION_INDEX[_t] = _i


def _action_index_from_event(ev: Dict) -> Optional[int]:
    """将 mjai 动作事件映射为 Mortal action index。"""
    typ = ev.get("type")
    if typ == "dahai":
        return _TILE_ACTION_INDEX.get(ev.get("pai", ""))
    if typ == "reach":
        return 37
    if typ == "chi":
        # 38/39/40：根据被鸣牌在顺子中的位置判断低/中/高
        pai = ev.get("pai", "")
        consumed = ev.get("consumed", [])
        nums = []
        for t in [pai] + list(consumed):
            if t in _TILE_ACTION_INDEX:
                # 提取数字（mjai 数牌 '1m' 或字牌）
                if t[0].isdigit():
                    nums.append(int(t[0]))
        if len(nums) == 3:
            nums.sort()
            pos = nums.index(int(pai[0])) if pai and pai[0].isdigit() else 1
            if pos == 0:
                return 38
            if pos == 1:
                return 39
            return 40
        return None
    if typ == "pon":
        return 41
    if typ in ("daiminkan", "ankan", "kakan"):
        return 42
    if typ == "hora":
        return 43
    if typ == "ryukyoku":
        return 44
    return None


class MortalInference:
    """使用 Mortal 官方引擎在牌谱上进行推理。"""

    def __init__(self, adapter: MortalModelAdapter, player_id: int = 0):
        self.adapter = adapter
        self.player_id = player_id

    def infer(self, mjai_events: Sequence[Dict]) -> List[Dict]:
        """遍历 mjai 事件（dict 列表），返回每个可行动作点的 AI 推荐与实战动作。"""
        import libriichi.state as s

        ps = s.PlayerState(self.player_id)
        results: List[Dict] = []

        for i, ev in enumerate(mjai_events):
            cans = ps.update(json.dumps(ev, ensure_ascii=False))
            if cans.can_act:
                obs, mask = ps.encode_obs(4, False)
                actions, q_out, masks, _ = self.adapter.engine.react_batch(
                    [obs], [mask], None
                )
                ai_action = int(actions[0])
                actual_action = self._find_actual_action(mjai_events, i + 1)
                results.append({
                    "event_idx": i,
                    "action": ai_action,
                    "actual_action": actual_action,
                    "is_mistake": (
                        actual_action is not None and actual_action != ai_action
                    ),
                    "q": q_out[0],
                    "mask": [bool(x) for x in mask],
                })

        return results

    def _find_actual_action(
        self,
        mjai_events: Sequence[Dict],
        start: int,
    ) -> Optional[int]:
        """从当前决策点向后找该玩家的实战动作；若被其他玩家行动打断则为 pass(45)。"""
        for ev in mjai_events[start:]:
            typ = ev.get("type")
            if typ == "end_kyoku":
                return 45
            if ev.get("actor") == self.player_id:
                idx = _action_index_from_event(ev)
                if idx is not None:
                    return idx
            # 其他玩家的行动（摸牌/打牌/鸣牌/和牌/流局）表示当前玩家已过
            if typ in (
                "tsumo", "dahai", "reach", "chi", "pon",
                "daiminkan", "ankan", "kakan", "hora", "ryukyoku",
            ) and ev.get("actor") != self.player_id:
                return 45
        return 45
