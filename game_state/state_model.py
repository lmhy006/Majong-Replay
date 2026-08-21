"""对局状态机 - 结构化状态模型（阶段三）。

定义全局对局状态、玩家状态、立直状态、副露与快照模型。
状态机逐事件更新 GameState，并在每个事件后生成 GameSnapshot。
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

# 副露类型约定（与协议/后续前端适配统一）：
#   0 = 吃
#   1 = 碰
#   2 = 大明杠
#   3 = 暗杠
#   4 = 加杠（由碰/大明杠升级而来）
#   5 = 拔北（三人麻将）
MELD_TYPE_CHI = 0
MELD_TYPE_PENG = 1
MELD_TYPE_MING_GANG = 2
MELD_TYPE_AN_GANG = 3
MELD_TYPE_ADD_GANG = 4
MELD_TYPE_BA_BEI = 5


class Meld(BaseModel):
    """一副副露（吃/碰/杠/拔北）。"""

    type: int = 0
    tiles: List[str] = Field(default_factory=list)
    # 每张牌来源座位；来自自己的牌为本人 seat
    froms: List[int] = Field(default_factory=list)


class LiqiState(BaseModel):
    """玩家立直状态（一等公民，用于局势判断与 AI 复盘）。"""

    declared: bool = False
    declared_step: int = 0          # 立直宣言发生在第几个事件
    tile: Optional[str] = None      # 立直时打出的牌
    is_wliqi: bool = False          # 是否双立直
    is_ippatsu: bool = False        # 是否一发（阶段三先留空，后续可推导）
    score_cost: int = 0             # 立直扣除点数（通常 1000）
    liqibang_after: int = 0         # 立直后场上立直棒数量
    failed: bool = False            # 立直是否失败（协议相关字段）
    liqi_type_beishuizhizhan: int = 0  # 背水立直类型（协议字段）


class PlayerState(BaseModel):
    """单个玩家当前局状态。"""

    seat: int
    hand: List[str] = Field(default_factory=list)
    discards: List[str] = Field(default_factory=list)
    melds: List[Meld] = Field(default_factory=list)
    liqi: Optional[LiqiState] = None
    score: int = 25000
    is_menqing: bool = True


class GameState(BaseModel):
    """当前局全局状态。"""

    uuid: str = ""
    chang: int = 0
    ju: int = 0
    ben: int = 0
    dealer_seat: int = 0
    scores: List[int] = Field(default_factory=lambda: [25000] * 4)
    liqibang: int = 0
    doras: List[str] = Field(default_factory=list)
    left_tile_count: int = 0
    players: List[PlayerState] = Field(
        default_factory=lambda: [PlayerState(seat=i) for i in range(4)]
    )
    round_status: str = "playing"   # playing | ended
    game_status: str = "playing"    # playing | ended
    # 内部开关：严格模式下手牌/牌河不一致直接抛错；非严格模式跳过并继续
    strict: bool = True


class GameSnapshot(BaseModel):
    """单个事件后的完整对局快照。"""

    step: int
    event_type: str
    event_summary: dict = Field(default_factory=dict)

    chang: int = 0
    ju: int = 0
    ben: int = 0
    dealer_seat: int = 0
    liqibang: int = 0
    scores: List[int] = Field(default_factory=lambda: [25000] * 4)
    doras: List[str] = Field(default_factory=list)
    left_tile_count: int = 0
    players: List[PlayerState] = Field(default_factory=list)
    round_status: str = "playing"
    game_status: str = "playing"
