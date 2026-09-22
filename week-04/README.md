# W04 · 把那个能跑的循环，加固成"生产可用"的 Agent

> Agent 开发实战 15 周 · 第 4 周 · 实际投入约 10 小时（含库核对与压缩 400 排错）
>
> 一句话钩子：**W03 你手搓了一个会调工具的循环，但它跑久了会失忆、烧钱、还停不下来。这一周，我们给这个循环装上"刹车、保险丝和行车记录仪"。**

**另有一份 [学习对话实录](DIALOGUE.md)**：这周的完整学习过程，包括猜错的地方、被质疑后改掉的写法，以及一套可以直接丢给 AI 的**引导脚本**——照着它能用同样的方式带你走一遍。

## 开篇：这周要解决什么问题

W03 末尾我埋了个伏笔：模型可能反复调同一个注定失败的参数，烧 token 到天荒地老。但那只是冰山一角。一个"裸奔"的 Agent 循环上了真实场景，会撞上四类问题：

1. **失忆**：`messages` 每轮变长，跑 10 轮工具调用后，上下文塞满几万 token，最早的约束被埋没，甚至撑爆窗口（W01 讲过的"失忆"回来了）。
2. **烧钱**：每轮都把历史全重发一遍，token 费用随轮数线性膨胀。
3. **停不下来**：模型一旦陷入某种循环（比如执着于重试一个失败的接口），没有外力会自己停。
4. **黑盒**：跑完一趟，你不知道它到底调了哪些工具、为什么这么走、花了多少钱——没法审计，没法复盘。

这一周**不引入任何新框架**（M2 里程碑就是要亲手写循环、框架不是黑盒），而是把 W03 那个循环**工程化加固**：显式结构化 ReAct、加记忆三层、上防护四件套、把每一步落库。

## 核心结论（先给答案）

1. **ReAct 不是新框架，是一种"提示 + 循环"的范式**。W03 我们已经在跑 ReAct，本周只是把 Thought / Action / Observation 从"混在 content 里"变成"结构化记录"。
2. **记忆分三层**：历史全留（但未必每轮重发）/ 摘要压缩（压过程与推理）/ 外部存储（压事实数据，用时再取）。**会变质的信息进摘要，不会变质的事实进外部存储**——这是分水岭。
3. **防护四件套**：步骤上限（兜底墙）/ 超时（卡死不拖垮全局）/ token 预算（软触发摘要 + 硬熔断）/ 重复调用检测（防死循环）。②③ 是节流阀，① 是最后的墙，④ 是精准拦截。
4. **工具调用落库 = 审计 + 外部存储一举两得**。一套 `runs` + `steps` + `messages` 表，既能回放每一步，又把大块结果移出对话上下文。
5. **真实 LLM 比你以为的更"聪明"**：本以为要教它别死循环，结果它遇到工具故障会自己降级绕开——防护④ 在真实模式这次**没触发**，因为模型自愈了。（这是本周最有意思的发现，见第三节坑 2。）

---

## 一、ReAct：把 W03 的循环正式命名

先给结论：**W03 我们已经在跑 ReAct 了，只是没说破。**

W03 那个 while 循环的本质就是：

```
LLM 返回 tool_calls → 我们执行 → 把结果填回 messages → 再请求 LLM → 重复
```

这就是 **Action → Observation → Action**。ReAct 论文（2022, Google）把它补全成三段：

| ReAct 阶段 | 含义 | 在 W03 循环里的对应 |
|---|---|---|
| **Thought** | 模型"想"下一步该干嘛（返回文本 reasoning） | 已在 assistant message 的 `content` 里，只是没单独拎出来 |
| **Action** | 模型决定调用哪个工具、传什么参 | `tool_calls`（`function.name` + `arguments`） |
| **Observation** | 工具执行结果 | 我们 append 的 `tool` 角色消息 |

> **PHP/Laravel 类比**：ReAct 就像你在 Controller 里写一个"多步业务编排"。比如退款流程——你先想"这单要先查订单状态"（Thought），调 `OrderService::getStatus()`（Action），拿到 `status=shipped`（Observation），再想"已发货要走物流拦截"（Thought），调下一个 Service（Action）……每一步先推理再动作，不是写死的 `if-else` 直线。

