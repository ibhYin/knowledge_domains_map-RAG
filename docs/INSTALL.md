# 安装与运行

完整安装、配置与日常操作指南。前置要求：Python 3.10+、Node.js 18+、一个 OpenAI 兼容的模型端点（base_url + api_key）。conda 非必需，但启动脚本默认按 conda 环境启动。

## 端口

| 端口 | 服务 | 说明 |
|---|---|---|
| **8002** | RAG 系统 | 主应用（首页/文档/图谱/图谱浏览器/问答/问答历史/**模型设置**） |
| **8001** | 引导服务 | 纯后台（无页面），负责拉起 8002，并在后端源码变更时自动重载 |

日常使用只进 **8002**：「模型设置」页配置 LLM 并查看运行状态。8001 无需手动访问；业务页面不提供服务启动、停止或重启按钮。

## 1. 后端环境（仅首次）

```bash
conda create -n langchain python=3.10 -y   # 环境名可自取，用 CONDA_ENV 环境变量指定
conda activate langchain                   # 或 export CONDA_ENV=你的环境名
pip install -r requirements.txt
cp .env.example .env                       # 填入你的 base_url / api_key / 模型名
```

## 2. 前端构建（仅首次）

后端只在 `web/dist` 存在时提供页面，clone 后必须先构建：

```bash
cd web && npm install && npm run build && cd ..
```

## 3. 启动

**方式 A（推荐，macOS，无需终端）**：双击项目根目录的 `启动GraphRAG.command` → 确保系统运行并打开 http://localhost:8002；已在运行则不会打断当前任务。窗口会显示后端 PID、启动时间和自动重载状态。

**方式 B（命令行）**：

```bash
./start.sh            # 启动问答系统（先清理端口上的旧后端）
./start.sh restart    # 重启后端（构建中会询问；--force 跳过）
./start.sh dev        # 开发模式：前端 :5173 + 后端 :8002（热更新）
```

> 手动启动后端备用命令：`PYTHONPATH=src python -m uvicorn graphrag.api.main:app --port 8002`

## 4. 代码变更与重启

- 改后端代码（`src/`，不含 `supervisor/`）：控制服务空闲时自动重载；构建进行中会延后到任务结束。页面无需刷新。
- 改前端代码：重新构建 `web/dist` 后刷新页面即可，无需重启后端。
- 改 `src/graphrag/supervisor/`：`./start.sh restart --supervisor`。
- 改非 LLM 的 `.env` 配置（分块、并发、发布间隔等）：`./start.sh restart`。
- 在「模型设置」页保存 base_url / api_key / model 不需要重启，下一次模型调用即生效。

## 5. 日常使用（都在 8002）

1. **模型设置**页：填写 **base_url / api_key / model** → 保存；新建的模型请求使用新配置
2. **文档**页上传 → **图谱**页构建 → **问答**页提问
3. 构建时可以切换页面；刷新后进入图谱页，会继续显示最近一次任务。后端代码变更会在构建结束后自动重载；手动重启（`./start.sh restart`）会终止正在运行的任务，页面会提示任务不存在，重新点击构建可从已保存的进度继续

## 6. 使用流程

1. **文档**页签：上传 PDF / MD / TXT / DOCX（多文件）
2. **图谱**页签：点击「构建图谱」→ 轮询进度 → 查看统计与图谱可视化（点击节点高亮邻居）
3. **问答**页签：输入问题 → 展示答案、匹配实体、检索上下文与相关子图

## 7. API 端点

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

## 8. 配置项（.env）

| 变量 | 说明 |
|---|---|
| `OPENAI_BASE_URL` | OpenAI 兼容端点地址（如 `https://xxx/v1`） |
| `OPENAI_API_KEY` | API Key |
| `OPENAI_MODEL` | 模型名 |
| `STRUCTURED_OUTPUT_METHOD` | `json_mode`（默认）/ `function_calling` / `json_schema` |
| `LLM_TIMEOUT` / `LLM_MAX_RETRIES` | 模型请求超时秒数（默认 120）/ SDK 层重试次数（默认 3） |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | 分块大小/重叠（字符） |
| `EXTRACTION_CONCURRENCY` | 抽取并发数 |
| `SOURCE_RERANK` | 问答来源相关性重排序开关，默认 `1`；`0` 关闭（A/B 对照用） |
| `MAX_ANSWER_SOURCES` | 喂给回答模型的分块上限，默认 `40`；其余检索来源仍可在页面展开 |
| `BUILD_CHECKPOINT_INTERVAL` | 阶段保存间隔，默认新增 5 个成功分块；首个成功结果立即保存；大语料下会按总量自适应放宽 |
| `BUILD_PUBLISH_INTERVAL` | 有新结果时的最长批次等待时间，默认 2 秒 |
| `BACKEND_AUTORELOAD` | 后端源码变更自动重载，默认 `1`（开启）；`0` 关闭 |
| `EXTRACTION_THINKING` | 可选 enabled / disabled，仅对支持 thinking 参数的模型设置；只作用于抽取调用，默认不发送该参数 |
