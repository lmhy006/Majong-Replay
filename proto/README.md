# proto/ —— 雀魂协议文件（阶段一）

雀魂客户端使用 Protobuf 传输对局数据。本目录存放从社区维护的
`MahjongRepository/mahjong_soul_api`（基于雀魂官方 `liqi.json`）导出的
完整协议定义与编译产物，供阶段二（牌谱拉取与解码）直接使用。

## 文件清单

| 文件 | 说明 |
| --- | --- |
| `protocol.proto` | 雀魂完整协议定义（proto3，`package lq`，967 个消息） |
| `protocol_pb2.py` | 由 `protocol.proto` 编译生成的 Python 模块（可直接 import） |
| `liqi.json` | 雀魂官方协议原始描述（浏览器 Network 面板可抓取到的新版） |
| `generate_proto_file.py` | 由 `liqi.json` 生成 `protocol.proto` 的转换脚本 |

## 使用方法

```python
import sys
sys.path.insert(0, "proto")
import protocol_pb2 as pb

# 牌谱拉取相关消息（阶段二使用）
pb.ReqGameRecord      # 请求对局
pb.GameDetailRecords  # 对局内所有小局记录
pb.RecordNewRound     # 新对局（配牌）事件
pb.RecordDealTile     # 摸牌事件
pb.RecordDiscardTile  # 打牌事件
```

## 更新协议（雀魂版本升级时）

1. 从雀魂官网（浏览器 Network 面板）获取最新 `liqi.json`，覆盖本文件；
2. 运行 `python generate_proto_file.py` 重新生成 `protocol.proto`；
3. 使用 protoc（或 `grpcio-tools` 的 `python -m grpc_tools.protoc`）
   编译生成新的 `protocol_pb2.py`：
   ```sh
   python -m grpc_tools.protoc -I. --python_out=. protocol.proto
   ```

## 来源

* 协议仓库：<https://github.com/MahjongRepository/mahjong_soul_api>
  （MIT，基于雀魂官方 `liqi.json` 生成）
* 原始协议：雀魂游戏客户端 `liqi.json`（官方资源）
