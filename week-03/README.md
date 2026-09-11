# W03 · Tool Use：亲手把 LLM 调教成"会干活的 Agent"，而不是只会对答的聊天框

> Agent 开发实战 16 周 · 第 3 周 · 实际投入约 6 小时
>
> 一句话钩子：**前两周你只是在"调 LLM 拿结果"，还是一问一答。从这周起，LLM 第一次反过来指挥你的代码去干活，再带着结果继续思考。**

**另有一份 [学习对话实录](DIALOGUE.md)**：这周的完整学习过程，包括猜错的地方、被质疑后改掉的写法，以及一套可以直接丢给 AI 的**引导脚本**——照着它能用同样的方式带你走一遍。

## 开篇：这周要解决什么问题

前两周你干了两件事：W01 把 API 调用跑通、看清每次花多少钱；W02 让模型吐出能进数据库的 JSON。但这两周，**模型始终是被动的**——你问一句，它答一句，你拿结果去用。

这一周要打破这个格局。想象一个真实场景：

> 用户说：「北京天气怎么样？再帮我看看订单 NO20260911001 的状态，如果已经发货了，通知用户 U1001 说一声。」

一个只会"对答"的模型会给你三段散文。一个 **Agent** 会：**查天气 → 查订单 → 读结果判断已发货 → 调发通知工具 → 汇报**。注意，中间那次"读结果判断已发货"是模型**基于工具返回的数据在推理**，不是模板拼接。

这就是 W03 的主题：**Tool Use（工具调用）**。它把 LLM 从一个"文本生成器"变成了一个"能操作你系统的决策者"。所有框架（LangChain、LangGraph、Prism）做的第一件事，就是把本周这个循环工程化——所以本周必须亲手写出来，不能靠框架糊弄过去。

## 核心结论（先给答案）

1. **LLM 不执行任何函数，它只产生"调用意图"**。你的 `while` 循环才是真正的执行引擎。模型每次只看到 `messages` 数组，决定"下一步调哪个工具 / 还是直接回答"。
2. **`messages` 数组每转一圈就变长**。每个工具结果都是数组里新增的一行，模型每轮要把前面所有上下文重读一遍——这就是 W02 你担心的"messages 暴涨"的根因（W04 讲压缩）。
3. **工具 `description` 是模型能读到的唯一 API 文档**。写得差，准确率直接掉；2026 年工程复盘一致结论：清晰的 `description` 比模糊描述 **+16%** 调用准确率（见第二节，非本课实测数据）。
4. **工具抛异常必须转成字符串回填，绝不能冒泡**。否则循环直接崩。这等于给模型一个能自我修正的 `422` 错误。
5. **写操作重试是地雷**：通知发了但网络超时，你一重试就双发。靠"从操作内容派生的幂等键"防住——类比 Stripe 的 `Idempotency-Key`。
6. **`max_steps` 必设**。否则模型可能反复调同一个注定失败的参数，烧 token 到天荒地老（W04 防护伏笔）。

---

## 一、循环机制：是谁在"执行"函数

### 1.1 先建立一个反直觉的认知

**LLM 不会真的"调用"任何函数。** 它只会"说"：*我打算调用 `get_weather`，参数是 `{city: 北京}`*。至于这个函数怎么跑、跑出什么，是你的代码干的，不是模型干的。

这和 PHP 的直觉**完全相反**。在 Laravel 里你写 `$weather = Weather::get('北京');`，函数同步执行、结果立刻回到你手里，是**同一个进程里的同步调用**。但 Agent 里，模型是"暂停"的——它吐出一个调用意图，等你的 `while` 循环把结果喂回来，它才接着想下一步。

> **类比**：把 LLM 想成"只会出 SQL 执行计划的 DBA，不会自己跑查询"。`User::find($id)` 在你脑子里是"立刻拿到对象"；在 Agent 里，模型返回 `tool_call: get_user(id=123)`，但 `User` 数据它**根本没碰过**。它只负责"规划"，你负责"执行"。

