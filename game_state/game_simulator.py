"""对局状态机 - 事件推演核心（阶段三）。

采用“事件驱动 reducer”模式：

    state = GameState()
    for event in events:
        apply_event(state, event)
        snapshots.append(make_snapshot(state, event))

事件流是确定性的，状态机只负责按顺序重放并还原完整对局状态。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from proto.decoder import GameEvent

from .state_model import (
    MELD_TYPE_ADD_GANG,
    MELD_TYPE_AN_GANG,
    MELD_TYPE_BA_BEI,
    MELD_TYPE_MING_GANG,
    GameSnapshot,
    GameState,
    LiqiState,
    Meld,
    PlayerState,
)


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

#舍牌
def _remove_one_from_hand(player: PlayerState, tile: str, strict: bool = True) -> None:
    """从手牌中移除一张指定牌；找不到时按 strict 决定抛错或忽略。"""
    try:
        player.hand.remove(tile)
    except ValueError:
        if strict:
            raise ValueError(
                f"座位{player.seat} 手牌中找不到 {tile!r}，当前手牌={player.hand}"
            )

#鸣牌
def _remove_last_discard(player: PlayerState, tile: str, strict: bool = True) -> None:
    """从牌河中移除最近打出的一张指定牌"""
    for i in range(len(player.discards) - 1, -1, -1):
        if player.discards[i] == tile:
            player.discards.pop(i)
            return
    if strict:
        raise ValueError(
            f"座位{player.seat} 牌河中找不到 {tile!r}，当前牌河={player.discards}"
        )


def _player_of(event: GameEvent, state: GameState) -> PlayerState:
    seat = event.seat
    if seat is None:
        seat = event.data.get("seat")
    if seat is None or not 0 <= int(seat) < 4:
        raise ValueError(f"事件 {event.step} ({event.type}) 缺少有效 seat: {event!r}")
    return state.players[int(seat)]


# ---------------------------------------------------------------------------
# 事件处理
# ---------------------------------------------------------------------------


def _apply_new_round(state: GameState, event: GameEvent) -> None:
    data = event.data
    tiles = [list(data.get(f"tiles{i}", []) or []) for i in range(4)]
    scores = list(data.get("scores") or [25000] * 4)

    # 庄家判定：优先“起手 14 张的座位”，找不到时用场/局推导兜底
    dealer = None
    for i, t in enumerate(tiles):
        if len(t) == 14:
            dealer = i
            break
    if dealer is None:
        dealer = (int(data.get("chang", 0) or 0) * 4 + int(data.get("ju", 0) or 0)) % 4
    state.dealer_seat = dealer

    state.chang = int(data.get("chang", 0) or 0)
    state.ju = int(data.get("ju", 0) or 0)
    state.ben = int(data.get("ben", 0) or 0)
    state.scores = scores
    state.liqibang = int(data.get("liqibang", 0) or 0)
    state.doras = list(data.get("doras") or ([data["dora"]] if data.get("dora") else []))
    state.left_tile_count = int(data.get("left_tile_count", 0) or 0)
    state.players = [
        PlayerState(seat=i, hand=list(tiles[i]), score=scores[i] if i < len(scores) else 25000)
        for i in range(4)
    ]
    state.round_status = "playing"
    state.liu_ju_type = 0
    state.liu_ju_manguan = False
    # 整场状态不在这里重置：只有 hu/liu_ju 带 gameend 时才结束整场


def _mark_liqi_declared(
    state: GameState,
    player: PlayerState,
    event: GameEvent,
    tile: Optional[str] = None,
    is_wliqi: bool = False,
    liqi_type: int = 0,
) -> None:
    """执行立直宣言：确保扣 1000 点并增加 1 根立直棒（只扣一次）。

    真实牌谱中立直确认可能出现在 deal_tile.liqi，也可能只由
    discard_tile.is_liqi 标记；本函数作为统一入口，无论哪个事件先到，
    都能正确扣分/加棒且不重复。
    """
    if player.liqi is None:
        player.liqi = LiqiState(
            declared=True,
            declared_step=event.step,
            tile=tile,
            is_wliqi=is_wliqi,
            score_cost=1000,
            liqibang_after=state.liqibang + 1,
            failed=False,
            liqi_type_beishuizhizhan=liqi_type,
        )
        state.liqibang += 1
        player.score -= 1000
        return

    # 已有立直状态：若尚未扣分则补扣
    if player.liqi.score_cost == 0:
        player.liqi.score_cost = 1000
        state.liqibang += 1
        player.score -= 1000

    # 补全/覆盖宣言信息（declared_step 最终以 discard_tile 宣言步为准）
    player.liqi.declared = True
    player.liqi.declared_step = event.step
    if tile is not None:
        player.liqi.tile = tile
    player.liqi.is_wliqi = is_wliqi
    if liqi_type:
        player.liqi.liqi_type_beishuizhizhan = liqi_type
    player.liqi.liqibang_after = state.liqibang


def _apply_deal_tile(state: GameState, event: GameEvent) -> None:
    data = event.data
    player = _player_of(event, state)
    tile = data.get("tile")
    if not tile:
        raise ValueError(f"事件 {event.step} deal_tile 缺少 tile: {event!r}")
    player.hand.append(tile)
    if "left_tile_count" in data:
        state.left_tile_count = int(data.get("left_tile_count", 0) or 0)

    # 协议中 deal_tile 可能携带 LiQiSuccess，用于立直成功/失败确认
    liqi_data = data.get("liqi")
    if liqi_data:
        failed = bool(liqi_data.get("failed", False))
        if player.liqi is None:
            player.liqi = LiqiState(
                declared=not failed,
                declared_step=event.step,
                failed=failed,
            )
        else:
            player.liqi.failed = failed

        if not failed:
            # 立直确认成功：统一走扣分/加棒逻辑（若尚未扣）
            _mark_liqi_declared(state, player, event)
            # 协议若给出立直棒总数，以协议值为准
            if "liqibang" in liqi_data:
                state.liqibang = int(liqi_data.get("liqibang", 0) or 0)
                player.liqi.liqibang_after = state.liqibang


def _apply_discard_tile(state: GameState, event: GameEvent) -> None:
    data = event.data
    player = _player_of(event, state)
    tile = data.get("tile")
    if not tile:
        raise ValueError(f"事件 {event.step} discard_tile 缺少 tile: {event!r}")

    _remove_one_from_hand(player, tile, state.strict)
    player.discards.append(tile)

    # 立直宣言：discard_tile.is_liqi = true
    if data.get("is_liqi"):
        _mark_liqi_declared(
            state,
            player,
            event,
            tile=tile,
            is_wliqi=bool(data.get("is_wliqi", False)),
            liqi_type=int(data.get("liqi_type_beishuizhizhan", 0) or 0),
        )


def _apply_chi_peng_gang(state: GameState, event: GameEvent) -> None:
    data = event.data
    player = _player_of(event, state)
    tiles = list(data.get("tiles", []) or [])
    froms = list(data.get("froms", []) or [])
    if not tiles:
        raise ValueError(f"事件 {event.step} chi_peng_gang 缺少 tiles: {event!r}")
    if not froms:
        # 旧/异常数据没有 froms 时，保守按全部来自自己处理
        froms = [player.seat] * len(tiles)
    if len(froms) != len(tiles):
        raise ValueError(
            f"事件 {event.step} chi_peng_gang tiles/froms 长度不一致: {event!r}"
        )

    for tile, from_seat in zip(tiles, froms):
        from_seat = int(from_seat)
        if from_seat == player.seat:
            _remove_one_from_hand(player, tile, state.strict)
        else:
            _remove_last_discard(state.players[from_seat], tile, state.strict)

    player.melds.append(
        Meld(type=int(data.get("type", 0) or 0), tiles=tiles, froms=froms)
    )
    # 吃/碰/大明杠都是公开副露，破坏门清
    player.is_menqing = False


def _apply_an_gang_add_gang(state: GameState, event: GameEvent) -> None:
    data = event.data
    player = _player_of(event, state)
    tile = data.get("tiles")
    if not tile:
        raise ValueError(f"事件 {event.step} an_gang_add_gang 缺少 tiles: {event!r}")
    typ = int(data.get("type", 0) or 0)

    # 注意：RecordAnGangAddGang.type 的协议语义与内部 Meld.type 不同。
    #   协议 type = 3 -> 暗杠，内部 Meld.type = 3
    #   协议 type = 2 -> 加杠，内部 Meld.type = 4 (MELD_TYPE_ADD_GANG)
    if typ == 3:  # 协议暗杠
        for _ in range(4):
            _remove_one_from_hand(player, tile, state.strict)
        player.melds.append(
            Meld(type=MELD_TYPE_AN_GANG, tiles=[tile] * 4, froms=[player.seat] * 4)
        )
        # 暗杠不破坏门清
    elif typ == 2:  # 协议加杠
        _remove_one_from_hand(player, tile, state.strict)
        target = None
        for meld in player.melds:
            if meld.tiles and meld.tiles[0] == tile and meld.type in (
                MELD_TYPE_MING_GANG,
                1,  # 碰
                4,  # 已是加杠
            ):
                target = meld
                break
        if target is None:
            target = Meld(type=MELD_TYPE_ADD_GANG, tiles=[], froms=[])
            player.melds.append(target)
        target.tiles.append(tile)
        target.froms.append(player.seat)
        target.type = MELD_TYPE_ADD_GANG
        # 加杠通常基于已公开的碰/杠，门清状态已在之前被破坏；这里不再额外处理
    else:
        # 未知 type：先记录到快照，不修改手牌，避免误伤
        # TODO: 确认其他 type 语义（可能是特殊规则）
        pass


def _apply_ba_bei(state: GameState, event: GameEvent) -> None:
    data = event.data
    player = _player_of(event, state)
    # 三人麻将拔北：从手牌移除一张北（4z）并记录为副露
    # 协议未显式给出拔的牌，默认按 4z；如后续发现其他表示再调整
    tile = "4z"
    if tile in player.hand:
        _remove_one_from_hand(player, tile, state.strict)
        player.melds.append(
            Meld(type=MELD_TYPE_BA_BEI, tiles=[tile], froms=[player.seat])
        )


def _apply_hu(state: GameState, event: GameEvent) -> None:
    data = event.data
    state.round_status = "ended"

    # 点数更新：优先用最终 scores，其次 old_scores + delta_scores
    scores = data.get("scores")
    old_scores = data.get("old_scores")
    delta_scores = data.get("delta_scores")
    if scores and len(scores) == 4:
        state.scores = [int(x) for x in scores]
    elif old_scores and delta_scores and len(old_scores) == 4 and len(delta_scores) == 4:
        state.scores = [int(old_scores[i]) + int(delta_scores[i]) for i in range(4)]

    # 整场结束标记（RecordHule.gameend 为 GameEnd 消息，存在即结束）
    if data.get("gameend"):
        state.game_status = "ended"


def _apply_liu_ju(state: GameState, event: GameEvent) -> None:
    data = event.data
    state.round_status = "ended"

    # 记录特殊流局类型：
    #   liu_ju.type 区分九种九牌/四风连打/四家立直/四杠散了等（原始协议值）
    #   no_tile.liujumanguan 表示流局满贯
    if event.type == "liu_ju":
        state.liu_ju_type = int(data.get("type", 0) or 0)
        state.liu_ju_manguan = False
    elif event.type == "no_tile":
        state.liu_ju_type = 0
        state.liu_ju_manguan = bool(data.get("liujumanguan", False))

    # 点数更新：RecordNoTile.scores[] / RecordLiuJu 相关字段
    scores_info = data.get("scores")
    if scores_info:
        for info in scores_info:
            old_scores = info.get("old_scores")
            delta_scores = info.get("delta_scores")
            if old_scores and delta_scores and len(old_scores) == 4 and len(delta_scores) == 4:
                state.scores = [int(old_scores[i]) + int(delta_scores[i]) for i in range(4)]
                break
            if delta_scores and len(delta_scores) == 4:
                for i in range(4):
                    state.scores[i] += int(delta_scores[i])

    if data.get("gameend"):
        state.game_status = "ended"


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

_EVENT_HANDLERS = {
    "new_round": _apply_new_round,
    "deal_tile": _apply_deal_tile,
    "discard_tile": _apply_discard_tile,
    "chi_peng_gang": _apply_chi_peng_gang,
    "an_gang_add_gang": _apply_an_gang_add_gang,
    "ba_bei": _apply_ba_bei,
    "hu": _apply_hu,
    "hu_xuezhan_mid": _apply_hu,
    "hu_xuezhan_end": _apply_hu,
    "liu_ju": _apply_liu_ju,
    "no_tile": _apply_liu_ju,
    # 以下特殊事件阶段三先透传，不改变状态：
    # "select_gap", "change_tile", "reveal_tile", "unveil_tile",
    # "lock_tile", "fill_awaiting_tiles", "gang_result", "gang_result_end"
}


def apply_event(state: GameState, event: GameEvent) -> None:
    """将单个事件应用到当前状态（原地更新）。"""
    handler = _EVENT_HANDLERS.get(event.type)
    if handler is not None:
        handler(state, event)


def make_snapshot(state: GameState, event: GameEvent) -> GameSnapshot:
    """基于当前状态生成该事件后的完整快照。"""
    return GameSnapshot(
        step=event.step,
        event_type=event.type,
        event_summary=dict(event.data),
        chang=state.chang,
        ju=state.ju,
        ben=state.ben,
        dealer_seat=state.dealer_seat,
        liqibang=state.liqibang,
        scores=list(state.scores),
        doras=list(state.doras),
        left_tile_count=state.left_tile_count,
        players=[p.model_copy(deep=True) for p in state.players],
        round_status=state.round_status,
        game_status=state.game_status,
        liu_ju_type=state.liu_ju_type,
        liu_ju_manguan=state.liu_ju_manguan,
    )


def simulate(
    events: Sequence[GameEvent],
    head: Optional[Dict] = None,
    strict: bool = True,
) -> List[GameSnapshot]:
    """重放完整事件流，返回每个事件后的快照列表。

    strict=True 时，手牌/牌河不一致会抛出异常，便于发现状态机 bug；
    strict=False 时跳过不一致，尽量继续重放（适合演示/容错）。
    """
    state = GameState(strict=strict)
    if head:
        state.uuid = str(head.get("uuid", "") or "")
    snapshots: List[GameSnapshot] = []
    for event in events:
        apply_event(state, event)
        snapshots.append(make_snapshot(state, event))
    return snapshots


def simulate_from_dicts(
    events: Sequence[Dict],
    head: Optional[Dict] = None,
    strict: bool = True,
) -> List[GameSnapshot]:
    """从 API/JSON 风格的事件字典列表重放事件流。"""
    game_events = [
        GameEvent(
            step=int(e.get("step", i + 1)),
            type=str(e.get("type", "")),
            full_name=str(e.get("full_name", "")),
            seat=e.get("seat"),
            data=dict(e.get("data", {}) or {}),
        )
        for i, e in enumerate(events)
    ]
    return simulate(game_events, head=head, strict=strict)
