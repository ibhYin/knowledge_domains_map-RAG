# 知识图谱 RAG 系统（GraphRAG）

基于 **NetworkX + LangChain + 中文 LLM 实体抽取**的知识图谱 RAG 项目，提供 FastAPI 后端与 Vue 3 前端页面（含知识图谱可视化）。

## 架构

```
文档(PDF/MD/TXT/DOCX) → 加载 → 中文分块 → LLM 抽取实体/关系 → NetworkX 图谱 → JSON 持久化
查询: 问题 → LLM 抽种子实体 → 定位 → BFS 扩张 → 中文上下文 → LLM 生成答案
```

纯图谱检索，不依赖向量库。实体抽取与问答使用 OpenAI 兼容端点（自定义 base_url + api_key）。

## 目录结构

```
├── src/graphrag/          # 后端（config/schemas/loaders/splitting/llm/graph/retrieval/pipeline/api）
│   └── supervisor/        # 引导服务（后台管理启停与自动重载，端口 8001，无页面）
├── scripts/restart.sh     # 重启后端（构建中询问；--supervisor 连控制服务一起重启）
├── web/                   # Vue 3 + Vite + ECharts 前端
├── data/                  # 运行时数据（文档/分块/图谱/日志，git 忽略）
├── 启动GraphRAG.command   # 双击启动（确保运行并显示当前进程信息）
├── start.sh               # 命令行版启动脚本
├── .env.example           # 环境变量模板
└── requirements.txt
```

## 端口与架构

