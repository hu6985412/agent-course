# W01 配套代码

> LLM 调用基础：把黑盒拆开看
> 全部代码实际跑过，正文里的输出都是真实粘贴的。

## 环境

不需要 `pip install` 任何东西——本周刻意只用 Python 标准库，目的是看清 HTTP 协议本身。

```bash
python 01_softmax.py            # Python 3.8+
python 03_chat_cli.py --mock    # 无 Key 也能跑
```

## 配置：全部从环境变量传入，代码里不写死

`03_chat_cli.py` 的真实模式需要三项配置。**代码里没有任何 Key、URL 或模型名**，
全部从环境变量读取（模型名读不到时会交互式询问）。

| 环境变量 | 说明 |
|---|---|
| `API_KEY` | 必填 |
| `BASE_URL` | 必填，**只到 `/v1`**，别带 `/chat/completions` |
| `MODEL` | 不填则交互式询问 |
| `SYSTEM_PROMPT` | 可选，覆盖默认 system prompt |

```bash
export API_KEY="sk-xxx"
export BASE_URL="https://your-relay.com/v1"    # 注意：只到 /v1
export MODEL="deepseek-v4-flash"
python 03_chat_cli.py
```

**Windows 用户别手打这三条** —— 用仓库根目录的 [`tools/start-env-windows.bat`](../../tools/README.md)：
改一次配置，以后**双击**就开一个已经配好变量的终端，关掉窗口变量就没了。
**仅限 Windows**，且**要先把它复制到仓库外再填 Key**（详见该文件的第一条规矩）。

### 为什么不用命令行传 Key

```bash
# 别这么干
python 03_chat_cli.py --api-key sk-xxx --base-url https://xxx/v1
```

命令行上的内容会**留在 shell history**（`~/.bash_history`、PSReadLine 历史）里，
也会出现在**进程列表**（同机其他用户 `ps` 一下就能看到完整命令行）。
环境变量两者都不会，配合 bat 用完即焚，是更干净的路径。

启动时脚本会打印配置来源，确认你用的是哪一套（**Key 自动打码**）：

```
本次配置来源：
  API_KEY   sk-abc*****************   <- 环境变量 API_KEY
  BASE_URL  https://example.com/v1    <- 环境变量 BASE_URL
  MODEL     deepseek-v4-flash         <- 环境变量 MODEL
  SYSTEM    内置默认   temperature=0.0
  单价      输入 ¥0.14/M · 输出 ¥0.28/M（命中缓存打一折）
```

> **Key 安全提醒**：别把 Key 提交进 git，也别粘进聊天窗口。中转站的 Key 建议先在后台设好**额度上限**——这比任何加密存储都管用。

## 文件清单

| 文件 | 作用 | 需要 Key |
|---|---|---|
| `01_softmax.py` | 手搓 softmax / temperature / top_p，四组对照实验 | ❌ |
| `03_chat_cli.py` | 终端聊天助手：多轮 + 流式 + 实时计费 | mock 模式不需要 |
| `req_nonstream.json` | curl 请求体：非流式 | ✅ |
| `req_stream.json` | curl 请求体：流式 + `include_usage` | ✅ |
| `req_cache.json` | curl 请求体：长 prompt（约 827 token），验证缓存 | ✅ |

## 1. 采样原理实验（建议先跑这个）

```bash
python 01_softmax.py
```

四组输出：

1. **temperature 对概率分布的影响** —— T 从 0.1 拉到 2.0，第一名从 100% 塌到 37%
2. **固定 top_p=0.9，候选集随 T 变宽** —— 1 → 2 → 4 → 5 个
3. **同一输入抽 20 次** —— 看输出种类数
4. **关键对照**：把前两名分差从 1.1 改成 0.05，同样的低温却锁不住

第 4 组是本节的重点，它证明了决定确定性的是 **Δ/T（分差÷温度）**，而不是温度本身。

想亲手验证这条规律的话，把最后一组改成 `for T in (0.01, 0.05, 0.1)`，预期「利润」概率 ≈ **99.3% / 73.1% / 62.2%**。

## 2. curl 手打原始请求

把请求体放进 JSON 文件的好处：**没有多行、没有引号转义、中文不变乱码**。

```powershell
# PowerShell —— 注意必须写 curl.exe，否则会调成 Invoke-WebRequest 别名
curl.exe -s "$env:BASE_URL/chat/completions" `
  -H "Authorization: Bearer $env:API_KEY" `
  -H "Content-Type: application/json" `
  -d "@req_nonstream.json"
```

```bash
# Linux / macOS / Git Bash
curl -s "$BASE_URL/chat/completions" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d @req_nonstream.json
```

**流式要加 `-N`**（关闭 curl 缓冲），否则你看到的不是"没流式"，是自己把流缓冲成了一次性：

```bash
curl -N -s "$BASE_URL/chat/completions" ... -d @req_stream.json
```

**缓存实验**：用 `req_cache.json` 连跑两次，看第二次的 `cached_tokens`。短 prompt（<64 token）永远命中不了，这是 DeepSeek 的规则。

## 3. 终端聊天助手

```bash
python 03_chat_cli.py                 # 真实 API，流式
python 03_chat_cli.py --no-stream     # 对照：非流式，看首字延迟差异
python 03_chat_cli.py --mock          # 本地模拟，验证链路用
python 03_chat_cli.py --window 65536  # 加上窗口预警
```

完整参数（**Key / URL / 模型名不在此列，只走环境变量**）：

| 参数 | 作用 |
|---|---|
| `--system "..."` | 覆盖默认 system prompt（也可设 `SYSTEM_PROMPT` 环境变量） |
| `--temperature 0.7` | 采样温度，默认 0（**thinking 模型会静默忽略它**，见正文踩坑 #1） |
| `--price-in` / `--price-out` | 覆盖单价（元/百万 token），换模型时必改，否则成本算错 |
| `--no-cache-discount` | 关掉缓存一折。部分中转站不透传缓存，按全价估更准 |
| `--no-stream` / `--window N` / `--mock` | 见上 |

会话内命令：

| 命令 | 验证的知识点 |
|---|---|
| `/cost` | 累计花费、缓存命中率（命中缓存的输入按一折算） |
| `/forget` | 清空历史后模型立刻"失忆" → 证明 API 无状态 |
| `/keep N` | 只保留最近 N 轮 → 上下文裁剪的代价 |
| `/exit` | 退出并打印最终账单 |

跑起来之后建议亲手试一次：**连续问三个问题，然后 `/forget`，再问「我刚才问了什么」**。这是本周验收标准里「制造并修复一次模型失忆」的现场。

## 踩坑提示（Windows）

| 现象 | 解法 |
|---|---|
| 一堆莫名的参数绑定错误 | 写 `curl.exe`，PowerShell 5.1 里 `curl` 是 `Invoke-WebRequest` 的别名 |
| 中文乱码 + `ConvertFrom-Json` 报错 | 先执行 `[Console]::OutputEncoding = [System.Text.Encoding]::UTF8`；用 [`tools/start-env-windows.bat`](../../tools/README.md) 起窗口则已自动设好 |
| 命令没输出、也没报错 | 别用 `-s`，用 `-sS`；`-s` 会把错误信息一起吞掉 |
| `Invalid URL (.../chat/completions/chat/completions)` | `BASE_URL` 只填到 `/v1` |
| `-d` 后面的文件名被当成了请求体内容 | `-d @file` 的 `@` 不能漏；PowerShell 里要写成 `"@req.json"`（加引号，否则被当成 splatting 运算符） |

## 许可

代码 MIT，文章 CC BY-NC-SA 4.0。