| PHP/Laravel 世界 | Agent 世界 |
|---|---|
| Controller 里 `$user = User::find($id)` 同步拿回对象 | 模型返回 `tool_call: get_user(id=123)`，但 User 数据它没碰过 |
| 函数返回值直接用在下一行 | 返回值由你的代码 append 回 messages，再整体发给模型 |
| 进程内调用，微秒级 | 一次 HTTP 往返，几百毫秒~几秒 |

### 1.2 一次完整的消息流（本周最该记住的东西）

用户问："北京天气怎么样？"

```
① 你发给模型的 messages（第 1 轮）：
   [{role: user, content: "北京天气怎么样？"}]

② 模型返回（注意：没有正文，只有 tool_calls）：
   assistant.tool_calls = [
     {id: "call_1", function: {name: "get_weather", arguments: '{"city":"北京"}'}}
   ]

③ 你的代码执行：get_weather("北京")  →  "晴, 24°C"

④ 你把"两条"消息 append 回数组：
   - assistant 消息（原样保留，含 tool_calls）
   - tool 消息：{role: "tool", tool_call_id: "call_1", content: "晴, 24°C"}

⑤ 现在 messages 变成 4 条：
   [user, assistant(带call), tool(结果)]  ← 下一轮发给模型

⑥ 模型第 2 轮返回：
   "北京今天晴，24°C，适合出门。"  ← 这次没有 tool_calls，循环结束
```

**关键一句话：`messages` 数组每转一圈就变长。** W02 笔记里你写的"下周注意：messages 暴涨"——根因就在这：每个工具结果都是数组里新增的一行。这又是个 PHP 类比：Laravel 不用 session、每次把整个会话数组当 POST 参数传，所以每次请求体都越来越胖。

### 1.3 循环骨架（先不纠结细节）

```python
messages = [{"role": "user", "content": "北京天气怎么样？"}]
while True:
    resp = client.chat.completions.create(model=..., messages=messages, tools=TOOLS)
    msg = resp.choices[0].message

    if not msg.tool_calls:          # 模型觉得不用再调工具了
        print(msg.content)          # 输出最终答案，退出
        break

    messages.append(msg)            # ① 先把带 tool_calls 的 assistant 消息存回去（关键）
    for call in msg.tool_calls:     # ② 逐个执行
        result = run_tool(call.function.name, call.function.arguments)
        messages.append({           # ③ 回填结果
            "role": "tool",
            "tool_call_id": call.id,
            "content": result,
        })
    # 回到 while 顶部，把更长的 messages 再发给模型
```

三个细节，少一个模型都会报错或失忆：

- **`messages.append(msg)`**：带 `tool_calls` 的那条 assistant 消息必须先留着，不能只存结果。
- **`tool_call_id` 必须回传**：模型靠这个 id 把"结果"精确贴回"当初那个调用意图"。对不上就崩。
- **while 必须有出口**：模型不是每次都停，得靠"没有 tool_calls 就 break"或"步数上限"来收口。

> 我们用零框架纯 Python 手写这个循环（完整代码见 `code/agent.py`），给 3 个工具：查天气、查订单、发通知。`--mock` 模式纯标准库、无需 Key 就能跑，专门用来看清循环怎么转。真实跑一次，你会看到第 1 轮 `messages` 从 1 条 → 执行 3 个工具后变 5 条；第 2 轮模型拿到结果直接给最终回答。

---

## 二、工具粒度、命名、描述：描述是给模型看的 API 文档

### 2.1 为什么"描述"是本周最该花功夫的地方

模型看不到你的源码。它唯一判断"该不该调这个工具、怎么传参"的依据，就是 `description` + 参数 `description`。这玩意儿就是**模型能读到的唯一文档**。

> **类比（你最熟的）**：你 `composer require` 一个包，不会去读源码，而是读 README / PHPDoc 才知道每个方法干嘛、啥时候用、参数啥格式。模型连源码都没有，它的 `description` 字段就是它的 PHPDoc。你写"处理数据"，等于 PHPDoc 写"does stuff"——废物；你写"查询指定城市实时天气，用户问天气/出行/温度时使用"，就是带 `@param` 和 `@usage` 的正经文档。