| 端口 | 服务 | 说明 |
|---|---|---|
| **8002** | RAG 系统 | 主应用（首页/文档/图谱/图谱浏览器/问答/问答历史/**模型设置**） |
| **8001** | 引导服务 | 纯后台（无页面），负责拉起 8002，并在后端源码变更时自动重载 |

日常使用只进 **8002**：「模型设置」页配置 LLM 并查看运行状态。8001 无需手动访问；业务页面不提供服务启动、停止或重启按钮。

## 快速开始

### 1. 配置环境（仅首次）

```bash
conda activate langchain
pip install fastapi python-docx    # 仅需补充这两个包
```

### 2. 启动

**方式 A（推荐，无需终端）**：双击项目根目录的 `启动GraphRAG.command` → 确保系统运行并打开 http://localhost:8002；已在运行则不会打断当前任务。窗口会显示后端 PID、启动时间和自动重载状态。

**方式 B（命令行）**：

```bash
./start.sh            # 启动问答系统（先清理端口上的旧后端）
./start.sh restart    # 重启后端（构建中会询问；--force 跳过）
./start.sh dev        # 开发模式：前端 :5173 + 后端 :8002（热更新）
```

### 3. 代码变更与重启

- 改后端代码（`src/`，不含 `supervisor/`）：控制服务空闲时自动重载；构建进行中会延后到任务结束。页面无需刷新。
- 改前端代码：重新构建 `web/dist` 后刷新页面即可，无需重启后端。
- 改 `src/graphrag/supervisor/`：`./start.sh restart --supervisor`。
- 改非 LLM 的 `.env` 配置（分块、并发、发布间隔等）：`./start.sh restart`。
- 在「模型设置」页保存 base_url / api_key / model 不需要重启，下一次模型调用即生效。

### 4. 日常使用（都在 8002）

1. **模型设置**页：填写 **base_url / api_key / model** → 保存；新建的模型请求使用新配置
2. **文档**页上传 → **图谱**页构建 → **问答**页提问
3. 构建时可以切换页面；刷新后进入图谱页，会继续显示最近一次任务。后端代码变更会在构建结束后自动重载；手动重启（`./start.sh restart`）会终止正在运行的任务，页面会提示任务不存在，重新点击构建可从已保存的进度继续

> 手动启动后端备用命令：`PYTHONPATH=src uvicorn src.graphrag.api.main:app --port 8002`

## 使用流程

1. **文档**页签：上传 PDF / MD / TXT / DOCX（多文件）
2. **图谱**页签：点击「构建图谱」→ 轮询进度 → 查看统计与图谱可视化（点击节点高亮邻居）
3. **问答**页签：输入问题 → 展示答案、匹配实体、检索上下文与相关子图

## API 端点

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/documents/ingest` | 上传文档 |
| GET | `/api/documents` | 文档列表 |
| POST | `/api/graph/build` | 异步启动建图，返回 job_id |
| GET | `/api/graph/build/status/{job_id}` | 构建进度 |
| GET | `/api/graph/stats` | 图谱统计 |
| GET | `/api/graph/viz?limit=300` | 已保存图谱快照（含版本和完整统计，限制画布大小） |
| POST | `/api/query` | 问答 `{question, hops, max_nodes}` |
| GET | `/api/graph/export?fmt=graphml` | 导出图谱 |

## 配置项（.env）

| 变量 | 说明 |
|---|---|
| `OPENAI_BASE_URL` | OpenAI 兼容端点地址（如 `https://xxx/v1`） |
| `OPENAI_API_KEY` | API Key |
| `OPENAI_MODEL` | 模型名 |
| `STRUCTURED_OUTPUT_METHOD` | `json_mode`（默认）/ `function_calling` / `json_schema` |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | 分块大小/重叠（字符） |
| `EXTRACTION_CONCURRENCY` | 抽取并发数 |
| `BUILD_CHECKPOINT_INTERVAL` | 阶段保存间隔，默认新增 5 个成功分块；首个成功结果立即保存 |
| `BUILD_PUBLISH_INTERVAL` | 有新结果时的最长批次等待时间，默认 2 秒；慢请求尚未返回时也会定时发布已完成结果 |
| `BACKEND_AUTORELOAD` | 后端源码变更自动重载，默认 `1`（开启）；`0` 关闭 |
| `BACKEND_AUTORELOAD_INTERVAL` | 自动重载检查间隔（秒），默认 `2` |
| `EXTRACTION_THINKING` | 可选 enabled / disabled，仅对支持 thinking 参数的模型设置；只作用于文档和问题实体抽取，默认不发送该参数 |

### 长任务与进度

每个成功分块的抽取底稿原子保存到 `data/extractions/<doc_id>/<chunk_index>.json`，包含实体、关系、内容哈希和抽取配置指纹。空结果也会缓存；失败不缓存。重试优先复用底稿，即使图谱保存失败，也无需重复调用模型。内容或模型、提示词、结构变更时缓存失效，并重新合图以清除旧贡献。

新版后端可通过 `/api/graph/build/current` 找到当前任务，不依赖某个浏览器事先记住任务 ID。页面显示处理百分比、成功／失败数量、最近获取进度的时间；切换页面后顶部仍显示当前任务。

分块按完成顺序合图，避免一个慢请求堵住后面已完成的进度。首个成功结果立即保存，之后新增 5 个成功分块或有新结果等待 2 秒时保存、发布一版图谱。网页每 1.5 秒查询进度，发现版本变化才读取新的画布快照，构建途中也能看到节点与关系增长。图谱与成功处理记录放入同一个原子快照；中断后重新启动并点击构建，可跳过已保存的成功分块。支持读取原有图谱格式；meta.json 保留为兼容镜像，以 graph.json 内的 metadata 为准。

实体／关系数量与画布来自同一已保存版本。默认画布最多展示前 300 个实体、900 条关系，并标明完整数量；完整图谱仍保存，可通过图谱浏览器查看其他实体。切到其他页面后继续查询任务进度，但暂停隐藏画布更新；返回后读取最新版本。新节点加入时复用已有节点 ID 和布局，保留缩放、平移及选中状态。

若模型支持关闭深度思考，可配置 `EXTRACTION_THINKING=disabled`，先用短样例验证速度和抽取质量。切换到不支持 thinking 的服务时，应移除此配置；不应只为提速盲目增加并发。

后端源码变更后，控制服务（:8001）会自动重载后端：空闲时立即重载，构建进行中则等任务结束再重载。重载会清空内存中的任务状态，但已发布的图谱与成功处理记录都已落盘，重新点击构建可跳过已处理分块。启动时 `main.py` 会从 `data/graph/` 重新加载图谱，重启不会丢失已发布内容；只有最后一个未发布批次（最多约 5 个分块）需要重做。

### 火山方舟 Coding Plan 配置

本项目使用 OpenAI 兼容协议。Coding Plan 的 `OPENAI_BASE_URL` 应填写：

```text
https://ark.cn-beijing.volces.com/api/coding/v3
```

`https://ark.cn-beijing.volces.com/api/coding` 是 Anthropic 协议入口，直接填入本项目会导致请求返回 404。协议与地址对应关系见 [火山方舟官方说明](https://docs.volcengine.com/docs/ark/coding-plan-personal-ai-hermes-agent?lang=en)。模型和密钥使用自己账号的有效配置。

后端源码变更由控制服务自动重载；`supervisor/` 自身的改动需要 `./start.sh restart --supervisor`。手工重启使用 `./start.sh restart`（构建中会询问，`--force` 跳过）。自动重载是否生效、当前后端 PID 与代码更新时间显示在「模型设置」页的「运行状态」卡片，也可通过 `GET /api/health` 与 `GET /api/control/status` 查看。

整批建图前，可先运行 `python docs/smoke_extract.py`：使用内置短文本，通过两次真实模型调用检查文档抽取、问题实体抽取和图谱保存／重载。检查使用临时目录，不修改原有文档或图谱；需要先安装项目依赖并配置模型。

## 说明与限制

- 纯图谱检索：问题实体不在图中时无法回答，系统会诚实提示（可配合 `seed_override` 调试）
- 中文 PDF 依赖内嵌文本，扫描件需 OCR（预留扩展点）
- 若结构化输出大面积失败，切换 `STRUCTURED_OUTPUT_METHOD=function_calling`
