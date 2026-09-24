# W10 · 对话实录与复现指令

> MCP：让 Agent 连上你的系统。
> 本周是「引导学习（阶段1）→ 实操（阶段2）→ 反馈迭代（阶段3）→ 汇总产出（阶段4）」完整跑完的一周，但按「先 A 后 B」把 Streamable HTTP 实测拆成了紧随其后的 B 步。
> 提炼版；逐轮一问一答底稿见 [`DIALOGUE-QA.md`](./DIALOGUE-QA.md)。

---

## 一、对话实录（关键转折点）

### 1. 阶段1 引导：三小节 + 理解检查

按课程四阶段节奏，先讲透概念再动手：

- **W10 定位**：W03–W04 手搓的工具绑死在 Agent 进程里；MCP 把能力标准化成「可被任意客户端发现并调用的服务」，把 N×M 集成压成 N+M。
- **三原语**：Tools（模型主动调用，动作/函数，可带副作用）/ Resources（客户端触发，只读数据源，喂上下文）/ Prompts（用户触发，提示词模板）。
- **传输 + 2026-07-28 规范**：stdio vs Streamable HTTP；五大变化（无状态核心 / MRTR / Header 路由 / 可缓存 list / Tasks）；HTTP+SSE 弃用。

每节配理解检查。amber 两题全对：

> **查昨天新增用户数，定义成 Tool 还是 Resource？** → amber：「Tool，查询需要去调用数据查询能力，是需要模型主动去调用的功能」。✅
> **远程 Laravel 后台调，传输选 stdio 还是 Streamable HTTP？** → amber：「Streamable HTTP；stdio 需要和调用端处于同一环境，更适合本地调试或者桌面应用，远程的 Laravel 后台无法调用本地 stdio 模式的 MCP server」。✅

### 2. 阶段2 实操：把 W09 成果包成第一个 Server

复用 W09 的 `db.py` / `query.py` / `indicators_seed.json`，用 FastMCP v4 把 `query_indicator` 包成 `@mcp.tool`、`fin://schema` 包成 `@mcp.resource`，业务逻辑零重写。

**环境坑（已记录）**：managed venv 装 `fastmcp==4.0.3` 首次失败，根因是 site-packages 里的损坏半安装包 `~yper`（原 typer）干扰 pip，删掉后重装成功。无头验证（`evidence.py`）意外发现**沙箱能连本机 MySQL**，真查到茅台 2025 归母净利 86228000000 元（L1, conf 1.0）——不是优雅报错。

### 3. 阶段3 反馈：FastMCP v4 + Inspector 三坑全踩

amber 本机起 Inspector 试调，连踩三个 v4 专属坑，每个都有真实终端输出作证：

1. **`fastmcp dev .\mcp_fin_server.py` 报 Unknown command** —— v4 把 `dev` 改成命令组，必须 `fastmcp dev inspector <file>`。
2. **Connect 报 `File not found: ...\.mcp_fin_server.py`** —— Arguments 栏的 `.\` 反斜杠被传参链路吃掉，变成 `.mcp_fin_server.py` 隐藏文件。
3. **`read_resource` 返回属性是 `.text` 不是 `.content`** —— v4 结构变化，验证脚本要双兼容。

改完 Arguments 为 `run mcp_fin_server.py` 后 Connect 正常，Run tool 返回完整茅台数据，**阶段 3 通过**。

---

## 二、给 AI 的复现指令（可直接复制）

下面这段 prompt 丢给任意 AI，就能以同样的方式带你走一遍 W10：

```
我要学 Agent 开发第 10 周：MCP（Model Context Protocol）—— 让 Agent 标准化地接入我的系统。

教学要求：
1. 分段推进，每小节讲完停下等我反馈，不要一次倾倒全部。
2. 一切以我的真实终端输出为准，不许编造"跑通了"。
3. 禁止问卷式提问；讲新概念先挂到 PHP/Laravel/SQL 类比（我是 PHP 全栈，Python 入门）。
4. 踩坑必须有真实终端输出作证，否则算没发生。
5. 先让我预测结果，再让我跑代码验证（先预测再验证）。

本周目标：
- 三原语：Tools（模型主动调用）/ Resources（只读数据源，客户端注入）/ Prompts（用户一键模板）。模型看不到 Resource。
- 两种传输：stdio（子进程，本地首选）vs Streamable HTTP（独立服务，远程首选）。远程调用端调不了本机 stdio。
- 2026-07-28 新规范五大变化（无状态核心 / MRTR / Header 路由 / 可缓存 list / Tasks）；HTTP+SSE 弃用。
- 实操：用 FastMCP v4 把已有的「查 MySQL 指标」函数包成第一个 MCP Server（tool + resource + prompt），stdio 跑通，再用 Inspector 试调。

请先讲「为什么 MCP 把 N×M 集成压成 N+M」，再讲三原语，然后带我写代码并本机验证。
```

---

## 三、方法论总结（哪些有效，哪些没做好）

**有效的手法**
- **三原语用 PHP/Laravel/SQL 类比**：MCP = 工具调用层的 PSR、Resource 类比 Eloquent Model、Prompt 类比 Blade 模板——amber 是 PHP 出身，这类比一打就通，理解检查两题全对。
- **理解检查前置**：每节末尾让 amber 先给结论再展开，暴露了他的直觉是否准确（两题都答对了，说明基础扎实）。
- **复用而非重写**：把 W09 的 `query_indicator` 直接包成 tool，业务逻辑零改动——这本身就是 MCP 价值的活教材。
- **踩坑必须终端输出**：FastMCP v4 的三个坑（dev 子命令 / `.\` 路径 / `.text` 属性）每个都先贴真实报错再下结论。

**没做好的 / 下次的改进**
- **B 步拆分**：本周按「先 A 后 B」把 Streamable HTTP 实测 + 第二个 Server + Tasks 拆到了收尾之后。周正文已诚实标注这部分未做，但 BUILD 节奏上略显割裂——下次同类「理论+实操+延展」周，可以在开周时就明确告知学员哪些属于延展、不在本周验收内。
- **第二 Server / Tasks 未动手**：课表规划了「2 个 Server + 一次 Tasks 长任务」，本周只交付了「只读查 MySQL」这一个。同构的第二个 Server 和 Tasks 模式留 B 步或 W11 补，正文已如实披露。
- **FastMCP v4 CLI 坑可前置预防**：`dev inspector` 子命令、`read_resource` 的 `.text` 属性都是 v4 专属变化，如果实操前先给一段"FastMCP v4 三忌"提示，能省一轮调试。
