# W04 · 带防护与审计的 Agent（代码运行说明）

本目录是 W04 的**完整可运行代码**：在 W03 零框架 `while` 循环基础上，叠加了
**ReAct 结构化记录 + 记忆三层 + 防护四件套 + 工具调用落库**，构成一个「生产可用」的 Agent。

## 文件

- `agent.py` —— 主程序（纯 Python 标准库 + `pymysql` 落库；无 `pymysql` 自动降级为不落库）

## 依赖

```bash
pip install pymysql     # 仅落库需要；不装也能跑（自动降级）
```

其余（`json` / `urllib` / `concurrent.futures` 等）均为标准库。

## 运行

### 无需 Key，立刻能跑（mock 模式）

```bash
python agent.py --mock            # 正常退款流程（订单已签收 -> 退款）
python agent.py --mock --order NO20260911002   # 不可退款分支（运输中）
python agent.py --mock --deadloop # 故意制造死循环，验证防护④（连续失败被拦）
python agent.py --mock --edge     # 演示：异常转字符串 / 幂等 / 重复拦截 / 超时熔断
```

### 真实 API 模式（需 Key）

双击仓库外的 `start-env-windows.bat`（已填好 Key，会注入 `API_KEY` / `BASE_URL` / `MODEL`），
在它弹出的窗口直接：

```bash
python agent.py
python agent.py --order NO20260911002     # 测不可退款分支
$env:W04_DEADLOOP=1; python agent.py       # 测死循环防护（PowerShell 语法）
```

> 若未检测到 Key，程序会**自动切回 mock 模式**演示，不会报错。

### 落库（可选，本地 MySQL）

代码从环境变量读 `DB_HOST/DB_PORT/DB_USERNAME/DB_PASSWORD/DB_NAME`，默认连
`127.0.0.1:3306` 的 `agent_runtime` 库（schema 见课程正文「数据模型」一节）。
连不上时自动降级为「不落库模式」，循环逻辑照常演示。 `--no-db` 可强制跳过落库。

## 防护四件套参数（见 `agent.py` 顶部常量）

| 常量 | 默认值 | 作用 |
|---|---|---|
| `MAX_STEPS` | 12 | ① 步骤上限（最后兜底墙） |
| `REPEAT_LIMIT` | 3 | ④ 同一「工具名+参数」连续出现几次后拦截 |
| `KEEP_RECENT` | 2 | ② 摘要压缩：保留最近几个完整工具交互块原文 |
| `TOKEN_BUDGET` / `TOKEN_HARD` | 4000 / 12000 | ③ token 软/硬预算 |
| `TOOL_TIMEOUT` / `RUN_TIMEOUT` | 8s / 120s | ② 单工具 / 整体超时熔断 |

## 落库回放

跑完后查本地库即可完整回放每一步：

```sql
SELECT step_no, span_type, tool_name, status, guardrail, observation
FROM steps WHERE run_id = ? ORDER BY id;
```

`runs` 表看整体（status / ended_reason / total_steps / total_tokens），
`messages` 表看规范消息流（含 `kind='summary'` 的压缩摘要）。
