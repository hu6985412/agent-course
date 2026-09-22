# W08 · LangGraph：把循环变成工程

> Agent 开发实战 15 周 · 第 8 周 · 实际投入约 14 小时（含阶段1 六小节引导、三版递进实操、收尾写作）
>
> 一句话钩子：**W04 你手搓的 while 循环 Agent 已经能跑退款全流程——但进程一崩就失忆、危险操作只能卡在 input() 阻塞、跑完无法回放。这些 W04 里"手动补的窟窿"，LangGraph 把它们变成了框架原语。本周我们把那个零框架 Agent 重写一遍，看清框架到底帮你省了什么。**

另有一份 [学习对话实录](DIALOGUE.md)：这周完整的引导过程 + 一套可直接丢给 AI 的**复现脚本**。还有 [逐轮一问一答底稿](DIALOGUE-QA.md)：每一次提问、回答、终端输出原样保留。

## 开篇：这周要解决什么问题

W04 你手搓了一个 `while` 循环 Agent：模型说调工具就调、工具结果回填再问模型，直到模型说"完了"。退款全自动跑通，里程碑 M2 达成。**那一步没有白做**——它让你真正看清了"Agent = 循环 + 工具 + 记忆"的本质。

但把它往真实生产一摆，四个窟窿就露出来了：

| W04 手搓的窟窿 | 真实后果 | 你当时怎么补 |
|---|---|---|
| ① 崩溃即失忆 | 跑到第 5 步进程被 kill，下次只能从头跑 | 把 `messages` 全放内存，没落库 |
| ② 只能串行 | 三个工具要并行得自己写线程 | 没做（M2 时串行够用） |
| ③ 人机协同 = 卡进程 | 要人批准只能塞 `input()`，跨不了进程跨不了天 | 全自动执行，不做人工确认 |
| ④ 跑完无法回放 | 想"回到第 3 步换个决策重跑"做不到 | 只能靠 `steps` 表自己查 |

> **PHP/Laravel 类比**：你写一个导 10 万条数据的脚本，跑到第 8 万条服务器重启——没断点续传就只能重来。正解是"进度落库 + 每批提交事务"。W04 你其实手搓了一个**穷人版 checkpoint**（`agent_runtime` 库的 `runs`/`steps`/`messages` 三表审计落库），LangGraph 的 `Checkpointer` 就是把那套"进度落库"变成一等公民 + 自动回放。框架不是把循环变复杂，是把你当时手动补的窟窿工程化。

## 核心结论（先给答案）

1. **框架解决的是"工程窟窿"，不是"循环本身"**：W03/W04 手搓完全对，因为你得先看见循环本质；W08 上框架，是因为接下来 W09 毕业项目、W13 可观测与上下文工程、W14 安全、W15 上线，全都需要"持久化 + 人机协同 + 可回放"的底座，自己手搓成本太高。
2. **`Checkpointer` = 进度落库**：每走一步把 state 快照存 Postgres，进程崩了按 `thread_id` 接着跑，精确到节点级（但节点重入需你保证幂等）。
3. **`interrupt()` = 把"等人"变成可持久化的暂停态**：危险操作前挂起、进程可退出、人批准后用 `Command(resume=...)` 同 `thread_id` 续跑——这是 Laravel 队列"任务挂起等人审批"的同构。
4. **状态要活在带类型的字段里，不靠解析 `messages`**：业务状态（`order`/`refunded`）由工具确定性读写，`messages` 只给 LLM 当对话笔录。这是生产级 Agent 的第一纪律。

---

## 一、概念：LangGraph 到底是什么心智模型

把 LangGraph 想成你最熟的 Laravel 那一套：

| LangGraph | Laravel / PHP 类比 | 说明 |
|---|---|---|
| **State** | 一张带类型的上下文表（TypedDict） | 不像 W04 把一切塞进 `messages` 列表，字段有类型 |
| **Node** | 一个 Controller action | 接收 state，返回对 state 的**局部更新**（patch） |
| **Edge** | 路由 + `redirect()` / `CASE WHEN` | 普通边 `A→B`；条件边按 state 决定下一步 |
| **Checkpointer** | 你 W04 的"进度落库" | 每步把 state 快照存 Postgres |
| **`interrupt()`** | 队列任务的 approval 中间件 / 重新入队 | worker 不卡 `input()`，任务持久化挂起，人点了再续 |