**2026 年工程复盘的一致结论**（多家团队实测，非本课自测数据，仅作方向参考）：

| 优化动作 | 调用准确率增量 |
|---|---|
| 模糊描述 → 清晰具体的 `description` | **+16%** |
| 再加参数的 `examples` | 再 **+7%** |
| 再加约束（`enum` / `format` / `pattern`） | 再 **+3%** |
| 优化到位可达 | **~93%** |

原因一句话：模型看不到你的源码，**`description` 是它判断"该不该调、怎么调"的唯一依据**。

### 2.2 命名：动词+名词，像 Laravel 命名路由

| ❌ 差命名 | ✅ 好命名 | 类比 |
|---|---|---|
| `process` | `get_weather` | 像 `php artisan user:create`，动宾清晰 |
| `do_query` | `query_order` | 像 Laravel 命名路由 `route('admin.sales.index')` |
| `handle` | `send_notification` | artisan 命令见名知意 |

模型靠"名字的语义"匹配用户意图。一个 `process` 放到 20 个工具里，模型分不清调哪个。

### 2.3 粒度：一个能力一个工具，变化走参数

| 极端 | 问题 |
|---|---|
| 太粗：`do_everything(action, params)` | 模型得自己拼 action 字符串，错率高（像 God Controller 用 `$action` switch 分流，反模式） |
| 太细：`get_temp` / `get_humidity` / `get_wind` | 工具列表爆炸，模型选花眼、token 涨 |
| ✅ 适中：`get_weather(city, date)` | 一个能力一工具，变化交给参数（一个 resource 路由 + 查询参数） |

**甜点区**：一个工具 = 一个能力，变化交给参数。比如"查订单"——按单号查、按用户查，都是**同一个 `query_order` 工具**，靠 `order_id` / `user_id` 参数区分，而不是拆成两个工具。

### 2.4 好 vs 差，直接看定义

```python
# ❌ 差：模型不知道何时用、参数啥意思
{
    "name": "process",
    "description": "处理数据",
    "parameters": {"type": "object",
                   "properties": {"input": {"type": "string"}}},
}

# ✅ 好：说清"做什么 + 何时用 + 参数约束 + 示例"
{
    "name": "get_weather",
    "description": "获取指定城市的实时天气。当用户询问天气、出行建议、"
                   "温度或是否适合外出时使用。",
    "parameters": {"type": "object",
        "properties": {
            "city":  {"type": "string", "description": "城市名，如'北京'、'上海'",
                      "examples": ["北京", "上海"]},
            "date":  {"type": "string", "description": "日期，格式 YYYY-MM-DD，默认今天",
                      "pattern": r"^\d{4}-\d{2}-\d{2}$"},
        },
        "required": ["city"],
        "additionalProperties": False,   # 禁止模型瞎编参数
    },
}
```

**描述里最关键的一句是"何时使用"**——不是"做什么"。"做什么"是给程序员看的，"何时用"是给模型做触发决策的。`additionalProperties: False` 则硬性禁止模型编造你没声明的参数。

---

## 三、失败返回错误字符串，绝不抛异常

### 3.1 一句话原则

**工具函数内部的所有异常，必须 catch 住、转成字符串、作为 tool 消息的 `content` 回填。绝对不能让异常冒泡炸掉你的 while 循环。**

### 3.2 为什么（用你最熟的 Laravel 类比）

| Laravel 世界 | Agent 世界 |
|---|---|
| Controller 里 `throw` 未捕获异常 → 整个请求 500 挂掉 | 工具函数 `raise` 未捕获异常 → while 循环崩溃，对话直接死 |
| 返回 `422 Unprocessable Entity` + 错误信息 → 调用方（前端）能据此修正参数重试 | 把错误写成字符串回填 tool 消息 → **模型能据此修正参数/换思路重试** |

