# W10 · 代码运行说明（MCP Server：把财报查询暴露成协议标准能力）

> 配套正文 [`../README.md`](../README.md)。本目录是 W10 阶段 2 实操 + B 步 HTTP 远程实测的可运行产物。
> 环境：Python 3.13 + FastMCP 4.0.3 + PyMySQL 1.2（managed venv 已装）。

## 依赖

```bash
pip install "fastmcp==4.0.3" pymysql httpx
```

> ⚠️ FastMCP 是 v3→v4 大改写，`pip install fastmcp` 不锁版本会自动升到最新大版、装饰器 API 可能变。**务必 pin `==4.0.3`**。

## 文件说明

| 文件 | 作用 |
|---|---|
| `mcp_fin_server.py` | **主文件**：FastMCP Server。`@mcp.tool query_indicator` 包 W09 的查询；`@mcp.resource fin://schema` 暴露科目字典；`@mcp.prompt 生成财报周报` 用户一键模板。支持两种模式：`MCP_MODE=stdio`（默认，Inspector/子进程）/ `MCP_MODE=http`（独立 HTTP 服务，stateless） |
| `fin_agent_client.py` | **调用端**：用 `httpx` 手写 MCP Streamable HTTP 协议（`initialize → notifications/initialized → tools/list → tools/call`）。这是你 W09「Laravel 后台调用端」在 MCP 世界的等价物，地址走 `MCP_BASE` 环境变量（默认 `http://127.0.0.1:8000/mcp`） |
| `db.py` | W09 复用：MySQL 连接（读 `FIN_DB_*` 环境变量，默认 `127.0.0.1:3306` root 空密码 `fin_agent`） |
| `query.py` | W09 复用：`query_indicator(company_code, year, matched_code)`，白名单表 + 参数化，不拼 SQL |
| `indicators_seed.json` | W09 复用：11 个标准科目字典（OPER_REV / NP_PARENT / NP_DEDUCT / DILUTED_EPS …） |
| `evidence.py` | 无头验证：用 in-memory Client 验证 `list_tools` / `read_resource` / `call_tool` / `list_prompts`，结果 UTF-8 落 `verify_evidence.txt` |
| `verify_server.py` | 早期验证脚本（同思路，无 prompt 项） |
| `verify_http_final.py` | **B 步验证**：独立子进程起 HTTP 服务 + `fin_agent_client` 调，结果落 `verify_http_final_evidence.txt` |
| `verify_evidence.txt` | stdio 实证输出：工具/资源/真实查库/模板 四项全过 |
| `verify_http_final_evidence.txt` | HTTP 远程实证输出：stateless 全链路走通 |

## 运行（三种方式）

### 1. 无头验证（CI / 不依赖客户端）

```bash
python evidence.py          # 必须先 cd 到本目录（indicators_seed.json 是相对路径）
cat verify_evidence.txt
```

### 2. stdio 本地调试（Inspector）

FastMCP v4 的 `dev` 是命令组，必须写 `inspector` 子命令，文件作位置参数：

```bash
fastmcp dev inspector mcp_fin_server.py
```

> ⚠️ Inspector 的 Arguments 栏**不要写** `.\mcp_fin_server.py`（PowerShell 风格 `.\` 反斜杠会被传参链路吃掉，变成 `.mcp_fin_server.py` 找不到文件）。写 `run mcp_fin_server.py`，或正斜杠绝对路径 `run D:/.../mcp_fin_server.py`。

浏览器打开 Inspector → Connect → 选 `query_indicator` → 填 `company_code=600519 / year=2025 / matched_code=NP_PARENT` → 返回茅台 2025 归母净利润 `86228000000` 元（method=L1, confidence=1.0）。

### 3. Streamable HTTP 远程版（让独立部署的客户端 / Laravel 后台连）

**启动服务**（默认 8000，可用 `MCP_PORT` 改端口）：

```bash
MCP_MODE=http python mcp_fin_server.py        # Windows PowerShell: $env:MCP_MODE="http"; python mcp_fin_server.py
```

服务以 **stateless 模式**（`mcp.http_app(stateless_http=True)`）启动 —— 这是 2026-07-28 规范的无状态核心，每请求独立、无需 session，天然可水平扩展，也避开了 FastMCP v4 有状态模式的 session 回收坑。

**用调用端连**：另开一个终端

```bash
python fin_agent_client.py                    # 自动连 MCP_BASE（默认 http://127.0.0.1:8000/mcp）
```

`fin_agent_client.py` 输出：`initialize → list_tools(['query_indicator']) → call_tool(...) → 贵州茅台 2025 归母净利 86228000000 元`。

> ⚠️ **为什么不用 FastMCP Client 的 streamable-http transport**：v4.0.3 在发第二个请求时会把完整 URL 错误地再拼一次（服务端日志出现 `POST http%3A//127.0.0.1%3A8000/mcp` 404），是该版本的 client/server 配合 bug。本调用端改用 `httpx` 直接发 JSON-RPC，反而更贴近协议本质。你未来的 Laravel 端用 Guzzle 同样发这几段即可。
>
> ⚠️ **端口一致**：调用端地址走 `MCP_BASE` 环境变量，必须和服务的 `MCP_PORT` 对应（默认都是 8000），否则连错端口 `tools/list` 会返回空。

### 4. 一键跑通 HTTP 全链路验证

```bash
python verify_http_final.py     # 自动起服务子进程 + fin_agent_client 调 + 落 verify_http_final_evidence.txt
```