### 1.1 最关键的洞察：框架把"循环"显式画出来

W04 的 `while` 循环在 LangGraph 里不是隐式的，而是一条**条件边把最后一个节点指回前面**：

```
START → call_model ⇄ call_tool
              │
         (无 tool_calls) → END  (或 → approve_refund → END)
```

一眼能看出"模型会在哪一步被重新询问、何时停"。

### 1.2 Reducer：每个字段自己决定"追加还是覆盖"

State 和普通 dict 最大的不同：**每个字段都带一个 reducer（合并函数）**。Node 返回的是局部 patch，框架按字段合并：

```python
class State(TypedDict):
    messages: Annotated[list, add_messages]   # reducer=累加：旧的3条+新的1条=4条
    step:     int                             # 无 reducer=覆盖：直接变新值
```

- `add_messages` 累加 = SQL `UPDATE ... SET counter = counter + 1`（增量），或 `array_merge($old, $new)`
- 默认覆盖 = `UPDATE state SET step = 5`（整字段替换），或 `$model->fill($patch)`

> **SQL 类比**：`messages` 用 `add_messages` 是因为对话历史不能丢（像 append-only 日志）；`step`/`refunded` 用覆盖是因为它们是"当前值"（像一行状态字段）。W04 你手动 `messages.append(...)`，本质就是手写版 `add_messages`。

### 1.3 框架 2026 现状（已联网核对）

- **LangGraph**：1.0 于 2025-10-22 GA，2026 中到 v1.2.x，零破坏性变更承诺到 2.0。`StateGraph / State / Node / Edge / Checkpointer / interrupt() / Command` 稳定；1.1.0 起 `invoke(version="v2")` 返回 `GraphOutput`。**最强生产理由：durable checkpoint（崩溃续跑）**。
- **OpenAI Agents SDK**：到 v0.18（2026-07），五原语 Agents/Handoffs/Guardrails/Sessions，2026-03 起有 Temporal 崩溃续跑集成。
- **Pydantic AI V2**：类型安全最强，状态在 `RunContext[Deps]`，第一方接 Temporal/DBOS/Prefect 做持久化。

选型核心维度：**状态持久化能力**——这是 LangGraph 最强的生产理由，也是 W08 选它的原因。

## 二、动手：把 W04 退款 Agent 重写进 LangGraph

三个递进版本：**v1**（零依赖验证图结构）→ **v2**（接 Postgres 崩溃续跑）→ **v3**（真实 LLM 全链路）。代码在 `code/`，全部已本机跑通。

### 2.1 State 设计（第六小节你的设计，比我想的还好）

W04 把金额/订单号散在对话里、要用的地方重新抠。你加了一个 `order` 字段："各环节判断订单实际状态，避免从 messages 里翻找；工具查到就覆盖写回，下游直接读"。落地 schema：

```python
class State(TypedDict):
    messages: Annotated[list, add_messages]   # 对话笔录（LLM 用，累加不丢）
    order_id: str                             # 查询键（覆盖）
    order: dict                               # 订单快照 status/amount/user（覆盖，工具刷新）
    refunded: bool                            # 是否已退款（覆盖，guard 标记）
```

`amount`/`order_status` 不单独存在，统一从 `order` 里取——这正是你说的"覆盖更新、方便后续工具使用"。

### 2.2 v1：循环 + 结构化状态路由 + interrupt 续跑（MemorySaver + MockModel）

```python
# refund_graph.py（节选）：路由用 state["order"]["status"]，不是"模型调了哪个工具"
def should_continue(state):
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
        return "call_tool"                           # 还有工具要执行
    if state["order"].get("status") == "pending_refund":
        return "approve_refund"                      # 退款请求已发起 → 人工批准
    return END

# approve_refund：危险操作前挂起，进程可退出；续跑用 Command(resume=...)
def approve_refund(state):
    decision = interrupt({"ask": f"确认退款 ¥{state['order']['amount']}？"})
    if decision.get("approve"):
        ORDERS[state["order_id"]]["status"] = "refunded"
        return {"refunded": True, "order": dict(ORDERS[state["order_id"]])}
    return {"refunded": False, "order": dict(ORDERS[state["order_id"]])}
```

