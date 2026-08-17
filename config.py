"""应用配置模块（阶段一）。

使用 pydantic-settings 从环境变量 / .env 文件读取配置，
未设置时使用默认值（本地开发默认 127.0.0.1:8000）。

支持的环境变量（示例见 .env.example）：
    DSH_MAJONG_HOST / DSH_MAJONG_PORT  服务监听地址
    DSH_MAJONG_DEBUG                   调试模式
    DSH_MAJONG_STATIC_DIR              前端静态资源目录
    DSH_MAJONG_WEIGHTS_DIR             AI 权重目录（阶段五）
    DSH_MAJONG_MAJSOUL_HOST            雀魂服务器地址（阶段二）
    DSH_MAJONG_REQUEST_INTERVAL        牌谱请求间隔秒数（风控保护）
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录（本文件所在目录）
BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    """全局配置。字段名与 .env / 环境变量同名（大小写不敏感）。"""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- 服务 ----
    host: str = "127.0.0.1"
    port: int = 8000
    debug: bool = False

    # ---- 目录 ----
    static_dir: Path = BASE_DIR / "static"
    weights_dir: Path = BASE_DIR / "weights"
    majiang_ui_dir: Path = BASE_DIR / "static" / "majiang-ui"

    # ---- 牌谱拉取（阶段二使用） ----
    majsoul_host: str = "https://game.maj-soul.com"
    request_interval_seconds: float = 2.0  # 连续请求最小间隔，规避风控


@lru_cache
def get_settings() -> Settings:
    """获取全局配置单例。"""
    return Settings()
