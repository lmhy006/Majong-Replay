# 雀魂牌谱本地复盘系统

完全本地运行、自主可控的雀魂牌谱 **解析 + 回放 + AI 复盘** 系统。

* 输入雀魂牌谱链接 → 自动拉取 → Protobuf 解码 → 状态机仿真 → majiang-ui 可视化回放
* AI 阶段接入社区开源轻量化 Mortal 权重（仅推理，不训练）

## 当前进度

### 阶段一（基础环境搭建）✅

| 子任务 | 状态 | 说明 |
| --- | --- | --- |
| 项目目录 + requirements.txt + 依赖安装 | ✅ | Python 3.12，依赖见 `requirements.txt` |
| 编译 Protobuf 协议文件 | ✅ | `proto/`（protocol.proto + protocol_pb2.py + liqi.json） |
| URL 解析模块 + 单元测试 | ✅ | `url_parser.py`（26 个用例） |
| majiang-ui 资源 + 基础页面 | ✅ | `static/majiang-ui/`（JS/CSS 本地打包）+ `static/index.html` |

### 阶段二（牌谱拉取与解码）✅

| 子任务 | 状态 | 说明 |
| --- | --- | --- |
| WebSocket 协议层 | ✅ | `majsoul_ws.py`：服务器发现、帧协议、RPC、fetchGameRecord（保留作底层能力） |
| 浏览器捕获拉取（主路径） | ✅ | `token_helper.py`：CDP 打开牌谱 → 截获 fetchGameRecord 响应 → 自动关闭浏览器 |
| 二进制数据解码 → 标准事件列表 | ✅ | `proto/decoder.py`：22 类事件，真实数据验证 |
| 协议兼容与错误处理 | ✅ | 新旧协议版本兼容、151/1004 等错误码映射、频率限制 |
| 单元测试 | ✅ | 66 个用例全通过（含真实牌谱 fixture） |

### 阶段三（对局状态机）✅

| 子任务 | 状态 | 说明 |
| --- | --- | --- |
| 状态模型 | ✅ | `game_state/state_model.py`：全局/玩家/立直/副露/快照模型 |
| 事件推演 | ✅ | `game_state/game_simulator.py`：逐事件还原手牌、牌河、副露、点数、立直、多局切换 |
| 快照生成与缓存 | ✅ | `game_state/snapshot.py`：每事件完整快照 + `data/game_records/` JSON 缓存 |
| 接口接入 | ✅ | `browser-fetch` / `demo` 返回 `snapshots`；新增 `POST /api/v1/paipu/simulate` |
| 单元测试 | ✅ | 新增 11 个状态机用例，总计 77 个用例全通过 |

### 阶段四（majiang-ui 前端回放对接）✅

| 子任务 | 状态 | 说明 |
| --- | --- | --- |
| majiang-ui 输入格式调研 | ✅ | 确认 `paipu` 对象结构与 `Board` 事件格式 |
| 数据转换器 | ✅ | `replay/adapter.py`：事件流/快照 → majiang-ui paipu |
| 回放数据接口 | ✅ | `GET /api/v1/paipu/{uuid}/replay` |
| 前端回放接入 | ✅ | `static/index.html` 自动加载 majiang-ui 回放（步进/自动播放/巡目跳转） |
| 真实牌谱验证 | ✅ | 6 份真实四麻牌谱通过 Node + majiang-core Board 完整回放 |
| 单元测试 | ✅ | 新增适配器测试，当前总计 86 个用例全通过 |

### 阶段五（AI 推理模块）✅

