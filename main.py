"""雀魂牌谱本地复盘系统 - FastAPI 入口。

当前提供：
    * GET  /                          基础页面（static/index.html）
    * GET  /static/*                  前端静态资源（majiang-ui 等）
    * POST /api/v1/paipu/parse        牌谱链接解析
    * POST /api/v1/paipu/browser-fetch 浏览器拉取并解码（主路径）
    * GET  /api/v1/paipu/demo         内置示例解码（无需登录）
    * POST /api/v1/paipu/simulate     事件流状态机重放（返回快照）
    * GET  /api/v1/paipu/{uuid}/replay 返回 majiang-ui 回放数据

说明：雀魂阻止程序化登录（151），主路径为通过调试浏览器打开牌谱并
捕获响应帧；底层协议层保留在 majsoul_ws.py / token_helper.py。

启动：uvicorn main:app --reload
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config import get_settings
from url_parser import PaipuUrlError, parse_paipu_url

logger = logging.getLogger(__name__)

settings = get_settings()

app = FastAPI(
    title="雀魂牌谱本地复盘系统",
    description="本地牌谱解析 + majiang-ui 回放 + Mortal AI 复盘",
    version="0.2.0",
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


class PaipuFetchRequest(BaseModel):
    url: str = Field(..., min_length=1, description="雀魂牌谱链接")


class PaipuFetchResponse(BaseModel):
    uuid: str                    # 对局唯一 ID
    version: int                 # 牌谱数据版本
    events: list                 # 解码后的对局事件列表
    event_count: int             # 事件总数
    snapshots: list = []         # 阶段三：每个事件后的完整对局快照列表


class PaipuSimulateRequest(BaseModel):
    events: list = Field(..., min_length=1, description="解码后的对局事件列表")
    head: dict | None = Field(default=None, description="可选的对局头信息（uuid 等）")


class PaipuSimulateResponse(BaseModel):
    uuid: str = ""
    event_count: int
    snapshot_count: int
    snapshots: list


class PaipuReplayResponse(BaseModel):
    uuid: str
    paipu: dict                  # majiang-ui 可直接消费的回放数据


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


@app.post("/api/v1/paipu/browser-fetch", response_model=PaipuFetchResponse)
async def browser_fetch_paipu(req: PaipuFetchRequest):
    """通过调试浏览器拉取并解码牌谱（无需 token，只要浏览器已登录雀魂）。

    浏览器打开牌谱链接时由雀魂页面自动拉取，我们捕获响应帧。
    """
    from proto.decoder import decode_paipu
    from token_helper import CaptureRecordError, capture_game_record, close_browser

    try:
        info = parse_paipu_url(req.url)
    except PaipuUrlError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    # 构造浏览器可导航的标准雀魂牌谱 URL：
    # 完整链接直接用；残缺链接（paipu=xxx）补成标准格式
    raw_url = req.url.strip()
    if raw_url.startswith(("http://", "https://")):
        browser_url = raw_url
    else:
        browser_url = f"{settings.majsoul_host}/1/?paipu={info.paipu}"

    try:
        data = await capture_game_record(browser_url, port=9222)
        result = decode_paipu(data)
        from game_state.game_simulator import simulate
        from game_state.snapshot import save_snapshots

        snapshots = simulate(result.events, head={"uuid": info.uuid})
        try:
            save_snapshots(info.uuid, snapshots, settings.record_cache_dir)
        except Exception as exc:
            logger.warning("保存快照缓存失败（不影响本次结果）: %s", exc)
    except CaptureRecordError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    except Exception as exc:
        logger.warning("browser-fetch 失败: %s", exc)
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    # 拉取成功后自动关闭调试浏览器
    try:
        await close_browser(port=9222)
    except Exception as exc:
        logger.warning("自动关闭浏览器失败（不影响结果）: %s", exc)

    logger.info("browser-fetch 成功: %s，%d 个事件（浏览器已自动关闭）", info.uuid, len(result.events))
    return PaipuFetchResponse(
        uuid=info.uuid,
        version=result.version,
        events=[e.to_dict() for e in result.events],
        event_count=len(result.events),
        snapshots=[s.model_dump(mode="json") for s in snapshots],
    )


@app.get("/api/v1/paipu/demo")
def demo_paipu():
    """演示接口（无需 token / 无需网络）。

    优先返回本地缓存中一份真实牌谱（数据自洽，可直接体验完整回放）；
    本地无缓存时回退到内置 fixture（仅验证解码链路，配牌与鸣牌可能不自洽）。
    """
    import base64
    import json
    import sys
    from pathlib import Path

    from proto.decoder import decode_paipu

    # 优先：返回本地缓存的一份真实牌谱，保证回放数据自洽
    cache_dir = settings.record_cache_dir
    real_records = sorted(
        (p for p in cache_dir.glob("*.json") if p.stem != "sample"),
        key=lambda p: p.name,
    )
    if real_records:
        path = real_records[0]
        data = json.loads(path.read_text(encoding="utf-8"))
        uuid = data.get("uuid") or path.stem
        events = [
            {
                "step": s["step"],
                "type": s["event_type"],
                "full_name": "",
                "seat": s["event_summary"].get("seat"),
                "data": dict(s["event_summary"]),
            }
            for s in data.get("snapshots", [])
        ]
        return PaipuFetchResponse(
            uuid=uuid,
            version=0,
            events=events,
            event_count=len(events),
            snapshots=data.get("snapshots", []),
        )

    # 回退：解码内置 fixture（人工构造的解码样例）
    sys.path.insert(0, str(Path(__file__).resolve().parent / "proto"))
    import protocol_pb2 as pb

    fixture = (
        Path(__file__).resolve().parent
        / "tests" / "fixtures" / "sample.res.b64"
    )
    if not fixture.exists():
        return JSONResponse(status_code=404, content={"detail": "演示数据缺失"})
    raw = base64.b64decode(fixture.read_bytes())
    res = pb.ResGameRecord()
    res.ParseFromString(raw)
    result = decode_paipu(res.data)
    from game_state.game_simulator import simulate
    from game_state.snapshot import save_snapshots

    uuid = res.head.uuid or "sample"
    snapshots = simulate(result.events, head={"uuid": uuid}, strict=False)
    try:
        save_snapshots(uuid, snapshots, settings.record_cache_dir)
    except Exception as exc:
        logger.warning("保存演示快照缓存失败（不影响本次结果）: %s", exc)
    return PaipuFetchResponse(
        uuid=uuid,
        version=result.version,
        events=[e.to_dict() for e in result.events],
        event_count=len(result.events),
        snapshots=[s.model_dump(mode="json") for s in snapshots],
    )


@app.post("/api/v1/paipu/simulate", response_model=PaipuSimulateResponse)
def simulate_paipu(req: PaipuSimulateRequest):
    """直接对已解码事件流做状态机重放，返回逐事件完整快照。"""
    from game_state.game_simulator import simulate_from_dicts

    try:
        snapshots = simulate_from_dicts(req.events, head=req.head)
    except Exception as exc:
        logger.warning("simulate 失败: %s", exc)
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    uuid = (req.head or {}).get("uuid", "")
    return PaipuSimulateResponse(
        uuid=uuid,
        event_count=len(req.events),
        snapshot_count=len(snapshots),
        snapshots=[s.model_dump(mode="json") for s in snapshots],
    )


@app.get("/api/v1/paipu/{uuid}/replay", response_model=PaipuReplayResponse)
def replay_paipu(uuid: str):
    """从快照缓存生成 majiang-ui 回放数据（阶段四）。"""
    from proto.decoder import GameEvent
    from replay.adapter import events_to_paipu
    from game_state.snapshot import load_snapshots

    try:
        snapshots = load_snapshots(uuid, settings.record_cache_dir)
    except Exception:
        return JSONResponse(
            status_code=404,
            content={"detail": f"快照缓存不存在: {uuid}，请先通过 browser-fetch 拉取"},
        )

    events = [
        GameEvent(
            step=s.step,
            type=s.event_type,
            full_name="",
            seat=s.event_summary.get("seat"),
            data=dict(s.event_summary),
        )
        for s in snapshots
    ]
    try:
        paipu = events_to_paipu(events, head={"uuid": uuid, "title": uuid}, strict=False)
    except Exception as exc:
        logger.warning("生成回放数据失败: %s", exc)
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    return PaipuReplayResponse(uuid=uuid, paipu=paipu)


@app.get("/api/v1/paipu/{uuid}/ai")
def ai_analyze_paipu(uuid: str):
    """对已拉取的牌谱运行 Mortal AI 推理，返回逐决策点推荐（阶段五）。"""
    from proto.decoder import GameEvent
    from game_state.snapshot import load_snapshots
    from ai_module.mortal_model_adapter import MortalModelAdapter
    from ai_module.replay_analyzer import ReplayAnalyzer

    try:
        snapshots = load_snapshots(uuid, settings.record_cache_dir)
    except Exception:
        return JSONResponse(
            status_code=404,
            content={"detail": f"快照缓存不存在: {uuid}，请先通过 browser-fetch 拉取"},
        )

    events = [
        GameEvent(
            step=s.step,
            type=s.event_type,
            full_name="",
            seat=s.event_summary.get("seat"),
            data=dict(s.event_summary),
        )
        for s in snapshots
    ]

    weight_path = settings.weights_dir / "mortal_298k.pth"
    try:
        adapter = MortalModelAdapter(weight_path, device="cpu").load()
        analyzer = ReplayAnalyzer(adapter, player_id=0)
        result = analyzer.analyze_replay(events, seat=0)
    except Exception as exc:
        logger.warning("AI 推理失败: %s", exc)
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    return result


# ---------------------------------------------------------------------------
# 浏览器辅助（启动调试浏览器；token/直连已移除，主路径为浏览器拉取）
# ---------------------------------------------------------------------------


class LaunchBrowserResponse(BaseModel):
    launched: bool
    browser: str | None
    port: int
    profile_dir: str


@app.post("/api/v1/browser/launch", response_model=LaunchBrowserResponse)
async def launch_browser():
    """以调试模式启动 Edge/Chrome（独立 profile，供浏览器拉取使用）。"""
    import token_helper

    try:
        browser = await asyncio.to_thread(
            token_helper.launch_browser,
            token_helper.DEFAULT_CDP_PORT,
            None,
            token_helper.MAJSOUL_URL,
        )
    except token_helper.TokenImportError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    profile_dir = str(Path(__file__).resolve().parent / ".browser-profile")
    return LaunchBrowserResponse(
        launched=True,
        browser=browser,
        port=token_helper.DEFAULT_CDP_PORT,
        profile_dir=profile_dir,
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