**本周升级点**：之前 Thought 顺带在 `content` 里，现在把它**显式结构化**——每一轮把 Thought / Action / Observation 作为一个完整记录存下来（落库的 `steps` 表里 `span_type` 区分 `llm` 和 `tool`）。这既是 ReAct 的规范做法，也直接服务于后面"工具调用落库可审计"的验收。

⚠️ **一个容易混淆的点**：ReAct 不是新框架，是一种范式。模型本身不需要特殊训练，靠 system prompt 引导它"先想后做、把思考写出来"即可。所以 W04 是"显性化 + 加防护"，不是从零再来。

---

## 二、动手：记忆三层 + 防护四件套 + 落库

### 2.1 记忆三层：为什么循环跑久了会"失忆"

W03 的循环每转一圈，`messages` 就变长（Thought + Action + Observation 全 append）。跑 10 轮后上下文塞满，然后：① 撑爆窗口 ② 每轮更贵 ③ 噪声淹没信号。

| 层 | 存什么 | 类比（你的系统） | W04 怎么落地 |
|---|---|---|---|
| **① 历史** | 完整原始 messages，append-only | `audit_log` 流水表，原始不动 | 全量落 `messages` 表，但**不一定每轮都塞进请求** |
| **② 摘要压缩** | 老轮次压成一段总结 | 数据库"月报汇总 / 物化视图"——流水太大定时 rollup | 只留最近 K 个工具交互块原文，更早的调 LLM（或 mock）压成 summary 放开头 |
| **③ 外部存储** | 大块事实数据，用时再取 | 不把数据塞进 session，存 MySQL `WHERE id=?` 查 | 工具结果落 `steps.observation`，对话里只留引用 |

**分水岭（最容易混）**：② 摘要压的是"过程与推理"（"用户先问退款，我查订单发现已签收，于是退款"——压成叙事不会出事）；③ 外部存储存的是"事实数据"（订单金额、物流单号——压了就可能改值变脏数据）。**会变质的信息进摘要，不会变质的事实进外部存储。**

### 2.2 防护四件套：让循环"跑不死、烧不穷"

| 防护 | 防什么 | 你的类比 | W04 实现 |
|---|---|---|---|
| **① 步骤上限** | 无限循环烧钱 | Laravel 队列 job 的 `tries` / while 的 fail-safe 计数器 | `MAX_STEPS=12`，超了直接终止报"已达步数上限" |
| **② 超时** | 单个工具卡死拖垮全局 | Guzzle 的 `timeout` | 每个工具包一层 `ThreadPoolExecutor` 超时；整体 `RUN_TIMEOUT` |
| **③ token 预算** | 上下文膨胀费用爆炸 | 接口限流 / 单请求最大开销 | 累计 token 接近 `TOKEN_BUDGET` 触发摘要压缩，超 `TOKEN_HARD` 熔断 |
| **④ 重复调用检测** | 模型反复调同一工具打转 | Stripe `Idempotency-Key` / Laravel 队列 `unique` / 熔断器 | 连续 N 次出现"同工具 + 同参数"直接拦下 |

> 关键定义（amber 定的）：重复检测的 key = **工具名 + 参数**，只按工具名会误杀"查订单A→查订单B→查订单C"这种正常多步推进。但纯"工具名+参数"漏杀"换着参数打转"（A 失败 B 失败 C 失败），所以生产可叠二级熔断（同工具连续失败 N 次也拦）。本周验收造的死循环是"同一失败调用反复重放"（参数相同），标准定义直接命中。

### 2.3 代码骨架（四件套 + 三层 + 落库，节选自 `code/agent.py`）

防护参数集中在文件顶部，改一处就能调：

```python
MAX_STEPS   = 12     # ① 步骤上限
REPEAT_LIMIT= 3      # ④ 同一「工具名+参数」连续出现几次后拦截
KEEP_RECENT = 2      # ② 摘要压缩：保留最近几个「完整工具交互块」原文
TOKEN_BUDGET= 4000   # ③ token 软预算（触发摘要压缩）
TOKEN_HARD  = 12000  # ③ 硬熔断
TOOL_TIMEOUT= 8      # ② 单工具超时（秒）
RUN_TIMEOUT = 120    # ② 整体运行超时（秒）
```

重复调用检测（④）——key 必须带参数，连续超阈值就拦截并终止：

