# W08 · 逐轮一问一答底稿（DIALOGUE-QA）

> 这是 [DIALOGUE.md](DIALOGUE.md) 的逐轮原始底稿。每一次提问、回答与终端输出都在这里，未做归纳压缩。

---

**轮 1 · 用户**：开始 W08 课程。

**AI**：进入 W08 阶段1 引导学习。先联网核对 2026 框架现状（LangGraph 1.0 GA 至 v1.2.x 稳定、OpenAI Agents SDK v0.18、Pydantic AI V2），确认 W08 内容未过时。W08 主题=LangGraph：把循环变成工程。进度标记进行中，开始第一小节。

---

**轮 2 · 用户**：内容呢？

**AI**：读 CURRICULUM/W07 进度/周工作流，确认 W08 当前周、W07 已达成 M3。第一小节讲"为什么需要框架"——手搓循环四个天花板：崩溃即失忆 / 只能串行 / 人机协同卡进程 / 跑完无法回放。配对照图（手搓 while vs LangGraph 原语）。

---

**轮 3 · 用户**：把每个阶段的进度和阶段结果都存储本地或者数据库，崩溃重启时判断本地进度，继续后续流程。

**AI**：第一小节确认通过。这正是 Checkpointer 的全部思想——你 W04 的审计落库三表=穷人版 checkpointer，W08 把"手动判断进度"交给框架（声明 `compile(checkpointer=...)`，按 `thread_id` 自动恢复，精确到节点内部）。

---

**轮 4 · 用户**：message 4条 step=5。

**AI**：第二小节确认通过。`messages` 用 `add_messages` 累加（3+1=4），`step` 默认覆盖（=5）。reducer 本质="每个字段自己决定追加还是替换"。

---

**轮 5 · 用户**：1.不会重跑 node_a，会从 node_b 接着跑。2：因为 checkpoint 记录了已完成节点。后续提问，不用先给提示，等回答完后再进行解释，不然问题的意义就少了很多。

**AI**：第三小节过关。补细节：崩溃发生在 node_b 中途 → checkpoint 只记 node_a 完成、node_b 未写完成标记 → 续跑时 node_a 不重跑、node_b 从头再跑（不是接着崩溃那行）。引出 W04 幂等纪律：框架负责"何时续"，你负责"续了不出错"。
> 附：用户在此给出教学反馈"先不给提示、等答完再解释"，已固化为课程引导纪律（后续小节照此执行）。

---

**轮 6 · 用户**：对象是 command（resume=value）生成的state，合并了当前提供的数据和之前提交的数据，以及一些节点信息，让节点从挂起点往下走，除了这个对象外，还需要传 thread_id 信息，明确这是哪一次调用。

**AI**：第四小节过关。纠正措辞：`Command(resume=value)` 是控制对象，只携带"恢复时该喂给 `interrupt()` 的返回值"，合并由引擎用 `thread_id` 做；`thread_id` 是 config 不是 Command 字段。一句话：`Command(resume=...)` 说"继续"，`cfg` 说"继续哪一次"。

---

**轮 7 · 用户**：对应关系，should_continue 返回的需要是通过 add_node 注册过的节点，如果返回值错误，应该会执行 add_conditional_edges 的第一个参数 call_model；如果两个参数都错了，是会抛出异常中断还是继续 g.add_edge("call_tool", "call_model") 呢？

**AI**：前半句对（返回值须是已注册节点名/END）。纠正：误以为"拼错会 fallback 到源节点 call_model"。`add_conditional_edges(source, path)` 的 `source` 是**起点**不是备选目标；拼错返回未注册名会直接 `ValueError` 中断，不会静默 fallback 到 source。类比 `redirect()->route('call_too')` 未定义直接炸。

---

**轮 8 · 用户**：抛出异常中断了，因为 call_too 不是合法节点。这里理解错 add_conditional_edges 和 add_edges 第一个参数的意义了，这里第一个参数是源节点，而不是备选参数。因为直接中断了，没有走 call_tool 所以后续的 g.add_edge("call_tool", "call_model") call_model 也就不会继续执行了。

**AI**：第五小节收口全对：返回未注册名→抛异常中断；第一个参数是源节点（起点）非备选；路由阶段就崩，根本到不了 call_tool，后续边不触发。给第六小节蓝图（W04 退款 Agent 的 LangGraph 重写）。

