# W10 · MCP：让 Agent 连上你的系统

> Agent 开发实战 15 周 · 第 10 周 · 约 6 小时
>
> 一句话钩子：**你每接一个 AI 客户端就重写一遍数据库集成？MCP 把「N 个客户端 × M 个系统」压成「N + M」——它是 AI 工具调用这层的 PSR。**

## 开篇：这周要解决什么问题

回顾你走过的路：

- W03–W04：手搓 Agent 循环，工具是**写在 Agent 代码里的 Python 函数**（查天气 / 查订单 / 发通知）。
- W08：用 LangGraph 把循环工程化。
- W09：把这套引擎套到财报场景，做出毕业项目 MVP——Python 服务跑抽取+归一化，Laravel 当调用端。

W10 要解决的问题是：**工具现在「绑死」在 Agent 进程里**。你想让另一个客户端（Claude Desktop、Cursor、或者你自己的 Laravel 后台）也能用「查 MySQL」「调业务 API」这些能力，就得把同一套逻辑再写一遍。结果是 **N 个客户端 × M 个系统 = N×M 份重复集成**。

MCP 就是来把这个「N×M」压成「N+M」的。

## 核心结论（先给答案）

1. **MCP 是开放协议，不是框架**：它统一了「AI 客户端」和「你的系统」两端，任何遵守协议的客户端插上任何遵守协议的服务端就能用——像 PSR 标准出来后，实现 PSR 接口的组件谁都能用。
2. **三原语是本周最高频考点**：Tools（模型主动调用去干一件事）/ Resources（只读数据源，客户端注入上下文）/ Prompts（用户一键触发的模板）。模型**看不到** Resource，是客户端喂进来后模型才「读到」。
3. **两种传输**：stdio（Server 是 Host 拉起的子进程，零网络零认证，本地/桌面首选）；Streamable HTTP（Server 是独立 HTTP 服务，远程多客户端共享）。**远程调用端调不了本机 stdio 子进程**——这是选型的分水岭。
4. **2026-07-28 规范是最大改版**：无状态核心（砍 `initialize` 握手，请求自带 `_meta`）、MRTR 多轮往返、Header 路由、可缓存 `list` 结果（渐进式披露控 token）、Tasks 扩展；HTTP+SSE 已弃用。写新 Server 直接按新规范。
5. **MCP Server 是薄壳**：不重写业务逻辑，把现有函数/数据按协议标准「暴露」出去即可——本周就把 W09 的 `query_indicator` 包成了第一个 Server，真实查到了茅台数据。

## 一、概念：MCP 到底是什么

### 1.1 心智模型：MCP = "AI 的 USB-C" / 工具调用层的 PSR

MCP（Model Context Protocol）是一个**开放协议**，统一了两端：

- **Host / Client（客户端）**：AI 应用——Claude Desktop、Cursor、你的 LangGraph Agent、Laravel 后台。
- **Server（服务端）**：你的系统——MySQL、业务 API、文件系统。

没 MCP 之前，每个 AI 应用要接你的数据库，都得自己写私有集成（就像每个 PHP 框架早年各自发明一套 DB 连接写法）。有 MCP 之后，只要双方都遵守同一协议，任何客户端插上任何服务端就能用（像 PSR 标准出来后，实现 PSR 接口的组件谁都能用）。

> **PHP/Laravel 类比**：你 W09 在 Laravel 里手写了一遍「消费 Python 服务的 HTTP 客户端 + SSE 转发」。那套逻辑如果每个系统都各写一遍会很痛。MCP 把「我能提供什么能力、怎么被调用、参数怎么描述」标准化了——这就是 AI 工具调用这层的 **PSR**。

### 1.2 三原语（必须记住的核心）

| 原语 | 是什么 | 谁决定"什么时候用" | PHP/Laravel 类比 |
|---|---|---|---|
| **Tools** | 可被模型调用的「动作/函数」，带参数、有返回值，可带副作用 | **模型**自己决定调用（选工具 + 造参数） | Controller action / Artisan command / API endpoint |
| **Resources** | 可被「读取」的数据，喂给模型当上下文 | **客户端/用户**触发，模型不主动决定 | Eloquent Model / 一张表的一行 / 只读 API 返回的 JSON |
| **Prompts** | 预写的提示词模板，用户点一下触发 | **用户**触发（不是模型自动调） | Blade `@include` 片段 / 邮件模板 / Notification 模板 |

关键区分：**Tools 是「模型主动调用去干一件事」；Resources 是「把数据拉来给模型看」；Prompts 是「给用户的一键模板」**。

