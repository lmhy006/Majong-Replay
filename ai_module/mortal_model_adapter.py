"""社区 Mortal 权重加载与适配（阶段五）。

支持加载 Mortal v4 权重（mortal_298k.pth），并在 libriichi 扩展可用时
构建官方 MortalEngine；libriichi 不可用时仍可加载权重/解析配置。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional

import torch

MORTAL_REPO = Path(__file__).resolve().parent.parent / "Mortal"
MORTAL_PY_DIR = MORTAL_REPO / "mortal"


class MortalModelError(RuntimeError):
    pass


class MortalModelAdapter:
    """加载社区 Mortal 权重，并适配本地推理设备。"""

    def __init__(
        self,
        weight_path: str | Path,
        device: str = "auto",
    ):
        self.weight_path = Path(weight_path)
        self.device = self._resolve_device(device)
        self._state_dict: Optional[Dict[str, Any]] = None
        self._loaded = False
        self.config: Optional[Dict[str, Any]] = None
        self.version: Optional[int] = None
        self._engine = None
        self._engine_error: Optional[str] = None

    @staticmethod
    def _resolve_device(device: str) -> str:
        if device == "auto":
            return "cuda" if torch.cuda.is_available() else "cpu"
        return device

    def load(self) -> "MortalModelAdapter":
        """加载权重文件，并尝试构建 MortalEngine。"""
        if not self.weight_path.exists():
            raise MortalModelError(
                f"权重文件不存在: {self.weight_path}，请将社区轻量化 Mortal 权重放到 weights/ 目录"
            )
        try:
            self._state_dict = torch.load(
                self.weight_path,
                map_location=self.device,
                weights_only=False,
            )
        except Exception as exc:
            raise MortalModelError(f"权重加载失败: {exc}") from exc

        self._loaded = True
        self.config = self._state_dict.get("config")
        if self.config:
            self.version = int(self.config.get("control", {}).get("version", 4))

        self._build_engine()
        return self

    def _build_engine(self) -> None:
        """在 libriichi 可用时构建官方 MortalEngine。"""
        self._engine = None
        self._engine_error = None

        # 先确保 Mortal/mortal 在 sys.path：libriichi.pyd 与 model/engine 都位于该目录
        sys.path.insert(0, str(MORTAL_PY_DIR))
        try:
            import libriichi  # noqa: F401
        except ImportError as exc:
            self._engine_error = (
                f"libriichi 扩展未安装: {exc}。请先在 Mortal/libriichi 编译 Python 扩展"
            )
            return

        try:
            from model import Brain, DQN
            from engine import MortalEngine

            cfg = self.config or {}
            control = cfg.get("control", {})
            version = int(control.get("version", 4))
            resnet = cfg.get("resnet", {})
            conv_channels = int(resnet.get("conv_channels", 192))
            num_blocks = int(resnet.get("num_blocks", 40))

            brain = Brain(
                version=version,
                conv_channels=conv_channels,
                num_blocks=num_blocks,
            ).eval()
            dqn = DQN(version=version).eval()
            brain.load_state_dict(self._state_dict["mortal"])
            dqn.load_state_dict(self._state_dict["current_dqn"])

            self._engine = MortalEngine(
                brain,
                dqn,
                is_oracle=False,
                version=version,
                device=torch.device(self.device),
                enable_amp=False,
            )
        except Exception as exc:
            self._engine_error = f"构建 Mortal 引擎失败: {exc}"

    @property
    def loaded(self) -> bool:
        return self._loaded

    @property
    def state_dict(self) -> Dict[str, Any]:
        if not self._loaded:
            raise MortalModelError("模型尚未加载，请先调用 load()")
        return self._state_dict

    @property
    def engine(self):
        if self._engine is None:
            raise MortalModelError(self._engine_error or "Mortal 引擎不可用")
        return self._engine

    def unload(self) -> None:
        self._state_dict = None
        self._loaded = False
        self.config = None
        self.version = None
        self._engine = None
        self._engine_error = None