---

**轮 9 · 用户**：在原基础上加一个订单状态 order_status int 覆盖 或者订单对象 order object 覆盖，用于各个环节判断订单实际状态，避免从 messages 里面去翻找订单数据，通过 order_id 查询到数据后对上述字段进行覆盖更新，后续工具更改了订单状态 也需要覆盖更新对应字段。方便后续工具使用。

**AI**：第六小节收口，且比我想的还好。落地 schema：`messages`(累加) / `order_id`(覆盖) / `order`(覆盖，工具刷新 status/amount/user) / `refunded`(覆盖)。`amount`/`order_status` 收进 `order` 对象，下游直接 `state["order"]["status"]` 读，不解析 messages。进阶段2 实操。

---

**轮 10 · 用户**：v1 执行报错（贴完整 traceback）
`PS D:\...\w08-scratch> python refund_graph.py`
`ModuleNotFoundError: No module named 'langchain_openai'`（在 get_model 第 71 行）

**AI**：根因 `get_model()` 原把 `from langchain_openai import ChatOpenAI` 写在无条件位置，且判定"`API_KEY` 非空就用 ChatOpenAI"。你用 bat 启动（已设真实 API_KEY）→ 走真实分支要此包，本机 venv 没装。改：v1 默认 MockModel，仅 `W08_REAL=1` 才真实。沙箱重跑验证修复（Exit Code 0）。

---

**轮 11 · 用户**：v1 跑通（贴输出）
```
=== 第1次 invoke（跑到 interrupt 挂起）===
[MockModel] 检测到 API_KEY 但未设 W08_REAL=1，默认用 MockModel 验证图结构   （×3）
挂起点 next      : ('approve_refund',)
order 快照       : {'order_id': 'ORD-1001', 'status': 'pending_refund', 'amount': 100, 'user': 'amber'}
refunded         : False
=== 隔天批准，Command(resume=...) 续跑 ===
最终 next        : ()
order 快照       : {'order_id': 'ORD-1001', 'status': 'refunded', 'amount': 100, 'user': 'amber'}
refunded         : True
✅ 图跑通：循环(call_model↔call_tool) + 结构化状态路由 + interrupt 挂起 + 同 thread_id 续跑均验证
```
**AI**：v1 本机跑通确认。顺手把 MockModel 提示去重为只打一次。

---

**轮 12 · 用户**：`docker exec -i gp17 psql -U amber -d template1 -c "CREATE DATABASE w08lg OWNER amber;"` 这句报 `Error response from daemon: No such container: gp17`；用 name 会报错。

**AI**：你直接踩到 W07 记过的坑——name 解析不稳。把所有建库命令统一改 **CONTAINER ID 参数 `PG_CONTAINER_ID`**，不再写死 name。`week-06/code/00_start_pgvector.sh` 两份同步改（自动探测用镜像过滤 `ancestor=`）。

---

**轮 13 · 用户**：`PS> pip install "langgraph-checkpoint-postgres[psycopg]"`
`Defaulting to user installation because normal site-packages is not writeable`
`ERROR: Could not find a version that satisfies the requirement ... No matching distribution found`

**AI**：根因你这窗口 `pip` 是**系统 python** 的（venv 的 pip 可写不会 default to user）；系统 pip 连 pypi 被 TLS 中断所以拉不到包。沙箱与本机共享 managed venv，由沙箱装：`python -m pip install "langgraph-checkpoint-postgres[psycopg]"`（extra `[psycopg]` 名不存在但 psycopg 已为核心依赖，照装），`PostgresSaver` 导入成功。本机即用、不用再装。

---

**轮 14 · 用户**：`PS> python refund_graph_pg.py`
`psycopg.errors.ActiveSqlTransaction: CREATE INDEX CONCURRENTLY cannot run inside a transaction block`（在 saver_a.setup()）

**AI**：根因 `CREATE INDEX CONCURRENTLY` 不能在事务块里跑，psycopg3 默认 `autocommit=False`。修 `connect()` 加 `autocommit=True`；`setup()` 幂等重跑干净建表。同步改注释里的 name 取法→ancestor。

---

