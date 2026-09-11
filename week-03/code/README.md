# W03 配套代码

> Tool Use：手搓 Agent 循环（零框架纯 Python while 循环）
> 全部代码实际跑过，正文里的输出都是真实粘贴的。

## 环境

**零第三方依赖**，只用 Python 标准库（`urllib` / `json` / `re` / `os` / `sys`）。
真实模式用 `urllib` 直接打 OpenAI 兼容的 `/chat/completions`，**不需要 openai SDK**。
Python 3.8 / 3.13 均可运行（脚本只用标准库语法）。

## 配置：全部从环境变量传入，代码里不写死

`agent.py` 真实模式需要三项配置。变量名与 `tools/start-env-windows.bat` 对齐：

| 环境变量 | 说明 |
|---|---|
| `API_KEY` 或 `OPENAI_API_KEY` | 必填，中转站 Key |
| `BASE_URL` 或 `OPENAI_BASE_URL` | 必填，**只到 `/v1`**，别带 `/chat/completions` |
| `MODEL` 或 `OPENAI_MODEL` | 必填，如 `deepseek-v4-flash` |

两种设变量方式都认：

```powershell
# 方式 A（推荐，Windows）：双击 tools/start-env-windows.bat（先复制到仓库外再填 Key）
#   它会弹出一个已配好变量的 PowerShell 窗口，在那里直接：
python agent.py

# 方式 B：手动设环境变量
#   PowerShell 里用 $env:（不是 bash 的 export！）
$env:API_KEY = "你的中转站Key"
$env:BASE_URL = "https://你的中转站地址/v1"
$env:MODEL = "deepseek-v4-flash"
python agent.py
```

> 为什么不用命令行传 Key：命令行内容会留在 shell history 和进程列表里。环境变量配合 bat 用完即焚，干净得多。

## 文件清单

| 文件 | 作用 | 需要 Key |
|---|---|---|
| `agent.py` | 核心：零框架 while 循环 Agent，3 个工具（查天气 / 查订单 / 发通知） | 真实模式需要 ✅；mock 不需要 ❌ |

## 运行

```bash
python agent.py --mock     # 无需 Key，立刻看循环：messages 1→5→6 完整跑一轮
python agent.py --edge      # 演示「异常转字符串」+「幂等去重」两个机制
python agent.py             # 真实 API：模型自己决定调哪几个工具、怎么造参数
```

## 三个模式

- `--mock`：内置一个启发式 `mock_llm`，按关键词硬匹配模拟"模型决策"。**纯标准库，无 Key 也能跑**，专门用来看清循环怎么转、messages 怎么变长。
- `--edge`：绕过 LLM 直接打工具，单独验证第 3 节（异常转字符串）和第 4 节（幂等去重）。
- 真实模式：用 `urllib` 打你的中转站。模型**真的在理解意图 → 选工具 → 造参数**——这是和 mock 的本质区别。

## 踩坑提示

| 现象 | 真因 | 解法 |
|---|---|---|
| `HTTP Error 403: Forbidden`（用 `urllib` 打中转站） | `urllib` 默认 `User-Agent` 是 `Python-urllib/3.x`，常被中转站 WAF 当异常脚本客户端拦截；`curl.exe` 默认 UA 是 `curl/8.x` 所以能过 | 请求头加浏览器风格 `User-Agent`（代码已加，见 `real_llm`） |
| PowerShell 里敲 `export API_KEY=...` 报错"不被识别" | `export` 是 bash 语法，PowerShell 不认 | 改用 `$env:API_KEY = "..."`；或直接双击 bat |
| 变量在 A 窗口设了、B 窗口读不到 | `start-env-windows.bat` 用 `powershell -NoExit` 启**新子进程**，变量只活在弹出的窗口里 | 在 bat 弹出的窗口里跑 `python agent.py`，不要另开窗口 |

## 许可

代码 MIT，文章 CC BY-NC-SA 4.0。
