# W08 · 学习对话实录（可复现版）

> 这不是正文。正文在 [README.md](README.md)。
>
> 这份文件是**这周学习过程的原始记录**，外加一套**引导脚本**：把它丢给任意一个 AI，
> 说一句「按这个文件带我学 W08」，它就能用同样的方式带你走一遍。
>
> **想要逐轮一问一答的完整底稿**：[DIALOGUE-QA.md](DIALOGUE-QA.md)
> （共 18 轮，覆盖六小节概念引导、三版实操、4 个真实踩坑；
> 每一次提问、回答、终端输出都在里面，未做归纳压缩）
>
> 之所以留这份东西，是因为我觉得**过程比结论值钱**。正文告诉你 LangGraph 是什么；
> 这份文件告诉你一个真实的人是怎么一步步把它搞懂、又怎么被真实报错"教育"的——包括我猜错的地方、
> 以及那些只有亲手跑一遍才会冒出来的问题。

---

## 一、怎么用这份文件

### 如果你是人类读者

1. 通读第二部分「对话实录」，当故事看就行——里面所有输出、错误和判断都是原始的。
2. 想让 AI 带你学一遍：把**第三部分「给 AI 的复现指令」**整段复制给任意 AI，然后说「开始」。
3. 想自己当老师教别人：同样用第三部分，把里面的实验换成你的场景。

### 如果你是 AI

**读到这份文件时，请这样理解你的角色：**

你不是"把 W08 的知识讲一遍"，你是**引导一个人亲手把它跑出来**。

- 一次只讲一小节，讲完必须停下来等对方的终端输出
- 每个知识点后面跟一条**能立刻跑出结果的命令**；没有命令的知识点，说明你还没想清楚怎么教
- 对方贴回输出后，**照着他的真实数字讲**，不要讲你预先准备的那套
- 宁可说"这个我不知道，我们一起测一下"，也不要编一个看起来合理的答案
- **提问先不给提示**：对方没答之前，不要先写"答出 XX 就过关"或铺垫答案——等他答完再解释，问题的意义才在

完整的行为准则见第三部分。

---

## 二、对话实录

> 以下按主题还原。为可读性做了压缩，但**技术讨论、错误和判断都是原始的**。

### 主题 1 · 阶段1 六小节引导（对方抓住了核心）

- **第1节 为什么需要框架**：我列手搓循环的四个天花板（崩溃即失忆/串行/人机卡进程/无法回放）。对方立刻给出现代解——"把每个阶段的进度和阶段结果都存储本地或数据库，崩溃重启时判断本地进度继续"。这正是 Checkpointer 的全部思想。
- **第2节 心智模型 + reducer**：讲 State/Node/Edge/Checkpointer 类比 Laravel 路由；reducer 累加 vs 覆盖。问 `messages`(3条)+`step` 的 patch 怎么合并，对方答"message 4条 step=5"，全对。
- **第3节 Checkpointer 崩溃续跑**：讲节点级 checkpoint。问进程 A 崩溃在 node_b 中途、进程 B 同 thread_id 续跑，对方答"不会重跑 node_a，从 node_b 接着"。**关键补充**：崩溃在 node_b 中途→ checkpoint 只记 node_a 完成，续跑时 node_b 从头再跑一遍（不是接着崩溃那行），引出 W04"幂等"纪律。对方还给了教学反馈：**后续提问先不给提示，等答完再解释**。
- **第4节 interrupt + Command**：讲危险操作人工确认。对方答"传 Command(resume=value) + 同 thread_id"。**纠正措辞**：`Command(resume=...)` 是控制对象只带恢复载荷，合并由引擎用 thread_id 做；thread_id 是 config 不是 Command 的字段。
- **第5节 条件边**：讲 `should_continue` 返回值是已注册节点名。对方一度以为"拼错会 fallback 到源节点 call_model"——纠正：第一个参数是**源节点**，不是备选；拼错直接抛 `ValueError`，不会静默 fallback。对方最终答全对。
- **第6节 State 设计**：让对方从零设计退款 State。对方加 `order_status`/`order` 字段"避免从 messages 翻找、工具覆盖更新下游直接用"——比我想的还好。落地成 `messages`/`order_id`/`order`/`refunded` 四字段。

