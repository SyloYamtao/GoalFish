<div align="center">

<img src="./frontend/src/assets/logo/GoalFish_logo_left.jpeg" alt="GoalFish Logo" width="45%"/>

世界杯比赛预测：赛前情报、图谱推理与比分预测工作台
</br>
<em>A World Cup match forecasting workspace for pre-match intelligence, knowledge-graph reasoning, and scoreline prediction</em>

[English Version](./README.md)

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](./LICENSE)
[![Node.js](https://img.shields.io/badge/Node.js-18%2B-339933?style=flat-square&logo=node.js&logoColor=white)](https://nodejs.org/)
[![Python](https://img.shields.io/badge/Python-3.11--3.12-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Vue](https://img.shields.io/badge/Vue-3-4FC08D?style=flat-square&logo=vue.js&logoColor=white)](https://vuejs.org/)
[![Docker](https://img.shields.io/badge/Docker-Services-2496ED?style=flat-square&logo=docker&logoColor=white)](https://www.docker.com/)

</div>

## 项目概览

**GoalFish** 是一个从 [MiroFish](https://github.com/666ghj/MiroFish) 群体智能预测工作流衍生而来的世界杯比赛预测系统，专注于足球赛前情报分析。它可以把球探笔记、公开赛事资料、球队背景和球员数据组织成一条结构化预测流程：上传证据、构建足球知识图谱、配置比赛假设、运行场景推演、生成预测报告，并在报告生成后继续围绕上下文追问。

这个项目面向世界杯赛前预测场景，强调证据、阵容背景、战术假设和球队近期信号。它的核心不是直接让大模型给出一个猜测，而是把预测过程拆成可检查、可追问的步骤：

- **证据优先**：导入赛前研究文档，抽取足球实体、事件、关系和支撑细节。
- **图谱推理**：使用 Graphiti + Neo4j 把上下文保存为可检索的赛事知识图谱。
- **结构化输入**：结合球队元数据、阵容数据、排名种子、球员属性、教练视角评审和用户设定的场景假设。
- **推演与报告**：运行比分场景模拟，并生成可读的赛事预测报告和可追溯的推理说明。
- **交互式复盘**：报告生成后，可以继续基于同一个项目上下文提问、质疑假设或探索替代情景。

## 可用场景

GoalFish 当前重点支持 **世界杯比赛预测**。内置数据和样例流程围绕国家队比赛设计，适合以下场景：

- 在世界杯赛前预测胜 / 平 / 负倾向。
- 结合球队强度、球员可用性、战术信息和比赛背景，估计可能比分。
- 将赛前研究报告转成知识图谱，为有证据支撑的预测提供上下文。
- 对比不同假设下的结果变化，例如阵容调整、伤停影响、教练策略或近期状态波动。
- 生成结构化预测报告，并通过后续问答继续检查证据和推理链条。

**免责声明**：GoalFish 仅提供分析辅助。足球比赛受到不确定性、偶然性、临场状态和情感因素影响，任何模型都无法完整捕捉全部变量。本项目不对任何预测结果负责，也不对基于预测报告作出的任何决策负责。

<em>足球之神正深情地注视着这届世界杯比赛，他把奇迹留给赤子之心，让所有冰冷的分析，都沦为这场热爱最壮丽的注脚。</em>

## 运行效果

<div align="center">
<table>
<tr>
<td><img src="./static/00_upload_zh.png" alt="上传赛事资料" width="100%"/></td>
<td><img src="./static/02_graph_entity_extract_end.png" alt="构建赛事知识图谱" width="100%"/></td>
</tr>
<tr>
<td><img src="./static/03_config.png" alt="预测参数配置" width="100%"/></td>
<td><img src="./static/03_config_players_01.png" alt="球员配置" width="100%"/></td>
</tr>
<tr>
<td><img src="./static/06_game_prediction_page_1.png" alt="比赛场景推演" width="100%"/></td>
<td><img src="./static/07_report_page_1.png" alt="赛事预测报告" width="100%"/></td>
</tr>
<tr>
<td><img src="./static/08_report_chat_success.png" alt="预测问答" width="100%"/></td>
<td><img src="./static/04_config_mock_coach.png" alt="教练评审配置" width="100%"/></td>
</tr>
<tr>
<td colspan="2"><img src="./static/08_report_chat_success_2.png" alt="带战术上下文的预测问答" width="100%"/></td>
</tr>
</table>
</div>

## 工作流

1. **上传资料**：导入世界杯赛前报告、球探笔记、PDF 或文本资料，作为赛事项目的种子证据。
2. **构建图谱**：抽取球队、球员、战术因素、伤停、排名、状态和上下文关系，并写入 Graphiti / Neo4j。
3. **配置预测**：选择对阵双方，调整比赛假设，检查阵容数据，注入可选的教练或分析师视角。
4. **运行推演**：结合足球进球模型、场景权重、图谱证据和球员 / 球队强度估计。
5. **生成报告**：输出结构化预测报告，包含胜平负判断、可能比分、关键驱动因素和风险点。
6. **继续问答**：围绕报告上下文继续追问，检查证据、挑战假设或探索其他场景。

## 快速开始

### 环境要求

| 工具 | 版本 | 说明 | 检查命令 |
|------|------|------|----------|
| **Node.js** | 18+ | 根目录脚本和 Vite 前端运行时 | `node -v` |
| **Python** | >=3.11, <3.13 | Flask 后端运行时 | `python --version` |
| **uv** | 最新版 | Python 依赖和虚拟环境管理 | `uv --version` |
| **Docker** | 最新版 | PostgreSQL、Redis、Neo4j 基础服务 | `docker --version` |
| **Ollama** | 最新版 | 默认本地聊天模型和 embedding 模型运行时 | `ollama --version` |

### 1. 配置环境变量

```bash
cp .env.example .env
```

默认配置使用本地 Ollama：

```env
LLM_CHAT_PROTOCOL=ollama
LLM_BASE_URL=http://localhost:11434/api/chat
LLM_MODEL_NAME=qwen3.5:2b-mlx

GRAPHITI_EMBEDDING_PROVIDER=ollama
GRAPHITI_OLLAMA_EMBED_URL=http://127.0.0.1:11434/api/embed
GRAPHITI_EMBEDDING_MODEL=qwen3-embedding:0.6b
GRAPHITI_EMBEDDING_DIM=1024
```

如果改用 OpenAI-compatible 在线供应商，修改 `.env` 中的 `LLM_*` 字段：

```env
LLM_API_KEY=your_api_key_here
LLM_CHAT_PROTOCOL=openai
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL_NAME=deepseek-chat
LLM_RESPONSE_FORMAT_JSON_OBJECT_SUPPORTED=true
```

### 2. 启动基础服务

```bash
docker compose up -d postgres redis neo4j
```

默认服务地址：

- PostgreSQL: `localhost:5432`
- Redis: `localhost:6379`
- Neo4j Browser: `http://localhost:7474`
- Neo4j Bolt: `bolt://localhost:7687`

### 3. 准备 Ollama 模型

```bash
ollama serve
ollama pull qwen3-embedding:0.6b
```

同时确认 `.env` 中 `LLM_MODEL_NAME` 指定的模型已经存在于 `ollama list`。

### 4. 安装依赖

```bash
npm run setup:all
```

也可以分步安装：

```bash
npm run setup
npm run setup:backend
```

### 5. 初始化数据库

```bash
cd backend
uv run alembic upgrade head
cd ..
```

### 6. 导入默认球员数据

```bash
cd backend
uv run python scripts/import_player_dataset.py \
  --input ../data/wc2026_squads_cleaned.csv \
  --team-metadata ../data/wc2026_team_metadata.csv \
  --source-kind fifa_md_2026 \
  --scope fifa_world_cup_2026_squads \
  --dataset-id wc2026_fifa_v2 \
  --normalize-strategy fm
cd ..
```

### 7. 启动 Celery Worker

在单独的终端中运行：

```bash
cd backend
uv run celery -A app.celery_app.celery_app worker --loglevel=INFO
```

### 8. 启动前后端

在另一个终端中从项目根目录运行：

```bash
npm run dev
```

也可以单独启动：

```bash
npm run backend
npm run frontend
```

### 9. 打开页面

以 Vite 终端输出为准，通常是：

```text
http://localhost:3000
```

后端 API：

```text
http://localhost:5001
```

### 10. Demo 文件

```text
docs/sample/research/20260621/04.突尼斯vs日本赛前信息报告.md
```

## Demo 材料

可以使用仓库内置的突尼斯 vs 日本赛前报告体验完整流程：

```text
docs/sample/research/20260621/04.突尼斯vs日本赛前信息报告.md
```

英文样例：

```text
docs/sample/research/20260621/04.Tunisia_vs_Japan_Pre-Match_Report_EN.md
```

## 仓库内容

```text
backend/                         Flask API、Celery 任务、Graphiti 集成、足球预测服务
frontend/                        Vue 3 + Vite 前端应用
data/wc2026_squads_cleaned.csv   默认世界杯阵容 / 球员数据集
data/wc2026_team_metadata.csv    阵容导入脚本使用的球队元数据
data/holdout/                    回测 / 留出数据
docs/sample/research/            示例赛前研究文档
static/                          README 截图
```

## 常用命令

```bash
# 安装全部依赖
npm run setup:all

# 同时启动前后端
npm run dev

# 只启动后端
npm run backend

# 只启动前端
npm run frontend

# 运行后端测试
cd backend && uv run pytest

# 运行前端测试
cd frontend && npm test

# 构建前端
cd frontend && npm run build
```

## 说明

- 完整流程需要 PostgreSQL、Redis 和 Neo4j。
- 当前 `docker-compose.yml` 只启动基础设施服务；前端和后端从源码运行。
- GoalFish 的图谱记忆层使用 **Graphiti** 和 **Neo4j**，同时兼容本地 Ollama 与 OpenAI-compatible LLM 服务。**Celery** 在本项目中承担后台 workflow 执行器的角色，用于处理知识图谱构建、预测报告生成等耗时任务，并提供任务排队、状态持久化、失败重试和前端可见的进度更新。
- 图谱构建默认通过 Redis + Celery 执行。构建知识图谱时请保持 Celery worker 运行。
- 如果本地 Ollama 未运行，或者聊天模型 / embedding 模型缺失，依赖 LLM 的图谱和报告步骤会失败。
- 后端控制台输出会同步写入 `logs/<startup-time>.log`，便于排障。

## 致谢

GoalFish 源自 [MiroFish](https://github.com/666ghj/MiroFish) 项目结构，并将其多智能体预测工作流适配到足球赛前情报分析和比分预测场景。

## 许可证

AGPL-3.0
