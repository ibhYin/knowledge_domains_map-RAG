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
│   └── supervisor/        # 引导服务（后台管理启停，端口 8001，无页面）
├── web/                   # Vue 3 + Vite + ECharts 前端
├── data/                  # 运行时数据（文档/分块/图谱/日志，git 忽略）
├── 启动GraphRAG.command   # 双击启动控制台
├── start.sh               # 命令行版启动脚本
├── .env.example           # 环境变量模板
└── requirements.txt
```

## 端口与架构

| 端口 | 服务 | 说明 |
|---|---|---|
| **8002** | RAG 系统 | 主应用（首页/文档/图谱/图谱浏览器/问答/问答历史/**模型设置**） |
| **8001** | 引导服务 | 纯后台（无页面），由启动脚本使用，负责拉起 8002 |

日常使用只进 **8002**：「模型设置」页配置 LLM。8001 是启动脚本使用的后台引导服务，无需手动访问；业务页面不提供服务启动、停止或重启按钮。

## 快速开始

### 1. 配置环境（仅首次）

```bash
conda activate langchain
pip install fastapi python-docx    # 仅需补充这两个包
```

### 2. 启动

**方式 A（推荐，无需终端）**：双击项目根目录的 `启动GraphRAG.command` → 自动启动系统并直接打开 http://localhost:8002。

**方式 B（命令行）**：

```bash
./start.sh         # 一键启动问答系统（等价双击 .command）
./start.sh dev     # 开发模式：前端 :5173 + 后端 :8002（热更新）
```

### 3. 日常使用（都在 8002）

1. **模型设置**页：填写 **base_url / api_key / model** → 保存；新建的模型请求使用新配置
2. **文档**页上传 → **图谱**页构建 → **问答**页提问
3. 构建时可以切换页面；刷新后进入图谱页，会继续显示最近一次任务。后端重启会终止正在运行的任务，页面会提示任务不存在

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
| `EXTRACTION_THINKING` | 可选 enabled / disabled，仅对支持 thinking 参数的模型设置；只作用于文档和问题实体抽取，默认不发送该参数 |

### 长任务与进度

新版后端可通过 `/api/graph/build/current` 找到当前任务，不依赖某个浏览器事先记住任务 ID。页面显示处理百分比、成功／失败数量、最近获取进度的时间；切换页面后顶部仍显示当前任务。

分块按完成顺序合图，避免一个慢请求堵住后面已完成的进度。首个成功结果立即保存，之后新增 5 个成功分块或有新结果等待 2 秒时保存、发布一版图谱。网页每 1.5 秒查询进度，发现版本变化才读取新的画布快照，构建途中也能看到节点与关系增长。图谱与成功处理记录放入同一个原子快照；中断后重新启动并点击构建，可跳过已保存的成功分块。支持读取原有图谱格式；meta.json 保留为兼容镜像，以 graph.json 内的 metadata 为准。

实体／关系数量与画布来自同一已保存版本。默认画布最多展示前 300 个实体、900 条关系，并标明完整数量；完整图谱仍保存，可通过图谱浏览器查看其他实体。切到其他页面后继续查询任务进度，但暂停隐藏画布更新；返回后读取最新版本。新节点加入时复用已有节点 ID 和布局，保留缩放、平移及选中状态。

若模型支持关闭深度思考，可配置 `EXTRACTION_THINKING=disabled`，先用短样例验证速度和抽取质量。切换到不支持 thinking 的服务时，应移除此配置；不应只为提速盲目增加并发。

已经运行中的旧后端不会自动加载这些代码。在长任务期间不要为升级重启后端；应等当前任务保存完成后再启动新版本。本次前端发布为现有旧任务附带一次性恢复信息，新后端启动后由当前任务 API 负责发现。

### 火山方舟 Coding Plan 配置

本项目使用 OpenAI 兼容协议。Coding Plan 的 `OPENAI_BASE_URL` 应填写：

```text
https://ark.cn-beijing.volces.com/api/coding/v3
```

`https://ark.cn-beijing.volces.com/api/coding` 是 Anthropic 协议入口，直接填入本项目会导致请求返回 404。协议与地址对应关系见 [火山方舟官方说明](https://docs.volcengine.com/docs/ark/coding-plan-personal-ai-hermes-agent?lang=en)。模型和密钥使用自己账号的有效配置。

修改后端源码后，需要在构建任务结束后通过终端重新启动后端；普通模式不自动重新加载代码。重新双击 `.command` 遇到健康的旧进程时，也不会强制重启它。

整批建图前，可先运行 `python docs/smoke_extract.py`：使用内置短文本，通过两次真实模型调用检查文档抽取、问题实体抽取和图谱保存／重载。检查使用临时目录，不修改原有文档或图谱；需要先安装项目依赖并配置模型。

## 说明与限制

- 纯图谱检索：问题实体不在图中时无法回答，系统会诚实提示（可配合 `seed_override` 调试）
- 中文 PDF 依赖内嵌文本，扫描件需 OCR（预留扩展点）
- 若结构化输出大面积失败，切换 `STRUCTURED_OUTPUT_METHOD=function_calling`