| 子任务 | 状态 | 说明 |
| --- | --- | --- |
| Mortal 源码/权重接入 | ✅ | `Mortal/` 仓库 + `weights/mortal_298k.pth`（v4） |
| 权重加载与引擎构建 | ✅ | `ai_module/mortal_model_adapter.py`：加载 Brain/DQN，构建 MortalEngine |
| 雀魂事件 → mjai 转换 | ✅ | `ai_module/mjai_converter.py`：真实牌谱可被 libriichi PlayerState 完整消费 |
| Mortal 推理 | ✅ | `ai_module/mortal_inference.py`：真实牌谱输出 76 个决策点 AI 推荐 |
| obs 编码 | ✅ | 推理使用官方 libriichi 生成 `(1012,34)` obs；`obs_encoder.py` 为纯 Python 备用实现 |
| 复盘对比/失误分析/报告 | ✅ | `ai_module/replay_analyzer.py`：实战动作对比、失误统计、summary |
| API | ✅ | `GET /api/v1/paipu/{uuid}/ai` |
| 单元测试 | ✅ | 当前总计 101 个用例全通过 |

> **拉取方式说明**：雀魂自 2023 年起阻止程序化登录（错误码 151），
> Python 直连登录不可用。当前主路径为**浏览器拉取**——通过本地调试浏览器
> 打开牌谱链接，雀魂页面自动拉取，我们截获 WebSocket 响应帧并解码。
> 无需 token，仅需浏览器保持雀魂登录态。

## 目录结构

```
majong_replay/
├── main.py                 # FastAPI 入口（parse / browser-fetch / demo + 静态服务）
├── config.py               # pydantic-settings 配置（.env 读取）
├── url_parser.py           # 雀魂牌谱链接解析（阶段一）
├── majsoul_ws.py           # 雀魂 WebSocket 协议层（底层保留，备用）
├── token_helper.py         # 浏览器 CDP 捕获/关闭（浏览器拉取核心）
├── game_state/             # 阶段三：对局状态机
│   ├── state_model.py      # 状态模型（GameState/PlayerState/LiqiState/快照）
│   ├── game_simulator.py   # 事件推演核心（逐事件还原对局）
│   └── snapshot.py         # 快照生成 + JSON 缓存
├── replay/                 # 阶段四：回放适配
│   └── adapter.py          # 事件流/快照 → majiang-ui paipu 转换器
├── ai_module/              # 阶段五：AI 推理
│   ├── obs_encoder.py      # 局面编码（Mortal v4 形状对齐中）
│   ├── mortal_model_adapter.py # 权重加载与 MortalEngine 构建
│   ├── mjai_converter.py   # 雀魂事件 → mjai 事件
│   ├── mortal_inference.py # 基于 libriichi 的推理器
│   └── replay_analyzer.py  # 复盘分析器
├── proto/
│   ├── protocol.proto      # 雀魂协议定义（967 消息）
│   ├── protocol_pb2.py     # 编译产物
│   ├── decoder.py          # 二进制 → 事件列表解码器（阶段二核心）
│   ├── liqi.json           # 官方协议原始描述
│   └── generate_proto_file.py
├── tests/
│   ├── test_url_parser.py  # 26 用例
│   ├── test_decoder.py     # 9 用例（含真实牌谱 fixture）
│   ├── test_majsoul_ws.py  # 8 用例（帧协议 / 错误映射）
│   ├── test_token_helper.py# 23 用例（CDP 捕获 / 关闭 / 帧解析）
│   ├── test_game_simulator.py # 15 用例（状态机推演）
│   ├── test_adapter.py     # 5 用例（majiang-ui 数据转换）
│   └── fixtures/           # 真实牌谱样例（MIT 许可）
├── static/
│   ├── index.html          # 基础页面（浏览器拉取 / 解析 / 示例）
│   └── majiang-ui/         # majiang-ui 前端子工程
└── weights/                # AI 权重目录（阶段五，不入库）
```

## 快速开始

```sh
# 1. 安装 Python 依赖（已装可跳过）
pip install -r requirements.txt

# 2. 启动服务
uvicorn main:app --reload
# 或 python main.py

# 3. 访问
#    主页面      http://127.0.0.1:8000
#    接口文档    http://127.0.0.1:8000/docs
```