**轮 15 · 用户**：v2 跑通（贴输出）
```
[MockModel] 检测到 API_KEY 但未设 W08_REAL=1，默认用 MockModel 验证图结构
进程A 挂起 next: ('approve_refund',)
→ 进程 A 崩溃退出（checkpoint 已落 Postgres）
进程B 从 Postgres 读 checkpoint 续跑...
最终 order: {...'status': 'refunded'...} refunded: True
=== 时间旅行：state history（正序：__start__ → 终态）===
步0: next=()        order.status=refunded
步1: next=('approve_refund',) order.status=pending_refund
步2: next=('call_model',) order.status=pending_refund
步3: next=('call_tool',)  order.status=paid
步4: next=('call_model',) order.status=paid
步5: next=('call_tool',)  order.status=None
步6: next=('call_model',) order.status=None
步7: next=('__start__',)  order.status=None
```
**AI**：v2 实证成功——进程 B 全新连接续跑、最终 refunded=True，证明持久化在数据库。时间旅行打印标题原为「旧→新」已改正序；`None` 因 `order` 初始 `{}`、`call_model` 不动 order，`call_tool` 执行 fetch_order 才填充（类比 `$order=new Order()` 查库前属性 null）。改 v2 打印为正序。

---

**轮 16 · 用户**：v3 报错（贴完整 traceback）
`PS> python refund_graph_real.py`
`langchain_openai...OpenAIInvalidRequestError: Error code: 400 - {'code': 'InvalidParameter', 'message': '<400> InternalError.Algo.InvalidParameter: Field required: input.contents', ...}`（在 call_model `model.invoke(state["messages"])`）

**AI**：不在图逻辑，在 LLM 调用层。`input.contents` 是 Gemini 请求格式，langchain_openai 发 OpenAI `messages`——网关把当前 MODEL 路由到 Gemini 端点。写隔离测试 `test_llm.py` 把图摘掉，只验证 ChatOpenAI 基础调用，打印实际 MODEL/BASE_URL。

---

**轮 17 · 用户**：应该是用的阿里的 qwen3.7-text-embedding-flash 模型 而不是 llm 模型导致的，这里可能需要多个 MOdel name 配置，用于区分模型场景，优化一下 bat 文件。

**AI**：根因确认——bat 只配一个 `MODEL`，被填成 embedding 模型，v3 当 chat 模型发出去。优化 `start-env-windows.bat` 为多模型变量：`CHAT_MODEL`(对话/工具) / `EMBEDDING_MODEL`(向量化) / `RERANK_MODEL`(重排) / `MODEL=%CHAT_MODEL%`(兼容别名)。v1/v3/test_llm 改读 `CHAT_MODEL`（fallback `MODEL`）。沙箱验证三份脚本 import+图编译全 OK。W05/W06 RAG 脚本不读这些变量，不破坏历史周次。长期记忆更新 bat 多模型约定。

---

**轮 18 · 用户**：v3 跑通（贴输出）
```
=== 第1次 invoke（真实 LLM，跑到 interrupt 挂起）===
挂起点 next      : ('approve_refund',)
order 快照       : {'order_id': 'ORD-1001', 'status': 'pending_refund', 'amount': 100, 'user': 'amber'}
refunded         : False
=== 隔天批准，Command(resume=...) 续跑（真实退款端点被调用）===
[调用退款API-mock] order=ORD-1001 amount=100 idempotency=refund-ORD-1001
最终 next        : ()
order 快照       : {'order_id': 'ORD-1001', 'status': 'refunded', 'amount': 100, 'user': 'amber'}
refunded         : True
✅ 真实 LLM + PostgresSaver 持久化 + interrupt 人工批准 全链路验证
```
**AI**：三版全跑通。v3 真实 LLM 跑 ReAct + PostgresSaver 持久化 + interrupt 人工批准 + 真实退款端点（mock 带幂等键）全链路验证。进入阶段4 收尾（course-week-finalize 八步流水线）。

---

## 附：本轮次未收录的元话题

按课程约定，**制定规则 / 调整课表 / 产出管理**类元话题不进 DIALOGUE-QA（已在课程管理文档统一处理）。本文件只保留与 W08 技术内容直接相关的问答。
教学反馈"先不给提示、等答完再解释"已固化到课程引导纪律（见 DIALOGUE.md 第四节方法论），不单列轮次。
