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
├── web/                   # Vue 3 + Vite + ECharts 前端
├── data/                  # 运行时数据（文档/分块/图谱，git 忽略）
├── .env.example           # 环境变量模板
└── requirements.txt
```

## 快速开始

### 1. 配置环境

```bash
conda activate langchain
pip install fastapi python-docx    # 仅需补充这两个包
cp .env.example .env               # 填入 OPENAI_BASE_URL / OPENAI_API_KEY / OPENAI_MODEL
```

### 2. 一键启动

```bash
./start.sh         # 生产模式：单端口 http://localhost:8001（自动构建前端）
./start.sh dev     # 开发模式：前端 http://localhost:5173 + 后端 :8001（热更新）
```

脚本会自动激活 conda 环境、清理旧实例、轮询等待服务就绪并打开浏览器，Ctrl+C 一键停止。

### 手动启动（可选）

```bash
# 终端 1：后端
PYTHONPATH=src uvicorn src.graphrag.api.main:app --reload --port 8001
# 终端 2：前端（仅开发模式需要）
cd web && npm run dev
```

生产模式 `npm run build` 后由后端自动托管 `web/dist`（单端口访问 `http://localhost:8001`）。

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
