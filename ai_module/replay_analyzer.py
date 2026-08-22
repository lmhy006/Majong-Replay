"""复盘对比、失误分析、报告生成（阶段五）。

使用 Mortal 官方引擎在 mjai 事件流上逐决策点推理，生成 AI 推荐。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from proto.decoder import GameEvent

from .mortal_model_adapter import MortalModelAdapter


class ReplayAnalyzer:
    """逐决策点对比实战动作与 AI 最优动作，生成结构化复盘数据。"""

    def __init__(self, adapter: MortalModelAdapter, player_id: int = 0):
        self._adapter = adapter
        self._player_id = player_id

    def analyze_replay(
        self,
        events: Sequence[GameEvent],
        seat: Optional[int] = None,
    ) -> Dict:
        """分析整份牌谱（事件流），返回 AI 推荐决策列表。

        当前先输出每个可行动作点的 AI 推荐动作与 Q 值；
        实战动作对比/失误打分将在后续版本补充。
        """
        try:
            from .mjai_converter import events_to_mjai
            from .mortal_inference import MortalInference
        except ImportError:
            return {"seat": seat, "decision_count": 0, "decisions": [], "error": "libriichi 不可用"}

        player_id = seat if seat is not None else self._player_id
        try:
            mjai_events = events_to_mjai(events)
            inference = MortalInference(self._adapter, player_id=player_id)
            decisions = inference.infer(mjai_events)
        except (RuntimeError, ImportError, NotImplementedError):
            return {"seat": player_id, "decision_count": 0, "decisions": [], "error": "推理不可用"}

        mistake_count = sum(1 for d in decisions if d.get("is_mistake"))
        mistake_idxs = [d["event_idx"] for d in decisions if d.get("is_mistake")]
        return {
            "seat": player_id,
            "decision_count": len(decisions),
            "mistake_count": mistake_count,
            "mistake_rate": round(mistake_count / len(decisions), 4) if decisions else 0.0,
            "summary": {
                "decision_count": len(decisions),
                "mistake_count": mistake_count,
                "mistake_event_idxs": mistake_idxs,
            },
            "decisions": decisions,
        }