> **跑通实录**（v1，MockModel 验证图结构，零依赖）：
> ```
> 挂起点 next      : ('approve_refund',)
> order 快照       : {'order_id': 'ORD-1001', 'status': 'pending_refund', 'amount': 100, 'user': 'amber'}
> refunded         : False
> === 隔天批准，Command(resume=...) 续跑 ===
> 最终 next        : ()
> order 快照       : {'order_id': 'ORD-1001', 'status': 'refunded', 'amount': 100, 'user': 'amber'}
> refunded         : True
> ```
> 注意挂起时 `status=pending_refund`（说明 `request_refund` 工具**真实执行**了，不是"模型调了哪个工具"的隐式约定）。

### 2.3 v2：跨进程崩溃续跑（PostgresSaver，接本机 pgvector 容器）

`MemorySaver` 进程一退就没；`PostgresSaver` 把 checkpoint 落 Postgres，垮进程都在。关键坑：**`setup()` 内含 `CREATE INDEX CONCURRENTLY`，不能在事务块里跑**，连接必须 `autocommit=True`：

```python
# refund_graph_pg.py（节选）
def connect():
    # autocommit=True：setup() 的 CREATE INDEX CONCURRENTLY 不能在事务块中运行（psycopg3 默认关闭）
    return psycopg.connect(
        f"dbname={PG_DB} user={PG_USER} password={PG_PASSWORD} host={PG_HOST} port={PG_PORT}",
        autocommit=True,
    )

# 进程 A 跑到 interrupt 挂起 → 崩溃退出；进程 B 全新连接+全新 app+同一 thread_id 续跑
conn_b = connect(); saver_b = PostgresSaver(conn_b); app_b = g.compile(checkpointer=saver_b)
app_b.invoke(Command(resume={"approve": True}), cfg)   # 不重跑进程 A 的节点，直接进 approve_refund
```

### 2.4 v3：真实 LLM 全链路（ChatOpenAI + PostgresSaver + 真实退款端点 mock）

v3 让真实 LLM 自己决定何时 `fetch_order` / `request_refund`（真正的 ReAct 循环），`interrupt()` 等人批准，批准后调 `simulate_refund_api`（mock，带**幂等键**，不真扣钱——演示小节3 讲的"node 重入防重复退款"）：

```python
# refund_graph_real.py（节选）
def approve_refund(state):
    decision = interrupt({"ask": f"确认退款 ¥{state['order']['amount']}？"})
    if decision.get("approve"):
        # 幂等键 = order_id：崩溃续跑时同一 key 不会重复退款
        simulate_refund_api(state["order_id"], state["order"]["amount"],
                            idempotency_key=f"refund-{state['order_id']}")
        ORDERS[state["order_id"]]["status"] = "refunded"
        return {"refunded": True, "order": dict(ORDERS[state["order_id"]])}
```

> **跑通实录**（v3，真实 LLM + PostgresSaver + interrupt 人工批准 全链路）：
> ```
> 挂起点 next      : ('approve_refund',)
> order 快照       : {'order_id': 'ORD-1001', 'status': 'pending_refund', 'amount': 100, 'user': 'amber'}
> refunded         : False
> === 隔天批准，Command(resume=...) 续跑（真实退款端点被调用）===
> [调用退款API-mock] order=ORD-1001 amount=100 idempotency=refund-ORD-1001
> 最终 next        : ()
> order 快照       : {'order_id': 'ORD-1001', 'status': 'refunded', 'amount': 100, 'user': 'amber'}
> refunded         : True
> ✅ 真实 LLM + PostgresSaver 持久化 + interrupt 人工批准 全链路验证
> ```

## 三、踩坑记录（4 条，均有终端输出作证）

