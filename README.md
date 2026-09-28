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
│   └── supervisor/        # 控制台服务（LLM 配置 + 一键启停，端口 8001）
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
| **8001** | 控制台 | 常驻服务：填 LLM 配置、一键启动/停止系统、查看日志 |
| **8002** | RAG 系统 | 真正的应用（文档/图谱/问答页面），由控制台启停 |

## 快速开始

### 1. 配置环境（仅首次）

```bash
conda activate langchain
pip install fastapi python-docx    # 仅需补充这两个包
```

### 2. 启动（两种方式任选）

**方式 A（推荐，无需终端）**：双击项目根目录的 `启动GraphRAG.command`，自动打开控制台 `http://localhost:8001`。

**方式 B（命令行）**：

```bash
./start.sh         # 启动控制台（等价双击 .command）
./start.sh dev     # 开发模式：前端 :5173 + 后端 :8002（热更新）
```

### 3. 在控制台页面操作

1. 填写 **base_url / api_key / model** → 点「保存设置」（保存后立即生效，无需重启）
2. 点「**启动系统**」→ 自动打开系统页面 `http://localhost:8002`
3. 想停止时回到控制台点「**停止系统**」；「退出控制台」可关闭控制台本身

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
| GET | `/api/graph/viz` | 图谱数据（ECharts 格式） |
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

## 说明与限制

- 纯图谱检索：问题实体不在图中时无法回答，系统会诚实提示（可配合 `seed_override` 调试）
- 中文 PDF 依赖内嵌文本，扫描件需 OCR（预留扩展点）
- 若结构化输出大面积失败，切换 `STRUCTURED_OUTPUT_METHOD=function_calling`