```python
key = f"{name}|{canonical}"          # 工具名 + 规范化参数
if key == last_key:
    repeat_count += 1
else:
    repeat_count, last_key = 1, key
if repeat_count > REPEAT_LIMIT:       # 连续 >3 次相同调用
    obs = f"⚠️ 重复调用检测：工具 {name} 以相同参数连续调用 {repeat_count} 次，已拦截"
    # 落库 steps.status='repeat_blocked', guardrail='repeat'；终止 run
    run_status, ended_reason = "guarded", "repeat"
    break
```

摘要压缩（②）——**协议红线**：`tool` 消息必须紧跟带 `tool_calls` 的 assistant，所以压缩以"assistant + 其全部 tool 响应"为不可分割单元，绝不留悬空：

```python
def maybe_compress(messages, keep_recent, use_mock):
    block_starts = [i for i, m in enumerate(messages)
                    if m.get("role") == "assistant" and m.get("tool_calls")]
    if len(block_starts) <= keep_recent:
        return messages, None
    first_keep = block_starts[-keep_recent]
    prefix = messages[:block_starts[0]]            # 前置 user/system
    older  = messages[block_starts[0]:first_keep]  # 被整块压缩（无悬空）
    tail   = messages[first_keep:]                 # 保留近期原文
    summary = build_summary(older, use_mock)
    return prefix + [{"role":"system","content":summary,"_summary":True}] + tail, summary
```

### 2.4 工具调用落库：审计 + 外部存储一举两得

我们落的库是一套本地预置的 `agent_runtime` 运行时库（GenAI 平台风格的表），本周用到的核心三张表（1:N，类比 Laravel 的 `hasMany`）：

```sql
-- 任务主表：一次用户请求 = 一行（类比 orders 主表）
CREATE TABLE runs (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  agent_id BIGINT NOT NULL,          -- 外键 -> agents（本周长出一个 seed 行）
  conversation_id BIGINT NOT NULL,   -- 外键 -> conversations
  task_input TEXT, model VARCHAR(64),
  status VARCHAR(16),                -- running / done / guarded / failed
  ended_reason VARCHAR(32),          -- completed / repeat / timeout / max_steps / token_budget
  total_steps INT, total_tokens INT,
  created_at DATETIME, finished_at DATETIME
);

-- 步骤明细：每个 ReAct 迭代 = 一行（类比 order_items / audit_log）
CREATE TABLE steps (
  id BIGINT PRIMARY KEY AUTO_INCREMENT, run_id BIGINT,
  step_no INT, span_type VARCHAR(16),  -- llm(Thought) / tool(Observation)
  thought TEXT, tool_name VARCHAR(64),
  tool_args JSON, observation TEXT,
  status VARCHAR(16),                  -- success / failed / timeout / repeat_blocked
  guardrail VARCHAR(32),               -- 触发了哪条防护
  dedup_key VARCHAR(128),              -- 重复检测键 = 工具名+参数hash
  tokens INT, latency_ms INT
);

-- 规范消息流：回放用（kind 区分 normal / summary）
CREATE TABLE messages (
  id BIGINT PRIMARY KEY AUTO_INCREMENT, conversation_id BIGINT, run_id BIGINT,
  role VARCHAR(16), content TEXT, kind VARCHAR(16),
  tool_call_id VARCHAR(64), metadata JSON
);
```

**回放**就是一句：`SELECT * FROM steps WHERE run_id=? ORDER BY id` —— 完整还原当时怎么想的、调了啥、拿到啥、为什么停。同时 `observation` 落库后，对话里只留引用（接 2.1 的 ③ 外部存储）。一张表同时吃下"记忆三层"和"审计"两条验收。

> 这套库对 W04 是"超集"：除了上面的运行时表，它还预置了 W05 RAG（documents / chunks / memories）、W13 评测（evaluations / feedbacks）的表——等于一次性把课程后半段的"运行时底座"铺好了。本周只用到 runs/steps/messages 三张。

---

## 三、踩坑记录（3 条，均有终端输出作证）

### 坑 1：摘要压缩制造"悬空 tool 响应"，真实 API 直接 400

