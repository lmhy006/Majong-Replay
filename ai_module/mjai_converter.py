"""雀魂牌谱事件 -> mjai 事件转换器（阶段五）。

将我们的 GameEvent 列表转换为 libriichi/mjai 能消费的事件 JSON，
从而用 Mortal 官方引擎进行推理。
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional, Sequence

from proto.decoder import GameEvent

_Z2MJ = {
    "1z": "E", "2z": "S", "3z": "W", "4z": "N",
    "5z": "P", "6z": "F", "7z": "C",
}
_AKA = {
    "0m": "5mr", "0p": "5pr", "0s": "5sr",
}
_BAKAZE = ["E", "S", "W", "N"]


def tile_to_mjai(tile: str) -> str:
    """雀魂牌格式 -> mjai 牌格式。"""
    tile = tile.strip()
    if tile in _Z2MJ:
        return _Z2MJ[tile]
    if tile in _AKA:
        return _AKA[tile]
    # 兼容 majiang-ui 格式 "m1" / "z1"
    if len(tile) == 2 and tile[0] in "mpsz" and tile[1].isdigit():
        tile = tile[1] + tile[0]
    if tile in _Z2MJ:
        return _Z2MJ[tile]
    if tile in _AKA:
        return _AKA[tile]
    return tile


def _dealer_of(data: Dict) -> int:
    for i in range(4):
        if len(data.get(f"tiles{i}", []) or []) == 14:
            return i
    return (int(data.get("chang", 0) or 0) * 4 + int(data.get("ju", 0) or 0)) % 4


def _split_events_by_kyoku(events: Sequence[GameEvent]) -> List[List[GameEvent]]:
    kyokus: List[List[GameEvent]] = []
    cur: List[GameEvent] = []
    for ev in events:
        if ev.type == "new_round":
            if cur:
                kyokus.append(cur)
                cur = []
        cur.append(ev)
    if cur:
        kyokus.append(cur)
    return kyokus


def _start_kyoku(new_round: GameEvent, kyoku_events: List[GameEvent]) -> Dict:
    data = new_round.data
    dealer = _dealer_of(data)
    scores = list(data.get("scores") or [25000] * 4)
    ju = int(data.get("ju", 0) or 0)
    honba = int(data.get("ben", 0) or 0)
    kyotaku = int(data.get("liqibang", 0) or 0)
    dora = data.get("dora") or (data.get("doras") or [None])[0] or "1m"
    bakaze = _BAKAZE[int(data.get("chang", 0) or 0) % 4]

    # 每局第一打应是庄家打出的牌，用它作为庄家第 14 张摸牌
    first_discard = next(
        (e for e in kyoku_events if e.type == "discard_tile" and e.seat == dealer),
        None,
    )
    first_discard_tile = first_discard.data.get("tile") if first_discard else None

    tehais: List[List[str]] = []
    for seat in range(4):
        tiles = list(data.get(f"tiles{seat}", []) or [])
        if seat == dealer and first_discard_tile and first_discard_tile in tiles:
            # 庄家：移除第一打的那张，作为 start_kyoku 后的 tsumo
            tiles = list(tiles)
            tiles.remove(first_discard_tile)
        tehais.append([tile_to_mjai(t) for t in tiles[:13]])

    return {
        "type": "start_kyoku",
        "bakaze": bakaze,
        "dora_marker": tile_to_mjai(dora),
        "kyoku": ju + 1,
        "honba": honba,
        "kyotaku": kyotaku,
        "oya": dealer,
        "scores": scores,
        "tehais": tehais,
    }


def _chi_pon_kan(event: GameEvent) -> Optional[Dict]:
    data = event.data
    seat = event.seat
    if seat is None:
        return None
    tiles = list(data.get("tiles", []) or [])
    froms = list(data.get("froms", []) or [])
    typ = int(data.get("type", 0) or 0)

    target = None
    pai = None
    consumed: List[str] = []
    for t, f in zip(tiles, froms):
        if f == seat:
            consumed.append(tile_to_mjai(t))
        else:
            target = int(f)
            pai = tile_to_mjai(t)

    if pai is None or target is None:
        return None

    if typ == 0:
        return {"type": "chi", "actor": seat, "target": target, "pai": pai, "consumed": consumed[:2]}
    if typ == 1:
        return {"type": "pon", "actor": seat, "target": target, "pai": pai, "consumed": consumed[:2]}
    if typ == 2:
        return {"type": "daiminkan", "actor": seat, "target": target, "pai": pai, "consumed": consumed[:3]}
    return None


def _an_gang_add_gang(event: GameEvent) -> Optional[Dict]:
    data = event.data
    seat = event.seat
    if seat is None:
        return None
    tile = tile_to_mjai(data.get("tiles", ""))
    typ = int(data.get("type", 0) or 0)
    if typ == 3:  # 暗杠
        return {"type": "ankan", "actor": seat, "consumed": [tile] * 4}
    if typ == 2:  # 加杠
        return {"type": "kakan", "actor": seat, "pai": tile, "consumed": [tile] * 3}
    return None


def _hora(event: GameEvent) -> List[Dict]:
    hules = event.data.get("hules", []) or []
    out = []
    for h in hules:
        actor = int(h.get("seat", event.seat if event.seat is not None else 0))
        target = actor if h.get("zimo", False) else event.seat if event.seat is not None else actor
        # 荣和时 target 使用最后打牌者，由调用方修正
        out.append({"type": "hora", "actor": actor, "target": target})
    return out


def events_to_mjai(events: Sequence[GameEvent]) -> List[Dict]:
    """将雀魂事件列表转换为 mjai 事件列表。"""
    mjai_events: List[Dict] = []
    last_discard_seat: Optional[int] = None

    for kyoku_events in _split_events_by_kyoku(events):
        if not kyoku_events or kyoku_events[0].type != "new_round":
            continue
        new_round = kyoku_events[0]
        start = _start_kyoku(new_round, kyoku_events)
        mjai_events.append(start)

        # 庄家第 14 张：start_kyoku 后先补一个 tsumo，再打第一张
        dealer = int(start["oya"])
        first_discard = next(
            (e for e in kyoku_events if e.type == "discard_tile" and e.seat == dealer),
            None,
        )
        if first_discard and first_discard.data.get("tile"):
            mjai_events.append({
                "type": "tsumo",
                "actor": dealer,
                "pai": tile_to_mjai(first_discard.data["tile"]),
            })

        for ev in kyoku_events[1:]:
            if ev.type == "deal_tile":
                if ev.seat is not None:
                    mjai_events.append({
                        "type": "tsumo",
                        "actor": ev.seat,
                        "pai": tile_to_mjai(ev.data.get("tile", "")),
                    })
            elif ev.type == "discard_tile":
                if ev.seat is None:
                    continue
                pai = tile_to_mjai(ev.data.get("tile", ""))
                if ev.data.get("is_liqi"):
                    mjai_events.append({"type": "reach", "actor": ev.seat})
                mjai_events.append({
                    "type": "dahai",
                    "actor": ev.seat,
                    "pai": pai,
                    "tsumogiri": bool(ev.data.get("moqie", False)),
                })
                if ev.data.get("is_liqi"):
                    mjai_events.append({"type": "reach_accepted", "actor": ev.seat})
                last_discard_seat = ev.seat
            elif ev.type == "chi_peng_gang":
                m = _chi_pon_kan(ev)
                if m:
                    mjai_events.append(m)
            elif ev.type == "an_gang_add_gang":
                m = _an_gang_add_gang(ev)
                if m:
                    mjai_events.append(m)
            elif ev.type == "hu":
                for h in _hora(ev):
                    if h["target"] == h["actor"]:
                        h["target"] = h["actor"]
                    elif last_discard_seat is not None:
                        h["target"] = last_discard_seat
                    mjai_events.append(h)
            elif ev.type in ("no_tile", "liu_ju"):
                mjai_events.append({"type": "ryukyoku"})

        mjai_events.append({"type": "end_kyoku"})

    return mjai_events


def events_to_mjai_json(events: Sequence[GameEvent]) -> List[str]:
    return [json.dumps(ev, ensure_ascii=False) for ev in events_to_mjai(events)]
