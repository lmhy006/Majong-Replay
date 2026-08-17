# 雀魂牌谱本地复盘系统

完全本地运行、自主可控的雀魂牌谱 **解析 + 回放 + AI 复盘** 系统。

* 输入雀魂牌谱链接 → 自动拉取 → Protobuf 解码 → 状态机仿真 → majiang-ui 可视化回放
* AI 阶段接入社区开源轻量化 Mortal 权重（仅推理，不训练）

## 当前进度：阶段一（基础环境搭建）✅

| 子任务 | 状态 | 说明 |
| --- | --- | --- |
| 项目目录 + requirements.txt + 依赖安装 | ✅ | Python 3.12，依赖见 `requirements.txt` |
| 编译 Protobuf 协议文件 | ✅ | `proto/`（protocol.proto + protocol_pb2.py + liqi.json） |
| URL 解析模块 + 单元测试 | ✅ | `url_parser.py`（26 个用例全通过） |
| majiang-ui 资源 + 基础页面 | ✅ | `static/majiang-ui/`（JS/CSS 本地打包）+ `static/index.html` |

## 目录结构

```
majong_replay/
├── main.py                 # FastAPI 入口（静态服务 + /api/v1/paipu/parse）
├── config.py               # pydantic-settings 配置（.env 读取）
├── url_parser.py           # 雀魂牌谱链接解析（阶段一核心）
├── majsoul_ws.py           # 牌谱 WebSocket 拉取（阶段二 TODO）
├── proto/                  # 雀魂 Protobuf 协议（protocol.proto / pb2 / liqi.json）
├── tests/                  # 单元测试（test_url_parser.py）
├── static/
│   ├── index.html          # 基础页面（输入链接 → 解析展示）
│   └── majiang-ui/         # majiang-ui 前端子工程（npm 打包出 JS/CSS + 图片音频）
└── weights/                # AI 权重目录（阶段五，不入库）
```

## 快速开始

```sh
# 1. 安装 Python 依赖（已装可跳过）
pip install -r requirements.txt

# 2.（可选）重新构建 majiang-ui 前端资源
cd static/majiang-ui && npm install && npm run build && cd ../..

# 3. 启动服务
uvicorn main:app --reload
# 或 python main.py

# 4. 访问
#    主页面      http://127.0.0.1:8000
#    接口文档    http://127.0.0.1:8000/docs
```

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

## 参考来源

* 开发文档：`雀魂牌谱本地复盘系统开发文档.docx`
* 协议：<https://github.com/MahjongRepository/mahjong_soul_api>
* 前端 UI：<https://github.com/kobalab/majiang-ui>（MIT）
* 匿名 UUID 算法：<https://github.com/Fat-pig-Cui/misc-code>