### 主题 2 · 阶段2 三版实操（真实坑驱动）

- **v1 langchain_openai 误依赖**：bat 环境跑 `refund_graph.py` 报 `ModuleNotFoundError: langchain_openai`。根因原 `get_model()` 把 MockModel 分支写成"`API_KEY` 非空就用 ChatOpenAI"，bat 已设真实 Key 就走了真实分支。修：v1 默认 MockModel，仅 `W08_REAL=1` 才真实。本机重跑通过。
- **容器 ID 改造（坑3）**：建库 `docker exec -i gp17` 报 `No such container: gp17`，对方 `docker ps` 明明显示容器在。确认是 Docker name 解析不稳，统一改成 **CONTAINER ID 参数**（`PG_CONTAINER_ID`），取 ID 用镜像过滤绕开 name；`week-06/code/00_start_pgvector.sh` 同步改。
- **pip 装包走系统 python（坑2 前置）**：`pip install langgraph-checkpoint-postgres` 报 `No matching distribution`——对方窗口的 `pip` 是系统 python 的（SSL 被 TLS 中断连不上 pypi）。改由沙箱 managed venv 装，本机共享即用。
- **CONCURRENTLY 事务块（坑2）**：v2 `setup()` 报 `CREATE INDEX CONCURRENTLY cannot run inside a transaction block`。修：连接 `autocommit=True`。重跑 v2 跨进程续跑实证通过 + 时间旅行 history。
- **input.contents 模型错配（坑4）**：v3 真实 LLM 报 `400 Field required: input.contents`（`contents` 是 Gemini 格式，langchain_openai 发 OpenAI `messages`）。根因 bat 的 `MODEL` 被填成 `qwen3.7-text-embedding-flash`（embedding 模型）。修：bat 拆多模型变量 `CHAT_MODEL`/`EMBEDDING_MODEL`，v1/v3/test_llm 读 `CHAT_MODEL`。v3 全链路跑通（真实 LLM + PostgresSaver + interrupt + 真实退款端点 mock 带幂等键）。

---

## 三、给 AI 的复现指令（可直接复制给任意 AI）