拿你 W09 财报场景举例：
- **Tool**：`query_indicator(company, year, indicator)` —— 模型判断「用户问了扣非净利润，我要调这个工具」。
- **Resource**：`fin://schema` —— 客户端把科目字典拉来当上下文，模型不会「调用」它，是客户端喂进来。
- **Prompt**：`生成财报周报` —— 你点一下，套一个预写好的提示词模板。

### 1.3 传输 + 2026-07-28 新规范

**两种传输**

| 传输 | 怎么通信 | 何时用 |
|---|---|---|
| **stdio** | Host 把 Server 当**子进程**拉起来，通过 stdin/stdout 走 JSON-RPC | 本地调试 / 桌面客户端（Claude Desktop）首选；零网络、零认证 |
| **Streamable HTTP** | Server 是**独立 HTTP 服务**，客户端 POST 调 | 要远程 / 多客户端 / 上云；2026-07-28 后**唯一**的远程传输 |

一句话区分：**stdio 的 Server 和客户端在同一台机器、同一进程树；Streamable HTTP 的 Server 是独立服务，任何能发 HTTP 的客户端都能连。**

**2026-07-28 规范五大变化**（已联网核实）

1. **无状态核心**：砍掉 `initialize` 握手和 `Mcp-Session-Id`。每个请求**自带**协议版本、客户端身份、能力，全塞进 `_meta` 字段。→ 任意请求可落到负载均衡后面任意实例，不需要 Redis、不需要 sticky session（像你平时写的 stateless REST 请求，天然可水平扩展）。
2. **MRTR（Multi Round-Trip Requests）**：取代原来要「一直开着双向流」才能做的 server→client 请求（追问用户、sampling、roots）。工具中途需要用户输入时，返回 `input_required`，客户端把答案带回来**重发原请求**。
3. **Header 路由**：Streamable HTTP 请求必须带 `Mcp-Method` 和 `Mcp-Name` 头。网关 / WAF / 限流器直接读头路由，**不用解析 JSON body**（像你 Laravel 路由用 HTTP method + URI 分发，而不是去解析请求体里的字段）。
4. **可缓存的 list 结果**：`tools/list`、`resources/list`、`prompts/list` 现在带 `ttlMs` + `cacheScope`。客户端可以缓存工具目录、保持上游 prompt cache 稳定——这就是课表说的**「渐进式披露控 token（实测 15 万 → 2 千）」**。
5. **Tasks 扩展**：长任务不再靠一直开连接，而是走 task 生命周期（`tasks/get`、`tasks/update`、`tasks/cancel`）轮询。

**弃用清单**：HTTP+SSE 远程传输正式弃用（最早 2027-07 才移除）；Sampling 被弃用；**stdio 不受影响**。12 个月过渡期——所以你写新 Server **直接按新规范，别碰已弃用的 SSE**。

**FastMCP 现状**（联网核实）：现由 Prefect 维护，v4.0.3 稳定（2026-09 当前）。`from fastmcp import FastMCP` + `@mcp.tool/@mcp.resource/@mcp.prompt` 装饰器 API 稳定。

## 二、动手：把 W09 成果包成第一个 FastMCP Server

### 2.1 为什么是「包一层」而不是重写

你 W09 踩过的坑（语义相似块误匹配、白名单防注入）都还在 `query_indicator` 里。MCP 的价值是**复用**这套能力，让任何客户端（Claude Desktop / Cursor / 你未来的 Laravel 后台）都能标准化调用它。

一句话：**MCP Server = 一个「把现有函数/数据，按协议标准对外暴露」的薄壳**。壳很薄，业务逻辑全在壳里面复用。

### 2.2 stdio 版（本地调试首选，零网络零认证）

直接复用你 W09 的 `db.py` + `query.py`：

