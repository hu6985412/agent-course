# W08 · LangGraph 退款 Agent 实验代码

用 LangGraph 重写 W04 的零框架退款 Agent：把"循环 + 状态 + 人机确认 + 持久化"工程化。
三个递进版本，从零依赖验证图结构，到接 Postgres 做跨进程崩溃续跑，再到真实 LLM 全链路。

> 示例场景用通用的"订单 → 退款"流程，仅演示 Agent 工程能力，不挂钩任何真实业务。

## 1. 依赖安装（managed venv 的 pip）

```bash
pip install langgraph langgraph-checkpoint-postgres langchain-openai psycopg
```

- `langgraph-checkpoint-postgres`：PostgresSaver（v2 / v3 用，v1 不用）
- `langchain-openai`：真实 LLM 客户端（仅 v3 / test_llm 用；v1 / v2 走内置 MockModel，零依赖）

## 2. 环境变量

把 `.env.example` 复制为 `.env` 并填入（**真实 Key 只在终端环境变量里，不进文件**）。

```powershell
# PowerShell（bat 已加载 API_KEY/BASE_URL/MODEL 时，下面这些只需补 PG_*）
$env:PG_HOST="127.0.0.1"; $env:PG_PORT="5432"; $env:PG_DB="w08lg"
$env:PG_USER="amber"; $env:PG_PASSWORD="amber123"
```

> 模型区分：`CHAT_MODEL`（对话/工具调用）与 `EMBEDDING_MODEL`（向量化）是不同场景，
> 不要像早期那样把 `MODEL` 填成 embedding 模型 —— 否则网关报 400 `input.contents`。

## 3. 版本运行

### v1 · 图结构验证（MemorySaver + MockModel，零外部依赖）

```bash
python refund_graph.py
```

不连数据库、不联网、不依赖 `langchain_openai`：用内置 MockModel 把 ReAct 循环跑出来，
`interrupt()` 挂起 → 同 `thread_id` + `Command(resume=...)` 续跑，验证图结构正确。

### v2 · 跨进程崩溃续跑（PostgresSaver，接本机 pgvector 容器）

```bash
# 1) 用容器 ID 引用（Docker name 解析不稳，绕开 name）
$PG_CONTAINER_ID = (docker ps -q --filter "ancestor=pgvector/pgvector:0.8.6-pg17")
docker exec -i $PG_CONTAINER_ID psql -U amber -d template1 -c "CREATE DATABASE w08lg OWNER amber;"

# 2) 设 PG_* 环境变量（见第 2 节），然后
python refund_graph_pg.py
```

进程 A 跑到 `interrupt` 挂起 → "崩溃退出"；进程 B 用**全新连接 + 全新 app 实例 + 同一 `thread_id`**
从 Postgres 读 checkpoint 续跑，最终 `refunded=True`，并打印 `state history`（时间旅行）。

### v3 · 真实 LLM 全链路（ChatOpenAI + PostgresSaver + 真实退款端点 mock）

```bash
$env:W08_REAL="1"
python refund_graph_real.py
```

真实 LLM 自己决定何时 `fetch_order` / `request_refund`；`interrupt()` 等人批准；
批准后调 `simulate_refund_api`（mock，带幂等键，不真扣钱）。

### 排错脚本

```bash
python test_llm.py       # 把图摘掉，只验证 ChatOpenAI 基础调用能否通（打印 CHAT_MODEL/BASE_URL）
```

## 4. 文件清单

| 文件 | 作用 |
|---|---|
| `refund_graph.py` | v1：MemorySaver + MockModel，验证循环 + 结构化状态路由 + interrupt 续跑 |
| `refund_graph_pg.py` | v2：PostgresSaver 跨进程崩溃续跑 + 时间旅行（复用 v1 的图定义） |
| `refund_graph_real.py` | v3：真实 ChatOpenAI 驱动 + PostgresSaver 持久化 + 真实退款端点（幂等 mock） |
| `test_llm.py` | 最小隔离测试：只验证 LLM API 调用本身（排查 `input.contents` 类网关不兼容） |

> pgvector 建库脚本 `00_start_pgvector.sh` 在 week-06/code（W05–W15 复用同一容器，按库名区分周次）。