- **现象**：真实模式跑到第 4 轮崩溃，`urllib.error.HTTPError: HTTP 400: Messages with role 'tool' must be a response to a preceding message with 'tool_calls'`。
- **真因**：旧 `maybe_compress` 按"tool 消息索引"切分压缩——第 3 轮末把 `assistant(tool_calls: query_order+query_logistics)` 删了，却把它的 `tool` 响应留在了 tail 里。第 4 轮把 `[system摘要, tool(物流结果), ...]` 发上 API，那个悬空的 `tool` 前面不是 assistant，直接 400。前 3 轮没报错，正是因为压缩是在第 3 轮末才第一次触发。
- **解法**：① 把压缩单元从"单条 tool 索引"改成"完整工具交互块"（assistant + 其全部 tool 响应），整块保留或整块移走，绝不留悬空；② `KEEP_RECENT` 从 3 降到 2，让 3 块的正常流程也能真实触发一次压缩演示；③ 新增 `validate_messages` 防御性校验，真实模式每次发请求前拦截，万一再出问题会**打印 messages 结构**而不是闷头打 400。

```python
def validate_messages(messages):
    """每条 tool 消息的 tool_call_id 必须对应『前面某个未消费的 tool_call』。"""
    pending = {}
    for m in messages:
        if m.get("role") == "assistant" and m.get("tool_calls"):
            for tc in m["tool_calls"]:
                pending[tc["id"]] = True
        elif m.get("role") == "tool":
            if m.get("tool_call_id") not in pending:
                issues.append(f"{i}: tool 找不到对应 tool_call（悬空）")
            else:
                pending.pop(m["tool_call_id"], None)
    if pending:
        issues.append(f"存在未闭合的 tool_calls: {list(pending)}")
```

> 验证：写临时单元测试覆盖"你报错同款 3 块场景 + 4 块复杂场景 + 不压缩场景 + 旧逻辑复刻"——新逻辑压缩后 `validate` 零问题，旧逻辑必然悬空。测试文件事后删了。

### 坑 2：死循环防护④ 在真实模式没触发——因为模型自愈了

- **现象**：`$env:W04_DEADLOOP=1` 让物流接口恒 500 后真实跑，模型只重试了 **1 次**物流（第 2、3 轮各一次 500），第 4 轮就跳去 `decide_refund` 了。④ 没机会拦，`status=done`，且模型在最终回答里**主动说明"物流接口两次 500，基于订单状态判定"**。
- **真因**：④ 依赖"模型连续 >3 次调同一工具"，但真实 LLM 看到工具失败后**自己只重试 1 次就换策略**（跳过故障接口、用订单状态兜底）。这不是 bug，是模型的**优雅降级**能力，比"被兜底拦下"更优。
- **结论（诚实披露）**：④ 的逻辑实证仍靠 **mock 模式**（`--deadloop`，`status=guarded / ended_reason=repeat`，连续 4 次相同失败被拦）。真实模式这次验证的是更有价值的事——**真实模型遇到故障会自我降级**，不会傻循环。验收"死循环被拦"由 mock 实证支撑，真实模式暴露了更好的工程现实。

### 坑 3：落库时 `messages.conversation_id` NOT NULL，卡住第一个 run

- **现象**：首跑报错 `Column 'conversation_id' cannot be null`。
- **真因**：库的 `messages` 表 `conversation_id` 是 `NOT NULL` 且无默认值，而 W04 单任务场景一开始忘建 conversation 记录。
- **解法**：每个 run 先建一条 `conversations` 行（也符合库的设计意图，W05 多轮对话直接复用），再把 `conversation_id` 传给所有 message 写入。同时 `runs.agent_id` 也是 `NOT NULL`，跑第一个 run 前先往 `agents` 表 seed 了一行（`slug=refund-agent`）。

> 附带一个小坑（非错误，是设计坑）：摘要压缩会把"已执行的工具对"从 messages 摘掉存进 steps。如果 mock 启发式靠扫描 messages 判断"执行到哪了"，压缩后就以为没查过、从头死循环。改成在循环里维护一个**独立的 `done_tools` 状态**传给 mock，压缩不影响它。

---

## 四、验收清单（对照 CURRICULUM）