```
你现在是 W08「LangGraph：把循环变成工程」的引导老师。目标：带一个 PHP/Laravel/SQL 背景的开发者
亲手把 W04 的零框架退款 Agent 重写进 LangGraph，并跑通「循环 + 持久化 + 人机确认」。
风格：一次只讲一小节，讲完停下等反馈；新概念先用 PHP/SQL 类比；给的命令必须能立刻跑出结果；
对方贴回输出后照真实数字讲，不背稿；先提问、对方答完再解释（不要先给提示/答案）。
绝不自动 commit/push。

分阶段：
【阶段1 引导学习】逐节讲，每节结束停下等反馈（不要一次倾倒）：
  第1节 框架必要性：手搓循环的四个天花板（崩溃失忆/串行/人机卡进程/无法回放）；
        PHP 类比：进度落库 vs 审计表。问：要做到崩了从第5步续跑，直觉怎么实现？
  第2节 心智模型：State=带类型上下文表、Node=Controller、Edge=redirect、Checkpointer=进度落库；
        reducer 累加(add_messages) vs 覆盖(默认)。问：messages(3条)+step 的 patch 合并后几条、step几？
  第3节 Checkpointer：节点级 checkpoint；崩溃在 node 中途 → 续跑 node 从头再跑（引出幂等）。
        问：进程A崩在node_b中途、进程B同thread_id续跑，node_a 重跑吗？为什么？
  第4节 interrupt+Command：危险操作人工确认；resume 载荷 + thread_id(config)。
        问：被挂起的同一次运行怎么续？对象和必要条件分别是什么？
  第5节 条件边：should_continue 返回值=已注册节点名；源节点≠备选，拼错直接 ValueError。
        问：返回未注册名会发生什么？为什么不会 fallback 到源节点？
  第6节 State 设计：让对方从零设计退款 State（业务状态活字段，不解析 messages）。

【阶段2 实操】三版递进（w08-scratch）：
  v1: refund_graph.py（MemorySaver+MockModel，零依赖验证图结构）→ 本机跑通
  v2: refund_graph_pg.py（PostgresSaver 跨进程崩溃续跑+时间旅行，接本机 pgvector 容器 w08lg）
  v3: refund_graph_real.py（真实 ChatOpenAI+PostgresSaver+interrupt+真实退款端点 mock 幂等）
  沙箱无 Key 先跑 test_llm 验证；其他让对方本机跑（PS + bat 加载 + PG_CONTAINER_ID 取容器 ID）。
  真实报错必须贴终端输出：langchain_openai 误依赖 / CONCURRENTLY 事务块 / gp17 name 解析 /
        input.contents 模型错配（bat 拆 CHAT_MODEL/EMBEDDING_MODEL）。

【阶段3 反馈】对方贴回后：一起看 v1 挂起/续跑、v2 跨进程续跑+history、v3 真实链路。
        重点：确认"进程B 不重跑进程A 节点、直接进 approve_refund"=持久化在数据库。

【阶段4 收尾】按 course-week-finalize 八步流水线：复制代码到 week-08/code/ + 写 README（十节）
        + DIALOGUE + DIALOGUE-QA + learning-log + 更新 PROGRESS + 红线扫描。不自动 commit/push。
        公开仓库不出现内部项目词/本机绝对路径/真实 Key；示例用通用订单-退款场景，不挂钩业务。

红线：公开仓库不出现内部项目词/本机绝对路径/真实 Key；不替对方"假装学会"；没跑通就说没跑通；
      多模型场景拆 CHAT_MODEL/EMBEDDING_MODEL（别把 embedding 模型当 chat 发出去）。
```

---

## 四、方法论总结（这一周沉淀下来的）

1. **先预测再让对方验证**：第1节对方直接说出"进度存本地/数据库，崩溃判断进度继续"——这正是 Checkpointer 的全部思想。引导的价值在于"让他自己推导出框架的解法"，不是我提前背稿。
2. **提问先不给提示**：对方明确"先不给提示、等答完再解释，不然问题意义少很多"。这纠正了我习惯性在问题后写"答出 XX 就过关"的写法——铺垫答案会剥夺他思考的空间。
3. **"源节点≠备选目标"是个高频误解**：第5节对方以为条件边拼错会 fallback 到源节点，纠正后他理解了"第一个参数是起点、返回值是已注册节点名、拼错直接报错"。框架拼错当场炸、手搓拼错静默死循环——这正是工程化的价值。
4. **配置错误能卡死整条链路**：坑1（langchain_openai 误依赖）和坑4（embedding 模型当 chat 发出去）都源于"环境变量怎么配"。多模型场景必须拆 `CHAT_MODEL`/`EMBEDDING_MODEL`，这是 W08 最值钱的一个工程纪律。
5. **踩坑必须有终端输出作证**：`No such container: gp17`、`CREATE INDEX CONCURRENTLY cannot run inside a transaction block`、`input.contents` 都是真实报错驱动的定位，不是脑补——每个坑都贴了终端输出。
6. **执行规范跨课程固化**：PS + bat 加载 + 其他配置手写 + 不提供 .sh；依赖统一走 managed venv（本机系统 python 连 pypi 被 TLS 中断，装包归沙箱）。W09–W15 复用。容器引用统一用 CONTAINER ID（绕开 name 解析坑）。