```python
# mcp_fin_server.py
from fastmcp import FastMCP
import db            # W09 的 MySQL 连接
import query         # W09 的 query_indicator

mcp = FastMCP("fin-agent")   # Server 名，客户端 list 时看到的就是它


@mcp.tool()
def query_indicator(company_code: str, year: int, matched_code: str) -> dict:
    """按 公司代码 + 年度 + 标准科目 code 查已归一化落库的值。

    返回：单行字典（company, code, year, matched_code, value, unit, method, confidence）
          查不到或出错时返回 {'error': '...'}，不会让 Server 崩溃。
    """
    try:
        row = query.query_indicator(company_code, year, matched_code)
        return row if row else {"error": "no match"}
    except Exception as e:   # 连不上库 / SQL 错：优雅返回，而非抛异常崩 Server
        return {"error": f"{type(e).__name__}: {e}"}


@mcp.resource("fin://schema")
def fin_schema() -> str:
    """只读：标准科目 code 清单，供模型选型参考。"""
    import json
    with open("indicators_seed.json", encoding="utf-8") as f:
        items = json.load(f)
    return "\n".join(f"{i['code']} = {i['name']}" for i in items)


@mcp.prompt()
def 生成财报周报(company_code: str, year: int) -> str:
    """一键生成「财报周报」提示词模板：引导模型先读 fin://schema 选科目，再调 query_indicator。"""
    return (
        f"请为股票 {company_code} 的 {year} 年度报告撰写一份财报周报。\n\n"
        "步骤：\n1. 读取 fin://schema 资源了解可用科目 code\n"
        "2. 调用 query_indicator 拉取 OPER_REV(营业总收入)/NP_PARENT(归母净利润)/NET_PROFIT(净利润)\n"
        "3. 汇总金额、单位、method(L1=精准命中)、confidence\n"
        "4. 按「经营概况/盈利质量/风险提示」三段输出\n"
    )


if __name__ == "__main__":
    mcp.run()                        # 默认 stdio
    # mcp.run(transport="http", host="127.0.0.1", port=8000)   # 远程版
```

**对照三原语**：`@mcp.tool` → 模型主动调；`@mcp.resource` → 只读被读取；`@mcp.prompt` → 用户点选触发。

### 2.3 怎么验证它能跑（MCP Inspector）

FastMCP v4 的 `dev` 是命令组，必须写 `inspector` 子命令，文件作位置参数：

```bash
fastmcp dev inspector mcp_fin_server.py
```

浏览器打开 Inspector → Connect → 选 `query_indicator` → 填参数点 Run，看到返回即通。

### 2.4 Streamable HTTP 版（一句话切换）

把 `mcp.run()` 换成 `mcp.run(transport="http", port=8000)`，Server 就变成独立 HTTP 服务。此时**你 W09 那个 Laravel 后台不必再 spawn 子进程**，只要能发 HTTP 就能连——这正是解决「远程调用端调不了 stdio」的方案。

## 三、踩坑记录

### 坑 1：managed venv 装 fastmcp 被损坏半安装包干扰

- **现象**：`pip install fastmcp==4.0.3` 报 `WARNING: Ignoring invalid distribution ~yper`，实则安装中途失败，import 时报 `ModuleNotFoundError`。
- **原因**：site-packages 里有个**损坏的半安装包 `~yper`**（原 `typer`）在干扰 pip 的依赖解析/写入。
- **解法**：`Remove-Item ~yper ~yper-0.27.2.dist-info` 后重装 `EXIT:0`，`import fastmcp` 成功。

### 坑 2：FastMCP v4 的 `dev` 必须加 `inspector` 子命令

- **现象**：`fastmcp dev .\mcp_fin_server.py` 报 `Unknown command ".\mcp_fin_server.py". Available commands: inspector, apps`。
- **原因**：v4 把 `dev` 改成了命令组，下面只有 `inspector` / `apps` 两个子命令，`.\mcp_fin_server.py` 被当成 `dev` 的子命令名去匹配，当然没有。
- **解法**：`fastmcp dev inspector .\mcp_fin_server.py`（文件作位置参数跟在 `inspector` 后）。

### 坑 3：Inspector Arguments 栏的 `.\` 路径前缀会被吃掉

