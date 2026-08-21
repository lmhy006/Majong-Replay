#!/usr/bin/env python3
"""批量拉取真实牌谱 -> 解码 -> 状态机生成快照 -> 保存缓存（阶段三回归用）。

用法：
    python .dev/batch_fetch_audit.py <url1> <url2> ...

注意：
    * 需要调试浏览器已启动且 CDP 9222 可访问；
    * 默认不自动关闭浏览器，方便连续拉取多张；
    * 拉取成功后快照会保存到 data/game_records/<uuid>.json。
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "proto"))

from config import get_settings  # noqa: E402
from proto.decoder import decode_paipu  # noqa: E402
from token_helper import capture_game_record  # noqa: E402
from url_parser import PaipuUrlError, parse_paipu_url  # noqa: E402
from game_state.game_simulator import simulate  # noqa: E402
from game_state.snapshot import save_snapshots  # noqa: E402

settings = get_settings()
CDP_PORT = 9222


async def process_one(url: str) -> dict:
    info = parse_paipu_url(url)
    browser_url = url.strip()
    if not browser_url.startswith(("http://", "https://")):
        browser_url = f"{settings.majsoul_host}/1/?paipu={info.paipu}"

    print(f"开始拉取: {info.uuid}", flush=True)
    data = await capture_game_record(browser_url, port=CDP_PORT)
    result = decode_paipu(data)
    snapshots = simulate(result.events, head={"uuid": info.uuid})
    save_snapshots(info.uuid, snapshots, settings.record_cache_dir)
    print(
        f"完成: {info.uuid}  events={len(result.events)} snapshots={len(snapshots)}",
        flush=True,
    )
    return {
        "uuid": info.uuid,
        "event_count": len(result.events),
        "snapshot_count": len(snapshots),
    }


async def main() -> None:
    urls = sys.argv[1:]
    if not urls:
        print("用法: python .dev/batch_fetch_audit.py <url1> <url2> ...")
        return

    results = []
    for url in urls:
        try:
            results.append(await process_one(url))
        except PaipuUrlError as exc:
            print(f"链接解析失败: {url} -> {exc}", flush=True)
        except Exception as exc:
            print(f"拉取失败: {url} -> {type(exc).__name__}: {exc}", flush=True)

    print("\n===== 批量结果 =====", flush=True)
    for r in results:
        print(f"  {r['uuid']}: events={r['event_count']}, snapshots={r['snapshot_count']}", flush=True)
    print(f"成功 {len(results)}/{len(urls)}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
