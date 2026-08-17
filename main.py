"""雀魂牌谱本地复盘系统 - FastAPI 入口（阶段一骨架）。

当前提供：
    * GET  /                   基础页面（static/index.html）
    * GET  /static/*           前端静态资源（majiang-ui 等）
    * POST /api/v1/paipu/parse 牌谱链接解析（调用 url_parser）

后续阶段将在此追加：
    * 牌谱拉取 / 解码接口（阶段二）
    * 对局仿真 / 快照接口（阶段三）
    * AI 复盘接口（阶段五、六）

启动：uvicorn main:app --reload
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config import get_settings
from url_parser import PaipuUrlError, parse_paipu_url

settings = get_settings()

app = FastAPI(
    title="雀魂牌谱本地复盘系统",
    description="本地牌谱解析 + majiang-ui 回放 + Mortal AI 复盘",
    version="0.1.0",
)


# ---------------------------------------------------------------------------
# API 模型
# ---------------------------------------------------------------------------


class PaipuParseRequest(BaseModel):
    url: str = Field(..., min_length=1, description="雀魂牌谱链接")


class PaipuParseResponse(BaseModel):
    paipu: str                   # paipu 参数完整值
    uuid: str                    # 对局唯一 ID
    match_id: str | None         # 主视角账号 ID（可选）
    anonymous: bool              # 是否匿名牌谱
    date: str | None             # 对局日期（普通牌谱，YYYY-MM-DD）
    url: str                     # 规范化后的链接


# ---------------------------------------------------------------------------
# API 路由
# ---------------------------------------------------------------------------


@app.post("/api/v1/paipu/parse", response_model=PaipuParseResponse)
def parse_paipu(req: PaipuParseRequest):
    """解析雀魂牌谱链接，返回对局唯一 ID 与元信息。"""
    try:
        info = parse_paipu_url(req.url)
    except PaipuUrlError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    return PaipuParseResponse(
        paipu=info.paipu,
        uuid=info.uuid,
        match_id=info.match_id,
        anonymous=info.anonymous,
        date=info.date.isoformat() if info.date else None,
        url=info.url,
    )


@app.get("/")
def index():
    """基础页面。"""
    return FileResponse(settings.static_dir / "index.html")


# 静态资源（majiang-ui、图片、音频等）
app.mount(
    "/static",
    StaticFiles(directory=settings.static_dir),
    name="static",
)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