### 坑 1：v1 无 Key 却报 `ModuleNotFoundError: langchain_openai`

- **现象**：bat 环境直接 `python refund_graph.py`，报缺 `langchain_openai`。
- **真因**：原 `get_model()` 写成"`API_KEY` 非空就用 `ChatOpenAI`"。你用 bat 启动——bat 已加载真实 `API_KEY`，于是走了真实分支要 import `langchain_openai`，而本机 venv 没装。沙箱那次能跑只是因为沙箱 venv 恰好装了，属于巧合。
- **解法**：v1 定位是"用 MockModel 验证图结构"，不该碰 `langchain_openai`。改成**默认走 MockModel**，只有显式设 `W08_REAL=1` 且存在 `API_KEY` 才走真实。本机直接跑即零依赖。

### 坑 2：`PostgresSaver.setup()` 报 `CREATE INDEX CONCURRENTLY cannot run inside a transaction block`

- **现象**：v2 首次 `setup()` 建表到建索引那步炸 `psycopg.errors.ActiveSqlTransaction`。
- **真因**：`CREATE INDEX CONCURRENTLY` **不能在事务块里运行**，而 psycopg3 默认 `autocommit=False`（每条语句包在事务里）。
- **解法**：连接加 `autocommit=True`，`setup()` 是幂等的（`CREATE TABLE IF NOT EXISTS`）重跑干净建好。

### 坑 3：`docker exec -i gp17` 报 `No such container: gp17`

- **现象**：W07 就踩过，W08 本机复现——`docker ps` 明明显示容器 `Up`，但 `docker exec -i gp17`（用 name）解析不到。
- **真因**：本机 Docker Desktop + Windows 对容器 **name 解析一直不稳**（瞬态），与容器是否存在无关。
- **解法**：所有建库命令统一用 **CONTAINER ID 参数**（`PG_CONTAINER_ID`），不再写死 name。取 ID 用镜像过滤绕开 name：`$PG_CONTAINER_ID = (docker ps -q --filter "ancestor=pgvector/pgvector:0.8.6-pg17")`。`week-06/code/00_start_pgvector.sh` 同步改为按镜像自动探测。

### 坑 4：v3 真实 LLM 报 `400 - Field required: input.contents`

- **现象**：v3 首次调用 `model.invoke(state["messages"])` 报 400，body 里 `input.contents`。
- **真因**：`input.contents` 是 **Gemini API 的请求格式**，而 `langchain_openai` 发的是 OpenAI 标准 `messages`。根因是 bat 里的 `MODEL` 被填成了 **`qwen3.7-text-embedding-flash`（embedding 模型）**，网关把它路由到 Gemini 风格端点，OpenAI `messages` 格式它不认。
- **解法**：bat 只配一个 `MODEL` 不够——chat / embedding / rerank 是不同场景不同模型。把 `start-env-windows.bat` 升级为**多模型变量** `CHAT_MODEL` / `EMBEDDING_MODEL` / `RERANK_MODEL`，v1/v3/test_llm 读 `CHAT_MODEL`（fallback `MODEL`）。W05/W06 的 RAG 脚本不读这些变量，改 bat 不破坏历史周次。

## 四、验收清单（对照 CURRICULUM）

| 验收项 | 状态 | 证据 |
|---|---|---|
| 能画状态图 | ✅ | 见第一节图：START→call_model⇄call_tool→(END / approve_refund→END) |
| 进程被 kill 后重启能从断点继续 | ✅ | v2 实证：进程 A 崩溃退出，进程 B 全新连接+同 thread_id 从 Postgres 续跑，`refunded=True` |
| 为什么需要框架（4 个天花板） | ✅ | 第一节：崩溃即失忆/串行/人机卡进程/无法回放 |
| State/Node/Edge/Checkpointer | ✅ | 第一节概念 + 2.1/2.2 代码 |
| `interrupt()` 与 `Command` 恢复 | ✅ | v1/v3 挂起→`Command(resume)`续跑，真实输出佐证 |
| 对比 OpenAI Agents SDK / Pydantic AI | ✅ | 1.3 联网核对 2026 现状，按"状态持久化"维度选型 |