模型在这里扮演"会读错误信息自我修正的 API 客户端"。你给它 `Error: 订单号格式错误，应为 NO 开头`，它有极高概率下一轮就把参数改对。你一旦 `raise` 让它啥都看不到，它连"我刚才错了"都不知道，对话就结束了。

### 3.3 错误有两种，都要变成字符串

```python
def execute_tool_safe(name: str, arguments_json: str) -> str:
    """执行工具，任何异常都吞掉转成字符串回填（绝不冒泡）。"""
    try:
        args = json.loads(arguments_json) if arguments_json else {}
    except json.JSONDecodeError as e:
        return f"Error: 参数不是合法JSON: {e}"          # ← 回填，不 raise

    try:
        if name == "query_order":
            return query_order(**args)
        # ... 其余工具
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"         # ← 任何运行时异常都吞掉转字符串
```

注意第二层：**即便"逻辑上没查到"也不该抛异常**——查订单返回空，应该回填 `"未找到订单 NO2026xxx，请确认订单号"`，而不是 raise `OrderNotFound`。空结果也是"成功执行了查询"的正常输出，模型拿到后能问用户要正确单号。

### 3.4 回填后模型下一轮能看见，形成自愈循环

```
assistant: tool_calls=[query_order(order_id="NO2026错")]
tool:      "Error: 订单号格式错误，应为 NO 开头"   ← 模型读到这句
   ↓ 下一轮
assistant: "您给的订单号格式不对，能发一下正确的吗？比如 NO20260911001"
```

这就是**自愈循环**：错误字符串 → 模型修正 → 再调 → 成功。

> **伏笔（W04 才展开）**：错误回填解决了"单次失败不死"，但模型可能反复调同一个注定失败的参数，烧 token 到天荒地老。所以 while 循环里要加**步数上限**（本代码 `MAX_STEPS=8`）和错误重试轮次上限，到顶强制收口——这是 W04 "防护四件套"的第一件。

### 3.5 安全钩子（W15 铺路）

"查 MySQL"如果是让模型传一段 raw SQL 字符串进来执行——那跟 PHP 里拼接用户输入进 SQL 一模一样，是注入漏洞。正确做法是工具只接收**结构化参数**（`order_id` / `user_id`），SQL 由你代码里写死、参数走预处理。这条 W15 安全红队会专门打，但现在写工具就要养成习惯。

---

## 四、并行调用与幂等性

### 4.1 并行调用：独立读操作要并发，别串行

模型一个回合可以吐出**多个** `tool_calls`。比如用户问"北京和上海天气怎么样"，模型会一次返回两个 `get_weather` 调用。这时候要并发执行：

```
串行：查北京 0.8s + 查上海 0.9s = 1.7s   ← 慢
并行：max(0.8s, 0.9s) = 0.9s             ← 只取最慢那个
```

**Laravel 类比**：像用 Guzzle 的 `concurrent()` 并发发多个 HTTP 请求，而不是 `foreach` 里一个个 `->get()`。延迟从"求和"变"取最大"。

### 4.2 并行的陷阱：一个挂了，全回合卡死

并发不是无脑 `Promise.all`。工程复盘的核心警告：**没有 per-call timeout 的并发是陷阱**——一个工具 HTTP 连接卡死，整个回合干等，模型坐等一个永远不来的结果。正确做法：

- **`allSettled` 而非 `all`**：一个失败不取消兄弟调用，所有结果（成功或失败）都收集回来回填。
- **每个调用各自带超时**：超时当成可重试的失败，走同一错误处理通道。

> 本课的 `agent.py` 为了清晰，工具是**串行**执行的。独立只读本可并发，但串行"安全但不最优"——这个优化方向留到 W04（配合防护一起做）。

### 4.3 幂等性：写操作重试是地雷

| 工具类型 | 例子 | 重试安全吗 |
|---|---|---|
| **读** | `get_weather`、`query_order` | ✅ 安全，查 100 次结果一样 |
| **写** | `send_notification`（发通知） | ❌ **危险** |

为什么危险：你调 `send_notification` 发通知，**服务端可能已经发出去了，只是网络超时、你这边没收到回包**。你一重试 → **又发一条**。用户收到两条一模一样的通知。

