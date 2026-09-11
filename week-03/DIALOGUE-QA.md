# W03 · 学习对话逐轮底稿（DIALOGUE-QA）

> 这是 W03 的**逐轮一问一答底稿**，未做归纳压缩。
> 只收技术相关问答；制定规则、调整课表、产出管理这类元话题不收。
> 完整提炼版见 [DIALOGUE.md](DIALOGUE.md)。

---

### 第 1 轮 · 触发

**amber**：开始W03课程

**我**：按约定走「阶段1 引导学习」：先读课表 W03 条目和上次进度，逐小节讲、每节停下等反馈。读 `agent-course-weekly-workflow.md` / `CURRICULUM.md` / `PROGRESS.md`，并联网核对 2026 年 tool use 现状（确认课表不过时）。进入第 1 节讲解：循环机制（LLM 不执行函数只产生调用意图、messages 变长、while 骨架三细节）。

---

### 第 2 轮 · 第 1 节反馈

**amber**：1. 只负责规划，不负责实际执行；2.都能理解；3.规划和执行结果通过tool_call_id，进行关联，告诉模型规划内容和执行结果；

**我**：第 1 节过关。精度修正：第 3 点——模型早就知道自己规划过什么（assistant 消息一直留着），`tool_call_id` 的真正意义是**锚点**，让模型把"结果"精确贴回"当初那个意图"，对不上就崩。规则：assistant 消息原样留着 + tool 消息回传同 id，缺一不可。进入第 2 节。

---

### 第 3 轮 · 第 2 节讲解 + 反馈

**我**：讲粒度/命名/描述——描述是给模型看的唯一 API 文档（类比 PHPDoc），引用 2026 复盘 +16% 数据（标注非本课实测）；命名动词+名词；粒度一个能力一工具。让他给"查 MySQL 订单"写一句 description。

**amber**：1.会，会更重视工具的使用场景描述注释以及入参说明；2. 查mysql最好按模块划分，例如查询订单信息工具的描述：用于查询商城订单数据，根据用户提供的订单编号或用户id进行查询，当需要获取对应订单数据时使用；

**我**：过关。他这句三要素（做什么+怎么查+何时用）齐全，属甜点区。微调加具象场景"发货状态"，点出"按模块划分"正是粒度甜点区落地。进入第 3 节。

---

### 第 4 轮 · 第 3 节讲解 + 反馈

**我**：失败必须转字符串回填，绝不抛异常（类比 Laravel 422 错误响应）；"查 MySQL"是头号异常源；埋伏笔：步数上限（W04 防护）；种安全钩子：别让模型传 raw SQL（W15 打）。问哪个工具最可能抛异常。

**amber**：1.能理解；2.查mysql；

**我**：准确。进入第 4 节。

---

### 第 5 轮 · 第 4 节讲解 + 反馈

**我**：并行调用（独立只读并发，类比 Guzzle concurrent）；陷阱 allSettled+per-call timeout；幂等性（写操作重试双发，类比 Stripe Idempotency-Key / Laravel 队列 unique）；幂等键从操作内容派生非随机 UUID；决策矩阵。问是否认同分类。

**amber**：1.理解；2.认同；

**我**：四节全过，阶段1 收工。进入阶段2 实操三步走（① 零框架 Python 循环 mock 可跑 ② 真实 API ③ PHP/Prism 重写）。我先写 `w03-scratch/agent.py` 并自测。

---

### 第 6 轮 · 写代码 + 自测

**我**：创建 `w03-scratch/agent.py`（纯 stdlib，3 工具 get_weather/query_order/send_notification）。自测：