## 使用方式（浏览器拉取）

1. 打开 http://127.0.0.1:8000
2. 若调试浏览器未启动：先手动启动（独立 profile，首次需登录一次雀魂）：
   ```sh
   python -c "import token_helper; token_helper.launch_browser()"
   ```
3. 页面粘贴牌谱链接 → 点「**浏览器拉取（推荐）**」
4. 等待 10~60 秒（Unity 加载）→ 显示对局行为事件流
5. 拉取成功后调试浏览器**自动关闭**；下次使用重复步骤 2~4（profile 保留登录态）

原理：通过 CDP（Chrome DevTools 协议）连接调试浏览器，让浏览器打开牌谱链接，
监听 WebSocket 帧截获 `fetchGameRecord` 响应。无需扩展、无需证书、无需 token。

## CLI 解码已保存的牌谱

```sh
# 解码内置示例
python .dev/demo_decode.py

# 解码自己保存的 .bin（浏览器拉取接口暂未提供保存，可自行扩展）
python .dev/demo_decode.py <文件路径>
```

### API

* `POST /api/v1/paipu/parse` — 解析牌谱链接（无需登录）
* `POST /api/v1/paipu/browser-fetch` — 浏览器拉取并解码（主路径，需调试浏览器已登录），返回 `events` + `snapshots`
* `GET  /api/v1/paipu/demo` — 内置示例解码（无需登录/网络），返回 `events` + `snapshots`
* `POST /api/v1/paipu/simulate` — 直接对事件流做状态机重放，返回逐事件完整快照
* `GET  /api/v1/paipu/{uuid}/replay` — 从快照缓存生成 majiang-ui 回放数据
* `GET  /api/v1/paipu/{uuid}/ai` — 对已拉取牌谱运行 Mortal AI 推理，返回逐决策点推荐（需 .venv 环境）

## 运行测试

```sh
python -m unittest discover -s tests -v
```

## 牌谱链接格式（url_parser 支持）

* 普通牌谱：`https://game.maj-soul.com/1/?paipu=200515-cfbe0120-c92c-44ad-bdfc-ebfef3a33a10_a89702544`
* 匿名牌谱：`https://game.maj-soul.com/1/?paipu=jijpmr-0415suwv-971c-67ei-ilom-qottvksmnvnn_a89702544_2`
* 旧式链接（无 `_a` 后缀）、残缺链接（直接 `paipu=xxx`）均可解析

对局 ID = 6 位日期（匿名时被编码）+ 8-4-4-4-12 位小写字母数字；
`_a<数字>` 为主视角账号 ID，`_2` 表示匿名牌谱。
`url_parser` 同时提供匿名/普通 UUID 互转（`encode_anonymous_uuid` / `decode_anonymous_uuid`）。

## 事件类型（decoder 输出）

`new_round` 配牌 / `deal_tile` 摸牌 / `discard_tile` 打牌（含立直）/
`chi_peng_gang` 吃碰杠 / `an_gang_add_gang` 暗杠加杠 / `ba_bei` 拔北 /
`gang_result` 杠结果 / `hu` 和牌 / `liu_ju` 流局 / `no_tile` 无牌 / `game_end` 结算 等。

## 参考来源

* 开发文档：`雀魂牌谱本地复盘系统开发文档.docx`
* 协议：<https://github.com/MahjongRepository/mahjong_soul_api>
* 前端 UI：<https://github.com/kobalab/majiang-ui>（MIT）
* 匿名 UUID 算法：<https://github.com/Fat-pig-Cui/misc-code>
* 真实牌谱样例：<https://github.com/honvl/Majsoul-to-NAGA>（MIT）
* Mortal AI 源码：<https://github.com/Equim-chan/Mortal>（AGPL-3.0）
* 社区轻量化 Mortal 权重：<https://huggingface.co/VoidShine/mortal-298k>（AGPL-3.0，本地位于 `weights/mortal_298k.pth`）