| 验收项 | 状态 | 证据 |
|---|---|---|
| 任务自动跑完（订单→物流→判定→退款全自动） | ✅ | 真实 run9 正常退款 `done`；run10 不可退分支 `done` |
| 数据库能完整回放每一步 | ✅ | `steps` 表按 `step_no` 存 `llm`+`tool` span，可 `SELECT * FROM steps WHERE run_id=?` |
| 死循环被拦住且日志可查 | ⚠️ | mock run5 `guarded/repeat` 实证；真实模式未触发（模型自愈，见坑 2，已如实记录） |
| 产出带防护与审计的 Agent（里程碑 M2） | ✅ | `code/agent.py`（纯 stdlib + pymysql，落库可降级） |

---

## 五、数据 / 实测结果

所有数字来自本机真实运行（Python 3.13，中转站 DeepSeek 兼容接口），以及 mock 对照。

### 真实模式（amber 本机双击 bat 后跑通）

| 场景 | 订单 | 轮数 | status | tokens | 过程 |
|---|---|---|---|---|---|
| 正常退款 | NO20260911001（已签收） | 4 | done | 363 | 订单→物流→判定可退→执行退款；第 3 轮触发摘要压缩（8→6） |
| 不可退款 | NO20260911002（运输中） | 3 | done | 318 | 订单→物流→判定不可退→收尾不执行 |
| 物流故障 | NO20260911001 | 6 | done | 407 | 物流两次 500 后**模型自愈**跳判定→退款；中途 3 次触发压缩 |

**实测量（正常退款 run9）**：

```
第 1 轮 | messages 共 1 条
  -> 执行工具 query_order({"order_id": "NO20260911001"})
  <- 回填: {"order_id":"NO20260911001","user_id":"U1001","status":"已签收","amount":299.0,...}
  -> 执行工具 query_logistics({"order_id": "NO20260911001"})
  <- 回填: {"order_id":"NO20260911001","carrier":"顺丰","track_no":"SF123","status":"已签收",...}
第 2 轮 | messages 共 4 条
  -> 执行工具 decide_refund({"order_id": "NO20260911001"})
  <- 回填: {"refundable": true, "reason": "已签收且在7天内", "amount": 299.0}
第 3 轮 | messages 共 6 条
  -> 执行工具 execute_refund({"order_id": "NO20260911001", "amount": 299.0})
  <- 回填: 已对订单 NO20260911001 退款 299.0 元，预计原路返回
  🗜️ 触发摘要压缩：8 条 -> 6 条（老轮次存入 steps 表）
第 4 轮 | messages 共 6 条
模型最终回答：退款已处理完成 ✅ ...（结构化表格汇报）
===== run 结束 | run_id=9 status=done tokens≈363 =====
```

> 注意第 3 轮的 `🗜️ 触发摘要压缩：8 条 -> 6 条`——这正是 W03 担心的"messages 暴涨"被本周边际治理：老的两个工具交互块被压成一条 `kind='summary'` 消息，对话上下文变短，但原始数据还在 `steps` 表里可回放。

### mock 模式（无需 Key，CI / 无网也能验证逻辑）

| 场景 | 命令 | 结果 |
|---|---|---|
| 正常退款 | `--mock` | `status=done`，4 个 tool 步骤完整，第 4 步触发压缩 |
| 不可退款 | `--mock --order NO20260911002` | `status=done`，判定不可退后收尾不执行 |
| 死循环④ | `--mock --deadloop` | `status=guarded / ended_reason=repeat`，连续 4 次相同失败被拦（**④ 实证**） |
| 边界演示 | `--mock --edge` | 异常转字符串 / 幂等去重 / 重复拦截 / 超时熔断，四项正常 |

### 防护四件套参数对照（代码顶部常量，可直接调）

| 防护 | 常量 | 默认 | 本次真实场景是否触发 |
|---|---|---|---|
| ① 步骤上限 | `MAX_STEPS` | 12 | 否（正常 3~6 轮结束） |
| ② 超时 | `TOOL_TIMEOUT` / `RUN_TIMEOUT` | 8s / 120s | 否（工具均秒回） |
| ③ token 预算 | `TOKEN_BUDGET` / `TOKEN_HARD` | 4000 / 12000 | 软触发（压缩）；硬熔断未达 |
| ④ 重复检测 | `REPEAT_LIMIT` | 3 | **真实未触发（模型自愈）**；mock `--deadloop` 触发 |

---

## 六、这周的取舍

### 做了什么