**PHP/Laravel 类比**：这跟 Stripe 支付重试一模一样——Stripe 要求每次支付请求带一个 `Idempotency-Key`，相同 key 重复提交只扣一次钱。也像 Laravel 队列 job 的 `unique` 去重键：同一个 key 的 job 不会重复入队。

### 4.4 幂等键怎么造（关键：从"操作身份"派生，不是随机 UUID）

```python
def idempotency_key(tool: str, args: dict) -> str:
    canon = json.dumps(args, sort_keys=True, ensure_ascii=False)  # 顺序无关规范化
    return f"{tool}:{canon}"

# send_notification(to=123, msg="x") 重试三次 → 三次都得到 "send_notification:{"msg":"x","to":123}"
# 服务端认这个 key：第一次真发，后两次直接返回原结果，不再发第二次
```

⚠️ **绝不能用随机 UUID 当幂等键**——那样两次重试算出两个不同的 key，服务端认不出是同一件事，照样双发。幂等键必须从"操作内容"派生，这样"同一个意图的重试"必然得到"同一个键"。

### 4.5 落到我们的 3 个工具（决策矩阵）

> 规则：含写操作 或 有依赖 → 串行；独立只读 → 并行。

| 场景 | 决策 | 原因 |
|---|---|---|
| "查北京和上海天气" | **并行** | 两个 `get_weather` 独立只读 |
| "查订单123 → 给该用户发通知" | **串行** | 通知依赖订单结果 + 通知是写操作 |
| "查天气 同时 查订单" | 读并行、写隔离 | 读并发，写单独串行+幂等键 |

---

## 五、踩坑记录（3 条，均有终端输出作证）

### 坑 1：urllib 打中转站返回 403 Forbidden，curl 却正常

- **现象**：真实模式第一次跑，直接 `urllib.error.HTTPError: HTTP Error 403: Forbidden`。
- **真因**：`urllib` 默认 `User-Agent` 是 `Python-urllib/3.13`，被中转站的 WAF 当成异常脚本客户端拦截。而同一条请求用 `curl.exe` 能正常连——因为 curl 默认 UA 是 `curl/8.x`，WAF 放行。
- **解法**：请求头加浏览器风格 UA：

```python
headers={"Authorization": f"Bearer {key}",
         "Content-Type": "application/json",
         "User-Agent": "Mozilla/5.0 (compatible; w03-agent/1.0)"}
```

  加完重跑，真实模式直接拿到模型的 tool_call 返回。这跟 Laravel 里"代码逻辑全对、却被 Nginx/网关某条规则拦了"是同一类坑——**业务逻辑没错，是传输层把客户端识别成不受欢迎的来源**。

### 坑 2：PowerShell 里敲 `export` 报错"不被识别"

- **现象**：在 PowerShell 里设变量，敲 `export OPENAI_API_KEY=xxx`，报错 `'export' is not recognized as the name of a cmdlet`。
- **真因**：`export` 是 bash 语法，PowerShell 用 `$env:变量 = "值"`。而且 `start-env-windows.bat` 用 `powershell -NoExit` 启的是**新子进程**，变量只活在弹出的窗口里——在别的窗口设了也读不到。
- **解法**：统一双击 bat 注入变量，在弹出窗口里直接跑 `python agent.py`；或手动 `$env:API_KEY = "..."`。**不重复设变量、不跨窗口**。

### 坑 3：变量名对不上 + Edit 工具静默未写入（老坑复发）

- **现象**：`start-env-windows.bat` 注入的是 `API_KEY`/`BASE_URL`/`MODEL`（无前缀），而 `agent.py` 原读 `OPENAI_API_KEY`（带前缀），导致 bat 配好的东西读不到，逼得手动再设一遍。改对齐时，Edit 工具报 `Success` 但 `real_llm` / `main` 两处旧代码**根本没写入**。
- **真因**：① 变量名前缀不一致；② Edit 静默失败（本系列第三次踩：W01/W02 各一次）。
- **解法**：`agent.py` 改为**优先 `OPENAI_*` 前缀、回退无前缀 `API_KEY/BASE_URL/MODEL`**，两种设变量方式都认；改动一律用 `replace()` + `assert` 强制并独立读盘校验，不信任工具返回值。

