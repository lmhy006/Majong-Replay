"""本地推理引擎（阶段五）。

当前状态：等待 Mortal 网络结构对齐后实现前向推理。
"""

from __future__ import annotations

from typing import Dict, List

from game_state.state_model import GameSnapshot

from .mortal_model_adapter import MortalModelAdapter
from .obs_encoder import encode_obs


class InferEngine:
    """统一推理接口：输入对局快照，输出动作概率/最优动作。"""

    def __init__(self, adapter: MortalModelAdapter):
        self._adapter = adapter

    def evaluate_actions(self, snapshot: GameSnapshot, seat: int) -> Dict:
        """返回该视角下的动作概率与最优动作。

        当前为占位实现，等待 Mortal 网络结构对齐后完成。
        """
        if not self._adapter.loaded:
            raise RuntimeError("模型尚未加载，请先调用 adapter.load()")

        obs = encode_obs(snapshot, seat)
        # TODO: obs -> model -> 46 类动作概率
        raise NotImplementedError(
            "Mortal 网络结构尚未对齐，暂无法完成推理；请提供 Mortal 源码/权重后继续"
        )