- 在 W03 零框架循环上，把阶段 1 讲的四个小节**全落进代码**：ReAct 三段结构化记录（落 `steps.span_type`）、记忆三层（历史落 `messages` / 摘要压缩 `kind='summary'` / 事实落 `steps`）、防护四件套、工具调用落库（runs/steps/messages 三表联动）。
- 业务场景按"查订单 → 查物流 → 判断退款 → 执行退款"全自动，`execute_refund` 带幂等去重（W03 讲的 Stripe 幂等键落地）。
- 真实 API 跑通，且**意外验证了模型的故障自愈能力**——比单纯"被防护拦下"更真实、更有料。

### 放弃了什么 / 留到后面

- **死循环④ 的真实模式验证没做满**：因为真实模型不会傻循环，④ 只靠 mock 实证。是否要在真实模式也强制造一次死循环（代码层无视模型决策、强制重复）？我们判断价值有限（只是为日志而日志），接受"mock 实证 + 真实自愈"的写法。如果你想要真实模式的 guarded 日志，可以加一个"强制死循环"调试开关。
- **Layer 2 摘要压缩用了 LLM 调用**（真实模式 `build_summary` 会再打一次 API 压摘要）。这本身又消耗 token，生产应换成更便宜的模型或本地压缩。本期如实标注。
- **并行调用仍未做**：工具串行执行（W03 留的优化项），W05+ 再考虑。

### 一个方法论提醒

我们联网核对了 2026 年 ReAct / 记忆 / 防护的实践，确认这套范式仍是主流骨架（只是多了些托管记忆服务如 Mem0 / LangMem）。**没有因为训练数据而自作主张改课表**——若后续发现过时，会回头更新 `CURRICULUM.md`。Agent 领域变化快，但"亲手给循环装刹车"这件事，一来没变过。

---

## 下一篇

W05 讲 **Embedding 与向量检索**——正式进入 RAG 的"取数"环节。本周落地的 `agent_runtime` 库里已经预置了 `documents` / `chunks` / `memories` 表，W05 直接复用：把文本切成 chunk、算 embedding、存起来，再按语义查回来。那套"记忆三层"里的 ③ 外部存储，会从一个退款 Agent 的临时结果，升级成"可跨会话检索的知识库"。

> 本周留下的尾巴：Layer 2 摘要压缩消耗 token（换便宜模型）、并行调用、死循环④ 的真实 forced 验证（可选）。这些 W05、W15 会分别收口。

## 附录：学习对话实录

- [DIALOGUE.md](DIALOGUE.md) —— 提炼版：按主题归类，含「给 AI 的复现指令」，可直接复制给任意 AI 带你走一遍
- [DIALOGUE-QA.md](DIALOGUE-QA.md) —— 逐轮一问一答底稿：保留每一次提问、回答与终端输出

## 附录：延伸阅读

- [ReAct 论文（Yao et al., 2022）](https://arxiv.org/abs/2210.03629) —— Reason + Act 范式原论文
- [OpenAI Tool Use 文档](https://platform.openai.com/docs/guides/function-calling) —— tool_calls 协议、并行调用、streaming 下的处理
- 2026 工程实践：托管记忆服务（Mem0 / LangMem）兴起，但"历史 / 摘要 / 外部存储"三层结构仍是基础；防护四件套（步数上限 / 超时 / token 预算 / 重复检测）是 Agent 上生产的标配

---

## 发布检查

- [x] 代码实际跑过，输出贴进正文（真实 run9/10/11 + mock 四场景）
- [x] 至少 2 条真实踩坑（实际 3 条：压缩悬空 400 / ④ 真实未触发但模型自愈 / conversation_id NOT NULL）
- [x] 有数字/表格（run9/10/11 tokens 363/318/407；四件套参数对照；压缩 8→6）
- [x] 有 PHP / SQL 类比（Controller 多步编排、audit_log、物化视图、Stripe 幂等键、Laravel 队列 unique、Guzzle timeout）
- [x] 标题不标题党，但要有信息量
- [x] 结尾有引导（下一篇 / 仓库链接）
- [x] 本周写了 `DIALOGUE.md`（对话实录 + 可复现的 AI 引导脚本）
- [x] 本周写了 `DIALOGUE-QA.md`（逐轮问答底稿，只收技术相关）
- [x] 死循环④ 未触发一事诚实披露（mock 实证 + 真实自愈），未假装真实模式拦下
- [x] Layer 2 摘要压缩消耗 token、并行未做等局限已如实标注