> 诚实标注：CURRICULUM 写"对比 OpenAI Agents SDK 与 Pydantic AI"——本周做了 2026 现状核对并据"状态持久化"维度选型，未把三者各写一遍完整 demo（聚焦 LangGraph 落地，对比作为选型依据已交代）。并行分支（Send API）留待多工具场景。

---

## 五、数据 / 实测结果

所有输出来自本机真实运行（Python 3.13，managed venv；真实 LLM 走 OpenAI 兼容网关 + `CHAT_MODEL`；Postgres 为本机 pgvector 容器 `w08lg` 库）。示例场景为通用"订单 → 退款"，与任何真实业务无关。

### 5.1 三版递进验证（全部本机跑通）

| 版本 | 检查点 | 持久化 | LLM | 续跑实证 | 结果 |
|---|---|---|---|---|---|
| v1 | MemorySaver + MockModel | 进程内 | 否（Mock） | 同进程 `Command(resume)` | 挂起→续跑 `refunded=True` ✅ |
| v2 | PostgresSaver | Postgres | 否（Mock） | **跨进程**崩溃续跑 | 进程B 不重跑进程A 节点，直接续 ✅ |
| v3 | PostgresSaver | Postgres | 真实 ChatOpenAI | 跨进程 + 真实退款端点 | 真实 LLM 跑 ReAct→批准→退款 ✅ |

### 5.2 v2 时间旅行：state history（正序，order.status 演变）

`get_state_history` 默认"新→旧"，反转成正序后能看到状态机如何一步步推进：

| 步 | next | order.status | 含义 |
|---|---|---|---|
| 0 | `__start__` | `None` | 初始 `order={}` |
| 1 | `call_model` | `None` | 模型决定 `fetch_order`，还没查 |
| 2 | `call_tool` | `paid` | `fetch_order` 执行，order 被填充 |
| 3 | `call_model` | `paid` | 模型决定 `request_refund` |
| 4 | `call_tool` | `pending_refund` | `request_refund` 执行翻状态 |
| 5 | `call_model` | `pending_refund` | 模型说"请人批准"，无 tool_calls |
| 6 | `approve_refund`(挂起) | `pending_refund` | 危险操作前 `interrupt()` 挂起 |
| 7 | `()`（终态） | `refunded` | 人批准后真退款 |

> `None` 不是 bug：`order` 初始 `{}`，`call_model` 只动 `messages` 不碰 `order`；只有 `call_tool` 执行 `fetch_order` 才把 `order` 覆盖成 `{status:paid,...}`。类比 Laravel：`$order = new Order()` 之后、查到 DB 之前属性就是 `null`。

## 六、这周的取舍

### 做了什么

- 阶段1 六小节全讲透（框架必要性 / 心智模型 / reducer / Checkpointer / interrupt / 条件边），每节停下等反馈、用 PHP/Laravel/SQL 类比打底。
- 阶段2 三版递进实操全跑通：v1 零依赖验证图结构 → v2 接 Postgres 跨进程崩溃续跑 + 时间旅行 → v3 真实 LLM + 持久化 + 人工批准全链路。
- 结构化状态路由落地（你第六小节加的 `order` 字段）：`request_refund` 真实执行翻状态、下游 `state["order"]["status"]` 路由，而非"模型调了哪个工具"的隐式约定。
- 真实退款端点演示幂等键（`refund-<order_id>`），呼应小节3 "node 重入防重复退款"。

### 放弃了什么 / 留到后面

- **并行分支（Send API）**：W04 三工具串行未并行，W08 也没做——课程范围外，且单退款链路并行收益有限，留待多工具场景。
- **真实退款网关**：用 `simulate_refund_api`（mock，带幂等键）演示"危险操作需幂等 + 人工批准"，不真扣钱；生产换成你的退款 HTTP 端点即可。
- **OpenAI Agents SDK / Pydantic AI 完整 demo**：只做 2026 现状核对与"状态持久化"维度选型，未各写一遍（聚焦 LangGraph 落地）。

### 一个方法论提醒