```python
key   = os.environ.get("OPENAI_API_KEY") or os.environ.get("API_KEY")
base  = os.environ.get("OPENAI_BASE_URL") or os.environ.get("BASE_URL")
model = os.environ.get("OPENAI_MODEL")   or os.environ.get("MODEL")
```

---

## 六、验收清单（对照 CURRICULUM）

| 验收项 | 状态 | 证据 |
|---|---|---|
| 能手画循环图（tool_call→执行→回填→再请求） | ✅ | 第一节六步消息流 + 第三节自愈循环 |
| 能解释"为什么工具描述写得差模型就不会用" | ✅ | 第二节 +16% 文档依据 + 现场写 description |
| `max_steps` 必设 | ✅ | 代码 `MAX_STEPS=8`，第五节伏笔说明 |
| 产出零框架 Agent 实现 | ✅ | `code/agent.py`（纯 stdlib，mock/edge/真实三模式） |
| 双语言（PHP/Prism 重写） | ⏸️ | **amber 拍板推迟到 W09**（框架周落地），未假装写过 |

---

## 七、实测数据

所有数字来自本机真实运行（Python 3.13，中转站 DeepSeek 兼容接口）。

### 模式一：`--mock`（无需 Key，纯标准库）

```
第 1 轮 | messages 当前共 1 条
  -> 执行工具 get_weather({"city": "北京"})
  <- 回填: {"city": "北京", "date": "今天", "weather": "晴", "temp": "24°C"}
  -> 执行工具 query_order({"order_id": "NO20260911001"})
  <- 回填: {"order_id": "NO20260911001", "user_id": "U1001", "status": "已发货", ...}
  -> 执行工具 send_notification({"to": "U1001", "message": "您的订单已发货"})
  <- 回填: 已向用户 U1001 发送通知：您的订单已发货
第 2 轮 | messages 当前共 5 条
模型最终回答：三件事都已完成...
```

**实测量**：messages 从 `1` 条 → 执行 3 个工具后变 `5` 条 → 第 2 轮收尾。完美复现 W02 担心的"messages 暴涨"。

### 模式二：真实 API（amber 本机双击 bat 后跑通）

模型**自己决定调哪 3 个工具、怎么造参数**——这是和 mock 的本质区别（mock 是关键词硬匹配）：

| 意图 | 模型造的参数 |
|---|---|
| 查天气 | `get_weather({"city": "北京"})` |
| 查订单 | `query_order({"order_id": "NO20260911001"})` |
| 发通知 | `send_notification({"to": "U1001", "message": "您的订单已发货"})` |

模型第 2 轮还**基于工具返回做了推理**："该订单状态正好就是「已发货」，所以这条通知内容和实际状态是吻合的"——这是 tool 结果回填后模型真正"带着数据思考"的铁证。

### 模式三：`--edge`（异常 + 幂等）

- ③ 异常转字符串：`query_order({})` 没传参 → 抛 `ValueError` → 被 `execute_tool_safe` 吞成 `Error: ValueError: ...` 字符串，循环不崩。
- ④ 幂等去重：相同内容发两次，第二次返回原结果、未重复发送，避免双发通知。

### 工具描述质量 vs 准确率（方向参考，非本课实测）

| 优化动作 | 调用准确率增量 |
|---|---|
| 模糊描述 → 清晰 `description` | +16% |
| 加参数 `examples` | +7% |
| 加约束（`enum`/`format`） | +3% |
| 优化到位可达 | ~93% |

> ⚠️ 这是 2026 年多家工程复盘的一致结论，用作"为什么值得花功夫写 description"的方向性依据；本课未自建评测集验证该百分比，不把它当精确实测数字。

---

## 八、这周的取舍

### 做了什么