- **现象**：Connect 报 `File not found: ...\.mcp_fin_server.py` + `Server exited with code 1`。
- **原因**：Arguments 栏写 PowerShell 风格 `.\mcp_fin_server.py`，反斜杠在 Inspector→子进程的传参链路里被转义吃掉，路径变成 `.mcp_fin_server.py`（一个不存在的隐藏文件）。
- **解法**：Arguments 去掉 `.\` 前缀写 `run mcp_fin_server.py`，或用正斜杠绝对路径 `run D:/.../mcp_fin_server.py`。**跨工具传 Windows 路径一律用正斜杠、不带 `.\` 前缀。**

### 坑 4：FastMCP v4 的 `read_resource` 返回属性是 `.text` 不是 `.content`

- **现象**：无头验证脚本里 `getattr(c, "content", ...)` 取到空，资源计数显示成「1 个」。
- **原因**：v4 改变了返回对象结构，Resource 内容在 `.text` 属性上。
- **解法**：`getattr(c, "text", getattr(c, "content", str(c)))` 双兼容读取。

## 四、验收清单

对照 CURRICULUM 的 W10 验收标准（诚实标注进度）：

- [x] 说一句"查一下某公司的归母净利润"，能拿到真实数字 —— `query_indicator(600519, 2025, 'NP_PARENT')` 实查茅台 **86228000000 元（L1, conf 1.0）**，Inspector 里 Run tool 验证通过
- [x] 三原语齐全：Tools（`query_indicator`）/ Resources（`fin://schema`，11 个科目）/ Prompts（`生成财报周报`，渲染正常）
- [x] 两种传输讲透 + 2026-07-28 新规范五大变化联网核实
- [x] stdio 版 Inspector 本机验证通过
- [x] **Streamable HTTP 远程版**（B 步实测，**已走通**）：`MCP_MODE=http` 起独立 HTTP 服务（uvicorn @127.0.0.1:8000，**stateless 模式**），用 `fin_agent_client.py`（httpx 手写 MCP 协议）作为调用端，完成 `initialize → notifications/initialized → tools/list → tools/call` 全链路，实查茅台 2025 归母净利 **86228000000 元（L1, conf 1.0）**。这正是解决「远程调用端调不了 stdio 子进程」的实锤 —— 你的 Laravel 后台只要能发 HTTP 就能连。
- [ ] **第二个 Server（调业务 API）** —— 本周只做了「只读查 MySQL」这一个，课表规划的「调业务 API」Server 未做
- [ ] **一次 Tasks 长任务模式** —— 2026-07-28 Tasks 扩展未动手写

> 说明：本周按「先 A 后 B」拆成两步，现已全部完成。A（理论 + 1 个 Server + stdio 验证 + 收尾）已进仓；B（Streamable HTTP 远程实测）也已走通并补证。课表规划的「第二个 Server（调业务 API）」与「Tasks 长任务模式」仍留 W11 / 毕业项目补（同构、非阻塞）。

## 五、数据 / 实测结果

无头验证（`evidence.py` → `verify_evidence.txt`）与 Inspector 试调**双重印证**：

| 检查项 | 结果 |
|---|---|
| 已注册工具 | `['query_indicator']` ✅ |
| `fin://schema` 读取 | 11 个标准科目 code ✅ |
| `call_tool(600519/2025/NP_PARENT)` | 贵州茅台 2025 归母净利润 = **86228000000 元**（约 862.28 亿，method=L1, confidence=1.0000） ✅ |
| 已注册 Prompts | `['生成财报周报']` ✅ |

Inspector 实调返回（amber 本机）：

```json
{
  "company": "贵州茅台", "code": "600519", "year": 2025,
  "matched_code": "NP_PARENT", "value": "86228000000.000000",
  "unit": "元", "method": "L1", "confidence": "1.0000"
}
```

`method: L1` + `confidence: 1.0000` 说明走的是字段字典精准匹配——正是 W09 毕业项目硬指标「扣非/归母零误匹配」的验收数据，且**沙箱与 amber 本机结果一致**。

### Streamable HTTP（stateless）实测结果（B 步）

`verify_http_final.py` 用独立子进程起 HTTP 服务 + `fin_agent_client.py`（httpx 手写 MCP 协议）作为调用端，完成全链路：

| 步骤 | 结果 |
|---|---|
| 端口就绪（uvicorn @8123） | True ✅ |
| `initialize`（stateless，session=None，符合 2026-07-28 无状态规范） | ✅ |
| `notifications/initialized`（协议要求的握手通知） | ✅ |
| `list_tools` | `['query_indicator']` ✅ |
| `call_tool(600519/2025/NP_PARENT)` | 贵州茅台 2025 归母净利润 = **86228000000 元**（L1, conf 1.0）✅ |

证据见 `code/verify_http_final_evidence.txt`。这条链路证明：**任何能发 HTTP 的客户端（你的 Laravel 后台）都能连上这个 MCP Server**，彻底证伪了「远程调用端调不了本机 stdio 子进程」。

## 六、这周的取舍

**做了什么**
- W10 定位与三原语讲透，用 PHP/Laravel/SQL 类比（MCP=工具调用层 PSR；Resource 类比 Eloquent Model；Prompt 类比 Blade 模板）。
- 把 W09 的 `query_indicator` 包成第一个 FastMCP Server，tool/resource/prompt 三原语全部注册，业务逻辑零重写。
- stdio 版在 Managed venv 无头验证 + amber 本机 Inspector 双重通过，真查到茅台数据。
- 2026-07-28 新规范五大变化联网核实，FastMCP v4 CLI 三个坑全部踩实并记录。

