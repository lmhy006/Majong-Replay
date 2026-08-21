"""对局快照生成与 JSON 持久化（阶段三）。

将状态机输出的 GameSnapshot 列表序列化为 JSON 缓存到 data/game_records/。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from config import BASE_DIR

from .state_model import GameSnapshot


def _default_cache_dir() -> Path:
    return BASE_DIR / "data" / "game_records"


def snapshots_to_dict(snapshots: List[GameSnapshot]) -> dict:
    """快照列表 -> 可 JSON 序列化 dict。"""
    return {
        "snapshot_count": len(snapshots),
        "snapshots": [s.model_dump(mode="json") for s in snapshots],
    }


def save_snapshots(
    uuid: str,
    snapshots: List[GameSnapshot],
    directory: Optional[Path | str] = None,
) -> Path:
    """保存快照到 JSON 文件，返回文件路径。"""
    cache_dir = Path(directory) if directory else _default_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{uuid}.json"
    payload = {
        "uuid": uuid,
        **snapshots_to_dict(snapshots),
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def load_snapshots(
    uuid: str,
    directory: Optional[Path | str] = None,
) -> List[GameSnapshot]:
    """从 JSON 文件读取快照列表。"""
    cache_dir = Path(directory) if directory else _default_cache_dir()
    path = cache_dir / f"{uuid}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return [GameSnapshot.model_validate(item) for item in data.get("snapshots", [])]