```
# --mock 第一次（有 bug：to 抓成 "U1001说内容为"）
# 修了正则：\w+ 把中文算进去，改成 [A-Za-z0-9]+ 后：
$ python agent.py --mock
第 1 轮 | messages 当前共 1 条
  -> 执行工具 get_weather({"city": "北京"})
  <- 回填: {"city": "北京", "date": "今天", "weather": "晴", "temp": "24°C"}
  -> 执行工具 query_order({"order_id": "NO20260911001"})
  <- 回填: {"order_id": "NO20260911001", "user_id": "U1001", "status": "已发货", "amount": 299.0}
  -> 执行工具 send_notification({"to": "U1001", "message": "您的订单已发货"})
  <- 回填: 已向用户 U1001 发送通知：您的订单已发货
第 2 轮 | messages 当前共 5 条
模型最终回答：三件事都已完成...

# --edge：验证 ③ 异常转字符串 + ④ 幂等去重
-> query_order({})  -> "Error: ValueError: 必须提供 order_id 或 user_id 至少一个"
-> send_notification 同内容两次 -> 第二次 "[幂等去重] 该通知已发送过，跳过重复发送"
```

让他在本机跑 `--mock` / `--edge` 确认。

---

### 第 7 轮 · PowerShell export 报错

**amber**：执行 `export OPENAI_API_KEY=xxx` 时报错 `export : The term 'export' is not recognized as the name of a cmdlet, function, script file, or operable program...`

**我**：PowerShell 和 Git Bash 语法差异。`export` 是 bash 命令，PowerShell 用 `$env:变量 = "值"`。给出三行：

```powershell
$env:OPENAI_API_KEY = "你的中转站Key"
$env:OPENAI_BASE_URL = "https://你的中转站地址/v1"
$env:OPENAI_MODEL = "deepseek-v4-flash"
```

并告知 `$env:XXX` 只在当前 PowerShell 会话有效（用完即焚，符合密钥只从环境变量读的约定）。

---

### 第 8 轮 · 统一 bat 配置

**amber**：之前设置的 start-env-windows.bat 已经配置这个三个参数，如果统一一下，都利用里面的配置，避免重复设置

**我**：读 `tools/start-env-windows.bat` 和 `agent.py`。确认根因：bat 设的是 `API_KEY/BASE_URL/MODEL`（无前缀），agent.py 原读 `OPENAI_API_KEY`（带前缀），名字对不上导致 bat 配好的读不到。改为优先 `OPENAI_*` 前缀、回退无前缀 `API_KEY/BASE_URL/MODEL`。

**踩坑**：Edit 工具报 Success，但 `real_llm` / `main` 两处旧代码**未写入**（本系列第三次：W01/W02 各一次）。改用 Python `replace()` + `assert` 强制改并独立读盘校验才生效。

**验证**：

```
$ export API_KEY=dummy BASE_URL=https://example.com/v1 MODEL=dummy
$ python agent.py
# 不再打印"自动切换到 mock"，而是进入真实分支请求 example.com（沙箱屏蔽外网才 Traceback）
```

证明无前缀 `API_KEY` 被正确读取。清理临时 patch 脚本。

---

### 第 9 轮 · 真实模式 403

**amber**（完整贴出）：

```
PS <workspace> python w03-scratch/agent.py
演示输入： 帮我查一下北京天气，再查订单 NO20260911001，然后通知用户U1001说内容为：您的订单已发货
===== 第 1 轮 | messages 当前共 1 条 =====
Traceback (most recent call last):
  ...
  File "...\urllib\request.py", line 613, in http_error_default
    raise HTTPError(req.full_url, code, msg, hdrs, fp)
urllib.error.HTTPError: HTTP Error 403: Forbidden
```

**我**：好消息——能进真实分支说明变量名对齐生效（否则先报"缺环境变量"）。坏消息——403 是服务器明确拒绝。urllib 只抛裸 403，我加诊断：标准 `User-Agent` 头（中转站常对 `Python-urllib/3.x` 直接 403）+ 捕获 `HTTPError` 打印打码 key / 完整 URL / 响应体前 800 字。

---

### 第 10 轮 · curl 能连的线索

**amber**：之前直接 `curl.exe` 是正常能连接 AI 的

**我**：锁定根因就是 User-Agent 被 WAF 拦。对比：

