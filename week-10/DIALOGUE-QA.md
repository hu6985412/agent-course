# W10 · 逐轮问答底稿（DIALOGUE-QA）

> 逐轮一问一答，不做归纳压缩。每轮给过的命令原文、终端输出均保留。
> 范围：W10 全部（阶段1 引导 → 阶段2 实操 → 阶段3 反馈 → 阶段4 收尾前的 FastMCP v4 / Inspector 三坑）。
> 元话题（课程走向讨论、产出管理）不收，见 [`DIALOGUE.md`](./DIALOGUE.md) 方法论部分。

---

### 轮 1 · 启动

**amber**：开始 W10 课程。

**老师**：进入阶段1 引导学习。先讲 W10 定位（MCP 把 N×M 集成压成 N+M）+ 三原语 + 两种传输 + 2026-07-28 规范，每节配理解检查，讲完停下等反馈。联网核实了 2026 现状：MCP 2026-07-28 规范已是最大改版（无状态核心 / Streamable HTTP 成唯一远程传输 / 旧 SSE 弃用）；FastMCP 现由 Prefect 维护，v4.0.3 稳定。

---

### 轮 2 · 三原语理解检查（Tools vs Resources）

**老师**：理解检查——Tools 和 Resources 最本质的区别是什么？用一句话说清「谁来决定什么时候用、以及模型是『调用它』还是『读取它』」。

**amber**：tools 可以自行很多其他操作，resources 只是数据源；tools 是模型主动调用；resources 是模型被动接收，读取，由客户端/用户触发。

**老师**：✅ 答对。补两点 precision：① Tool 可带副作用（写库/发API/删数据），Resource 约定只读；② 模型看不到 Resource——是客户端把 Resource 内容注入上下文后模型才「读到」它，模型不会主动说"我要读 resource X"。

---

### 轮 3 · 传输 + 2026 规范理解检查

**老师**：理解检查——把「查昨天新增用户数」做成 MCP 能力：1. 该定义成 Tool 还是 Resource？为什么？2. 如果想让远程的 Laravel 后台也能调它，传输选 stdio 还是 Streamable HTTP？为什么不能选另一个？

**amber**：1. tool，查询需要去调用数据查询能力，是需要模型主动去调用的功能；2. 传输选 Streamable HTTP；stdio 需要和调用端处于同一环境，更适合本地调试或者桌面应用，远程的 Laravel 后台无法调用本地 stdio 模式的 MCP server。

**老师**：✅ 两题全对。补一句易混淆的：本地调试时两个都能用（本机 LangGraph Agent 接本机 Server 用 stdio 最省事），只有「调用端和 Server 不在一台机器」才必须 Streamable HTTP。

---

### 轮 4 · 动手前确认

**老师**：进入阶段2 实操。先把 W09 的 `query_indicator` 真实代码看一眼（确认它是确定性、参数化、白名单表的安全查询），再问：1. 你 W09 的 fin_agent 库现在本机 MySQL 还在吗？2. 直接新建代码我帮你建 + 跑通，还是你想先自己照代码敲一遍？

**amber**：1. 还在；2. 直接新建，代码已看懂。

**老师**：收到。建任务清单，落 `w10-scratch/mcp_fin_server.py`（复用 W09 的 db.py/query.py/indicators_seed.json），managed venv 装 fastmcp==4.0.3 跑通。

---

### 轮 5 · 环境坑：损坏半安装包干扰 pip

**老师**（贴 pip 日志）：`pip install fastmcp==4.0.3` 首次失败，`WARNING: Ignoring invalid distribution ~yper`，import 报 ModuleNotFoundError。根因：site-packages 有损坏半安装包 `~yper`（原 typer）。已 `Remove-Item ~yper ~yper-0.27.2.dist-info` 后重装成功，import fastmcp 4.0.3 ✅。

---

### 轮 6 · 无头验证（意外真查到数据）

**老师**（贴 verify_evidence.txt）：
```
[1] 已注册工具: ['query_indicator']
[2] fin://schema 读取成功: 共 11 个标准科目 code
[3] call_tool('query_indicator', 600519/2025/NP_PARENT) 实查结果:
    {'company': '贵州茅台', 'code': '600519', 'year': 2025, 'matched_code': 'NP_PARENT',
     'value': '86228000000.000000', 'unit': '元', 'method': 'L1', 'confidence': '1.0000'}
```
惊喜：沙箱能连你本机 MySQL（127.0.0.1:3306 root 空密码 fin_agent），是真数据非优雅报错。

---

### 轮 7 · 阶段3：fastmcp dev 报错

**amber**（贴终端）：
```
PS D:\WorkBuddyWorkspace\agent_workspace\w10-scratch> fastmcp dev .\mcp_fin_server.py
╭─ Error ──────────────────────────────────────────╮
│ Unknown command ".\mcp_fin_server.py". Available commands: inspector, apps.
```

**老师**：根因——FastMCP v4 把 `dev` 改成了命令组，下面只有 `inspector`/`apps` 两个子命令。你写的 `fastmcp dev .\mcp_fin_server.py` 把 `.\\mcp_fin_server.py` 当成 `dev` 的子命令名匹配，当然没有 → Unknown command。正确命令：`fastmcp dev inspector .\mcp_fin_server.py`（文件作位置参数跟在 `inspector` 后）。

---

### 轮 8 · 阶段3：Inspector Connect 报 File not found

**amber**（贴截图日志）：
```
[09/23/26 19:17:12] ERROR File not found: filesystem.py:69 D:\WorkBuddyWorkspace\agent_workspace\w10-scratch\.mcp_fin_server.py
[09/23/26 19:17:12] ERROR Server exited with code 1, waiting for file change...
```
Arguments 栏填的是 `run .\mcp_fin_server.py --no-ban`。

**老师**：根因——Arguments 栏写 PowerShell 风格 `.\mcp_fin_server.py`，反斜杠在 Inspector→子进程的传参链路里被转义吃掉，路径变成 `.mcp_fin_server.py`（一个不存在的隐藏文件）→ File not found + Server exited code 1。修法：Arguments 去掉 `.\` 前缀写 `run mcp_fin_server.py`，或用正斜杠绝对路径 `run D:/.../mcp_fin_server.py`。**跨工具传 Windows 路径一律用正斜杠、不带 `.\` 前缀。**

---

### 轮 9 · 阶段3：试调成功

**amber**（贴 Inspector Run tool 返回）：
```json
{
  "company": "贵州茅台", "code": "600519", "year": 2025,
  "matched_code": "NP_PARENT", "value": "86228000000.000000",
  "unit": "元", "method": "L1", "confidence": "1.0000"
}
```

**老师**：✅ 阶段3 通过。Inspector 真调 `query_indicator` 返回完整结果，与沙箱无头验证一致。`method: L1` + `confidence: 1.0000` 正是 W09 毕业项目硬指标「扣非/归母零误匹配」的验收数据。

---

### 轮 10 · 推进顺序决策

**amber**：先A 后B。

**老师**：收到。A = 收尾（补 `@mcp.prompt` 模板 + course-week-finalize 复制进 agent-course/week-10/code/ + 写 README/DIALOGUE/DIALOGUE-QA + 更新 PROGRESS）；B = Streamable HTTP 远程版实测（让 Laravel 后台能连）。先 A 后 B。

---

> 注：B 步（Streamable HTTP 远程实测 + 第二个业务 API Server + Tasks 长任务）按「先A后B」紧随 A 之后，属于 W10 延展，正文与 PROGRESS 已诚实标注未做，不在此底稿展开，待 B 步实际跑通后补录。