**放弃了什么 / 为什么（诚实）**
- **第二个 Server（调业务 API）未做**：本周课时聚焦"把一个能力暴露成 MCP + 跑通 stdio 全链路 + 走通 HTTP 远程"，第二个 Server 是同构的（换一个 `@mcp.tool` 包你的业务 API 即可），留 W11 补。
- **Streamable HTTP 用 FastMCP Client 没跑通（已用 httpx 绕过）**：FastMCP v4.0.3 的 streamable-http transport 在发第二个请求时会把完整 URL 错误地再拼一次（服务端日志出现 `POST http%3A//127.0.0.1%3A8000/mcp` 404），这是该版本的 client/server 配合 bug。最终用 `httpx` 手写 MCP JSON-RPC（`fin_agent_client.py`）100% 走通，反而更贴近协议本质。若未来要用官方 Client，需等 FastMCP 修复或降/升版本。
- **Tasks 长任务模式未写**：2026-07-28 的 Tasks 扩展是本课表"做什么"里的要求，但需要一个长任务场景（如"异步导入一年财报"）来承载，留毕业项目 W15 或单独补。
- **Laravel 端 MCP Client 改造未做**：W09 的 Laravel 调用端现在是 SSE 转发，升级为 MCP Client 消费本 Server 是毕业项目延展（届时 PHP 端用 Guzzle 同样发这几段 JSON-RPC 即可），未动。

## 下一篇

W11 · **编排与协作：Skills → Handoff → Supervisor**。本周的 MCP 是"门卡"（能否访问你的系统）；W11 的 Skill 是"入职文档"（怎么用、按什么顺序）。两者配合，才能把"会调工具"升级为"会分工协作"。届时把本周第二个 Server + Tasks 长任务一并补上。

## 附录：学习对话实录

本周完整对话（含三原语理解检查、FastMCP v4 三个 CLI 坑、Inspector 试调）见：

- [`DIALOGUE.md`](./DIALOGUE.md) —— 提炼版：对话实录 + 给 AI 的复现指令 + 方法论总结
- [`DIALOGUE-QA.md`](./DIALOGUE-QA.md) —— 逐轮一问一答底稿（命令原文 + 终端输出）

代码见 [`code/`](./code/)：`mcp_fin_server.py`（FastMCP Server）+ 复用 W09 的 `db.py`/`query.py`/`indicators_seed.json` + 验证脚本。

## 附录：延伸阅读

- MCP 规范 2026-07-28（无状态核心 / MRTR / Header 路由 / Tasks）
- FastMCP 官方文档（v4：`dev inspector` 子命令、Streamable HTTP）
- PSR 标准（PHP 框架互操作的类比对象）

---

## 发布检查

- [x] 代码实际跑过，输出贴进正文（无头验证 + Inspector 实调双重印证）
- [x] 至少 2 条真实踩坑（4 条：损坏包 / dev 子命令 / `.\` 路径 / `.text` 属性）
- [x] 有数字/表格（茅台 862.28 亿 + 验证四项表）
- [x] 有 PHP/SQL 类比（MCP=PSR；Resource=Eloquent；Prompt=Blade）
- [x] 标题不标题党，有信息量
- [x] 结尾有引导（下一篇 W11 / 仓库链接）
- [x] 本周写了 `DIALOGUE.md`
- [x] 本周写了 `DIALOGUE-QA.md`

### 提交前必做：红线扫描

```bash
# 只扫 *.md / *.py 会漏！必须覆盖所有文本类型。
# 注：本模板文件自身会命中（关键词写在下面这行里），属正常，忽略即可。
grep -rlE "dd-admin|dd-api|ddLife|hope-garden|病历|CatchAdmin|dd_permissions" . \
  --include="*.md" --include="*.py" --include="*.json" --include="*.bat" --include="*.sh"

# 顺带查有没有把 Key 写进任何文件
grep -rn "sk-" . --include="*.json" --include="*.py" --include="*.md"
```

- [x] 红线扫描覆盖 `.md` `.py` `.json`（本周无 `.bat`/`.sh` 进仓）
- [x] 无 `sk-` 开头的真实 Key（`.env.example` 仅占位 `FIN_DB_PASS=` 为空，无 Key）
- [x] `.py` / `.md` / `.json` 全 LF