| 客户端 | 默认 UA | 中转站态度 |
|---|---|---|
| `curl.exe` | `curl/8.x` | ✅ 放行 |
| Python `urllib` | `Python-urllib/3.13` | ❌ 常当异常脚本客户端拦截 |

`agent.py` 已加 `User-Agent: Mozilla/5.0 (compatible; w03-agent/1.0)`（第 209 行），浏览器风格合法标识，多数 WAF 放行。让他重跑。

---

### 第 11 轮 · 真实模式跑通

**amber**（完整贴出）：

```
演示输入： 帮我查一下北京天气，再查订单 NO20260911001，然后通知用户U1001说内容为：您的订单已发货
===== 第 1 轮 | messages 当前共 1 条 =====
-> 执行工具 get_weather({"city": "北京"})
<- 回填: {"city": "北京", "date": "今天", "weather": "晴", "temp": "24°C"}
-> 执行工具 query_order({"order_id": "NO20260911001"})
<- 回填: {"order_id": "NO20260911001", "user_id": "U1001", "status": "已发货", "amount": 299.0}
-> 执行工具 send_notification({"to": "U1001", "message": "您的订单已发货"})
<- 回填: 已向用户 U1001 发送通知：您的订单已发货
===== 第 2 轮 | messages 当前共 5 条 =====
模型最终回答： 三件事都已完成，结果如下：
**1. 北京天气** ... 今天：晴，气温 24°C ...
**2. 订单 NO20260911001** ... 订单状态：已发货 ...
**3. 通知发送** ... 已向用户 U1001 发送通知：「您的订单已发货」✅
顺便提醒一下：该订单（U1001）的状态正好就是「已发货」，所以这条通知内容和实际状态是吻合的...
```

**我**：步②真实 tool_call 循环跑通。做验收讲解，指出 4 个学习点：① 模型自己选 3 工具造参数（和 mock 硬匹配本质不同）② messages 1→5 验证 W02 担心的暴涨 ③ 3 个 tool_calls 一次性返回但代码串行执行（执行策略是你的选择，非模型决定）④ 模型第 2 轮基于工具返回做了推理（"订单状态已发货，通知吻合"）。问步③路线。

---

### 第 12 轮 · 收尾决策

**我**（AskUserQuestion）：步②已跑通。步③用 PHP+Prism 重写，现在做还是先收尾本周？给出三选项：现在写 PHP/Prism（推荐）/ 先收尾 W03 推迟 PHP 到 W09 / 先跑真实边界场景再定。

**amber**：先收尾 W03，PHP 推迟到 W09

**我**：接受决策。进入阶段4 汇总产出：归档 `week-03/code/agent.py` + 写 `week-03/README.md` + `DIALOGUE.md` + `DIALOGUE-QA.md` + 根目录 `week-03-learning-log.md` + 更新 `PROGRESS.md`。PHP/Prism 对照留 W09（框架周），正文与对话文件均如实标注未假装写过。

---

## 附：本周真实终端证据索引

| 证据 | 位置 | 说明 |
|---|---|---|
| mock 模式 messages 1→5→6 | 第 6 轮 / README 第七节 | 循环跑通，messages 暴涨复现 |
| `--edge` 异常+幂等 | 第 6 轮 / README 第七节 | ③ 异常转字符串 ④ 幂等去重 |
| 403 Forbidden Traceback | 第 9 轮 | urllib 默认 UA 被 WAF 拦截 |
| `curl.exe` 能连 | 第 10 轮 | 对照定位 UA 根因 |
| 真实模式跑通输出 | 第 11 轮 | 模型自己选工具造参数，基于结果推理 |
| PowerShell `export` 报错 | 第 7 轮 | bash/PowerShell 语法差异 |
| Edit 静默未写入 | 第 8 轮 | 长文件改动需 replace+assert+读盘校验 |

> 所有 Key 均来自 `start-env-windows.bat` 注入或会话内 `$env:`，未写入任何文件。提交前已做红线扫描（`*.md`/`*.py`/`*.json`/`*.bat`/`*.sh` 全类型），无内部项目名、无 `sk-` 明文 Key。