- 零框架纯 Python 手写 while 循环 Agent，**不依赖任何框架**，把 tool_call→执行→回填→再请求 跑通并实测。
- 3 个工具覆盖"读/读/写"三类，刻意把唯一的写操作 `send_notification` 做成幂等，演示第 4 节的地雷与解法。
- 真实 API 跑通，模型自己选工具造参数（不是 mock 的硬匹配）。

### 放弃了什么 / 留到后面

- **PHP/Prism 重写推迟到 W09**：amber 拍板先收尾 W03 主线，PHP 落地留到框架周（W09 是"PHP 落地：领域 Agent MVP"差异化周），不强行这周跨两条线。
- **`query_order` 用内存 `dict` 模拟 MySQL**：避免依赖真实库，让无 Key/无库也能完整演示循环。真实 DB 落库留 W04——那周本来就要"工具调用日志写 MySQL"。
- **3 工具串行执行**：当前 `for call in tool_calls` 串行，"安全但不最优"。独立只读可并发（第 4 节讲了 `allSettled` + per-call timeout），本期未实现，留作 W04 优化项。

### 一个方法论提醒

我们联网核对了 2026 年 Tool Use 现状，确认课表 W03 四点（循环机制 / 描述质量 / 失败回填 / 并行幂等）仍是工程主流，**未改动 CURRICULUM**。Agent 领域变化快，但"手写一次循环"作为地基这件事，一年来没变过——框架只是把这套循环藏起来。

---

## 下一篇

W04 讲 **ReAct、记忆与循环防护**。我们给这周的 Agent 加三样东西：步骤上限（已埋 `MAX_STEPS` 伏笔）、自动摘要压缩（解决本节 messages 暴涨）、工具调用日志写 MySQL（让每一步可回放、可审计）。然后**故意制造一次死循环**，验证防护真的能拦住——而不是等它烧光 token。

> 本周留下的尾巴：并行调用还没实现；写操作的幂等现在靠"内容派生 key"在本地去重，真实多实例部署时这把锁要落到服务端（数据库唯一索引 / Redis）。这些 W04、W15 会分别收口。

## 附录：学习对话实录

- [DIALOGUE.md](DIALOGUE.md) —— 提炼版：按主题归类，含「给 AI 的复现指令」，可直接复制给任意 AI 带你走一遍
- [DIALOGUE-QA.md](DIALOGUE-QA.md) —— 逐轮一问一答底稿：保留每一次提问、回答与终端输出

## 附录：延伸阅读

- [OpenAI Tool Use 文档](https://platform.openai.com/docs/guides/function-calling) —— tool_calls 协议、并行调用、streaming 下的处理
- [Anthropic Tool Use 文档](https://docs.anthropic.com/en/docs/build-with-claude/tool-use) —— `tool_use` / `tool_result` 块结构与错误回填约定
- 2026 工程复盘（多家团队一致）：清晰工具描述对调用准确率的影响（+16% 量级），建议把 `description` 当 API 文档来写

---

## 发布检查

- [x] 代码实际跑过，输出贴进正文（mock 1→5→6；真实模式 amber 本机跑通；edge 验证异常+幂等）
- [x] 至少 2 条真实踩坑（实际 3 条：403 UA / PowerShell export / 变量对齐+Edit 静默）
- [x] 有数字/表格（messages 1→5；工具描述 +16% 方向参考；真实参数对照表）
- [x] 有 PHP / SQL 类比（DBA 出计划、PHPDoc、422 错误、Stripe 幂等键、Laravel 队列 unique、Guzzle concurrent）
- [x] 标题不标题党，但要有信息量
- [x] 结尾有引导（下一篇 / 仓库链接）
- [x] 本周写了 `DIALOGUE.md`（对话实录 + 可复现的 AI 引导脚本）
- [x] 本周写了 `DIALOGUE-QA.md`（逐轮问答底稿，只收技术相关）
- [x] PHP/Prism 重写如实标注推迟 W09，未假装写过
- [x] 工具描述 +16% 数据明确标注"非本课实测、方向参考"