我们联网核对了 2026 框架现状，确认 W08 内容未过时（LangGraph 仍是生产级 checkpoint 最强选项）。但**选型要讲清理由、不能只报结论**：本课选 LangGraph 的核心依据就是"durable checkpoint（崩溃续跑）"，不是它"更流行"。同样，坑 1/4 都暴露了"环境变量配置"这个看似不起眼、实则能卡死整条链路的环节——多模型场景务必拆 `CHAT_MODEL`/`EMBEDDING_MODEL`，别再踩"把 embedding 模型当 chat 模型发出去"的坑。

---

## 下一篇

W09 是**毕业项目开工周**：财报与可转债分析 Agent 的数据地基（A 股年报场景）。Python 侧做主体——建核心数据表、用 Migration 反向生成字段字典、`classify`/`extract` 抽取工具、**L1-L2 归一化**（含近似字段陷阱的否定词保护）、`query_indicator`；Laravel 侧只做调用端——HTTP 客户端调我写的 FastAPI 服务、SSE 流式转发、队列跑长任务、一个最简 Vue 查询页，**不写任何 Agent 逻辑**。W06 埋的雷也在这周正面拆：向量 + BM25 + 重排三道防线都分不开「扣非净利润」和「归母净利润」这对语义相似块，唯一解是字段级归一化。

> 本周尾巴：并行分支（Send API，多工具并发）；真实退款网关替换 mock（毕业项目需时）。

## 附录：学习对话实录

- [DIALOGUE.md](DIALOGUE.md) —— 提炼版：按主题归类，含「给 AI 的复现指令」，可直接复制给任意 AI 带你走一遍
- [DIALOGUE-QA.md](DIALOGUE-QA.md) —— 逐轮一问一答底稿：保留每一次提问、回答与终端输出

## 附录：延伸阅读

- [LangGraph 官方文档](https://langchain-ai.github.io/langgraph/) —— StateGraph / Checkpointer / interrupt / Command 权威参考
- [LangGraph Postgres 检查点](https://langchain-ai.github.io/langgraph/cloud/low_level/persistence/) —— PostgresSaver 建表与 autocommit 注意点
- [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/) —— 五原语 Agents/Handoffs/Guardrails/Sessions
- [Pydantic AI](https://ai.pydantic.dev/) —— 类型安全的 Agent 框架，状态在 `RunContext[Deps]`
- 2026 实践：LangGraph 最强生产理由 = durable checkpoint（崩溃续跑）；选框架核心维度 = 状态持久化能力

---

## 发布检查

- [x] 代码实际跑过，输出贴进正文（v1/v2/v3 三版输出、v2 时间旅行 history）
- [x] 至少 2 条真实踩坑（实际 4 条：langchain_openai 误依赖 / CONCURRENTLY 事务块 / gp17 name 解析 / input.contents 模型错配）
- [x] 有数字/表格（三版递进验证表、v2 state history 演变表）
- [x] 有 PHP / SQL 类比（进度落库 vs 审计表 / reducer vs UPDATE 增量 / interrupt vs 队列挂起 / 条件边 vs redirect）
- [x] 标题不标题党，但要有信息量
- [x] 结尾有引导（下一篇 / 仓库链接）
- [x] 本周写了 `DIALOGUE.md`（对话实录 + 可复现的 AI 引导脚本）
- [x] 本周写了 `DIALOGUE-QA.md`（逐轮问答底稿，只收技术相关）
- [x] 并行分支与真实网关留待后续，均已诚实披露，未假装完成

### 提交前必做：红线扫描（含全部文件类型）

```bash
grep -rlE "dd-admin|dd-api|ddLife|hope-garden|病历|CatchAdmin|dd_permissions" . \
  --include="*.md" --include="*.py" --include="*.json" --include="*.bat" --include="*.sh"
grep -rn "sk-" . --include="*.json" --include="*.py" --include="*.md"
```

- [x] 红线扫描覆盖了 `.md` `.py` `.json` `.bat` `.sh`
- [x] 无 `sk-` 开头的 Key 出现在任何待提交文件里
- [x] `.bat` 是 CRLF，其余文件是 LF
