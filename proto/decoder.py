"""雀魂牌谱 Protobuf 解码模块（阶段二）。

将拉取到的二进制牌谱数据解码为结构化对局事件列表，
供阶段三（对局状态机仿真）逐事件推演使用。

数据链路（新版协议，version >= 210715）：

    ResGameRecord.data
      -> Wrapper{ name=".lq.GameDetailRecords", data=GameDetailRecords }
      -> GameDetailRecords.actions[] (GameAction)
      -> GameAction.result = Wrapper{ name=".lq.RecordXxx", data=RecordXxx }
      -> 具体事件消息（摸牌/打牌/鸣牌/和牌/流局等）

旧版协议（version < 210715）：

    GameDetailRecords.records[] 每个元素直接是 Wrapper 序列化

输出：对局全流程事件列表，每项含 step 序号、事件类型、座位与结构化数据。
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# 保证无论从项目根目录还是 proto/ 内部 import，都能找到 protocol_pb2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from google.protobuf.json_format import MessageToDict  # noqa: E402

import protocol_pb2 as pb  # noqa: E402

# ---------------------------------------------------------------------------
# 事件类型注册表：Wrapper.name -> (短名, pb 消息类)
# ---------------------------------------------------------------------------

_RECORD_CLASSES: Dict[str, tuple] = {
    ".lq.RecordNewRound": ("new_round", pb.RecordNewRound),
    ".lq.RecordDealTile": ("deal_tile", pb.RecordDealTile),
    ".lq.RecordDiscardTile": ("discard_tile", pb.RecordDiscardTile),
    ".lq.RecordChiPengGang": ("chi_peng_gang", pb.RecordChiPengGang),
    ".lq.RecordGangResult": ("gang_result", pb.RecordGangResult),
    ".lq.RecordGangResultEnd": ("gang_result_end", pb.RecordGangResultEnd),
    ".lq.RecordAnGangAddGang": ("an_gang_add_gang", pb.RecordAnGangAddGang),
    ".lq.RecordBaBei": ("ba_bei", pb.RecordBaBei),
    ".lq.RecordHule": ("hu", pb.RecordHule),
    ".lq.RecordHuleXueZhanMid": ("hu_xuezhan_mid", pb.RecordHuleXueZhanMid),
    ".lq.RecordHuleXueZhanEnd": ("hu_xuezhan_end", pb.RecordHuleXueZhanEnd),
    ".lq.RecordLiuJu": ("liu_ju", pb.RecordLiuJu),
    ".lq.RecordNoTile": ("no_tile", pb.RecordNoTile),
    ".lq.RecordSelectGap": ("select_gap", pb.RecordSelectGap),
    ".lq.RecordChangeTile": ("change_tile", pb.RecordChangeTile),
    ".lq.RecordRevealTile": ("reveal_tile", pb.RecordRevealTile),
    ".lq.RecordUnveilTile": ("unveil_tile", pb.RecordUnveilTile),
    ".lq.RecordLockTile": ("lock_tile", pb.RecordLockTile),
    ".lq.RecordFillAwaitingTiles": ("fill_awaiting_tiles", pb.RecordFillAwaitingTiles),
}

# 未知事件也可解码（保留原始 name 与数据）
_UNKNOWN_PREFIX = "unknown:"


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GameEvent:
    """单条对局事件。"""

    step: int                       # 全局步数（从 1 递增）
    type: str                       # 短类型名（如 discard_tile）
    full_name: str                  # 协议名（如 .lq.RecordDiscardTile）
    seat: Optional[int]             # 事件关联座位（无则 None）
    data: Dict[str, Any] = field(default_factory=dict)  # 结构化事件数据

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step": self.step,
            "type": self.type,
            "full_name": self.full_name,
            "seat": self.seat,
            "data": self.data,
        }


@dataclass(frozen=True)
class GameDetailResult:
    """整局解码结果。"""

    version: int                    # GameDetailRecords.version
    events: List[GameEvent]         # 事件序列
    raw: bytes = b""                # 原始 GameDetailRecords 字节

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "events": [e.to_dict() for e in self.events],
        }


# ---------------------------------------------------------------------------
# 基础解码
# ---------------------------------------------------------------------------


def _parse_wrapper(data: bytes) -> pb.Wrapper:
    w = pb.Wrapper()
    w.ParseFromString(data)
    return w


def _seat_of(name: str, data: Dict[str, Any], msg: Any = None) -> Optional[int]:
    """从事件数据中提取座位号（优先 pb 原始字段，避免默认值丢失）。"""
    if msg is not None:
        fields = msg.DESCRIPTOR.fields_by_name
        if "seat" in fields:
            return int(getattr(msg, "seat"))
        # 和牌事件：座位在 hules[].seat
        if name in (".lq.RecordHule", ".lq.RecordHuleXueZhanMid", ".lq.RecordHuleXueZhanEnd"):
            if len(getattr(msg, "hules", [])) > 0:
                return int(msg.hules[0].seat)
        return None
    # 兜底：从 dict 提取（无 pb 消息时）
    if "seat" in data and isinstance(data["seat"], int):
        return data["seat"]
    if name in (".lq.RecordHule", ".lq.RecordHuleXueZhanMid", ".lq.RecordHuleXueZhanEnd"):
        hules = data.get("hules") or []
        if hules:
            s = hules[0].get("seat")
            if isinstance(s, int):
                return s
    return None


def decode_event(blob: bytes, step: int = 0) -> GameEvent:
    """解码单个事件（Wrapper 序列化 -> GameEvent）。

    Args:
        blob: Wrapper 序列化字节（name + data）
        step: 事件步数
    """
    w = _parse_wrapper(blob)
    name = w.name
    entry = _RECORD_CLASSES.get(name)
    if entry is None:
        # 未知事件：原样保留 data 原始字节（base64）
        return GameEvent(
            step=step,
            type=_UNKNOWN_PREFIX + name,
            full_name=name,
            seat=None,
            data={"raw_base64": w.data.decode("latin1")} if w.data else {},
        )
    short_name, msg_class = entry
    msg = msg_class()
    msg.ParseFromString(w.data)
    # 保留全部字段（含默认值），避免 seat=0 / type=0 等信息丢失
    data = MessageToDict(
        msg,
        preserving_proto_field_name=True,
        including_default_value_fields=True,
    )
    seat = _seat_of(name, data, msg)
    return GameEvent(step=step, type=short_name, full_name=name, seat=seat, data=data)


def decode_game_detail_records(data: bytes) -> GameDetailResult:
    """解码 GameDetailRecords 序列化字节，返回事件列表。

    同时兼容新旧两种协议版本（新版 actions[] / 旧版 records[]）。
    """
    gd = pb.GameDetailRecords()
    gd.ParseFromString(data)

    events: List[GameEvent] = []
    step = 0

    if gd.version >= 210715 or not gd.records:
        # 新版：actions[] (GameAction)，事件在 result 字段
        for action in gd.actions:
            if not action.result:
                continue
            step += 1
            events.append(decode_event(action.result, step))
    else:
        # 旧版：records[] 每个元素直接是 Wrapper 序列化
        for rec in gd.records:
            step += 1
            events.append(decode_event(rec, step))

    return GameDetailResult(version=gd.version, events=events, raw=data)


def decode_game_record_data(data: bytes) -> GameDetailResult:
    """解码 ResGameRecord.data（Wrapper 外壳）并返回整局事件列表。"""
    w = _parse_wrapper(data)
    if w.name and w.name != ".lq.GameDetailRecords":
        raise ValueError(f"意外的 Wrapper 类型：{w.name!r}（期望 .lq.GameDetailRecords）")
    return decode_game_detail_records(w.data)


# ---------------------------------------------------------------------------
# 便捷接口
# ---------------------------------------------------------------------------


def decode_paipu(data: bytes) -> GameDetailResult:
    """解码完整牌谱数据。

    Args:
        data: ResGameRecord.data（Wrapper 外壳）或裸 GameDetailRecords 字节均可，
              自动识别。

    Returns:
        GameDetailResult（version + 事件列表）
    """
    try:
        return decode_game_record_data(data)
    except Exception:
        return decode_game_detail_records(data)
