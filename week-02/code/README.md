# W02 配套代码

> Prompt 工程与结构化输出：领域信息抽取
> 全部代码实际跑过，正文里的输出都是真实粘贴的。

## 环境

需要 Python 3.9+ 与 `requests` / `pydantic`（Pydantic v2 优先，v1 也兼容）：

```bash
pip install requests pydantic
```

## 配置：全部从环境变量传入，代码里不写死

`extract.py` 真实模式需要三项配置。代码里**没有任何 Key、URL 或模型名**，全部从环境变量读取（读不到会直接报错退出）。

| 环境变量 | 说明 |
|---|---|
| `API_KEY` | 必填 |
| `BASE_URL` | 必填，**只到 `/v1`**，别带 `/chat/completions` |
| `MODEL` | 不填默认 `deepseek-v4-flash` |

```bash
export API_KEY="sk-xxx"
export BASE_URL="https://your-relay.com/v1"
export MODEL="deepseek-v4-flash"
python extract.py --prompt v2 --repeat 3
```

**Windows 用户**：别手打这三条，用仓库根的 `tools/start-env-windows.bat`（先复制到仓库外再填 Key，详见该文件说明）。双击即开一个已配好变量的终端，关掉窗口变量就没了。

### 为什么不用命令行传 Key

命令行内容会留在 shell history（`~/.bash_history`、PSReadLine 历史）和进程列表（同机其他用户 `ps` 可见）。环境变量两者都不会，配合 bat 用完即焚，是更干净的路径。

## 文件清单

| 文件 | 作用 | 需要 Key |
|---|---|---|
| `extract.py` | 核心批跑：读 `cases.json` → 调真实 API → `json.loads` → Pydantic 校验 → 逐字段比对 → 统计 + 失败明细 | ✅ |
| `cases.json` | 24 条电商客服对话测试集 + 期望值（其中 5 条用接受集合） | ❌ |
| `results_v1_r3.json` ~ `results_v4_r3.json` | 四版 prompt 各跑 repeat=3 的实测结果 | ❌ |
| `inject_bad.json` / `inject_good.json` | Prompt Injection 对照实验请求体 | ✅ |
| `parse_demo.py` | 把两次真实输出喂给 `json.loads` 复现格式问题 | ❌ |

## 运行

```bash
python extract.py --prompt v2 --repeat 3     # 用 v2 跑全部 24 条，每条 3 次压噪声
python extract.py --prompt v3 --show         # 只打印 v3 的 prompt 全文，不调 API
python extract.py --limit 5                   # 只跑前 5 条快速验证
python extract.py --prompt v4 --repeat 1      # 单轮快速看差距
```

参数（Key / URL / 模型名不在此列，只走环境变量）：

| 参数 | 作用 |
|---|---|
| `--prompt` | 选哪一版 prompt：`v1` / `v2` / `v3` / `v4`，默认 `v1` |
| `--repeat N` | 每条样本重复 N 次，压随机噪声；报告「完全稳定率」（N/N 全过才算）与「平均通过率」 |
| `--limit N` | 只跑前 N 条 |
| `--show` | 只打印拼装好的 prompt 全文后退出，不调 API |
| `--sleep` | 请求间隔秒，默认 1.0，防限流 |

输出：终端打印逐条结果 + 汇总（完全稳定率 / 平均通过率 / 字段成功率 / token 合计），并写 `results_{prompt}_r{repeat}.json`。

## Prompt 四版演进（详见正文）

| 版本 | 思路 | 约束字符数 |
|---|---|---|
| v1 | 基础五段结构 | 约 317 |
| v2 | v1 + 关键词映射（intent 直接锚定） | 约 608 |
| v3 | v2 的关键词换成判据 + few-shot 示例 | 约 1874 |
| v4 | v3 去掉示例（验证示例价值） | 约 978 |

> 单变量原则：v2 / v3 / v4 共享 `SHARED_EXTRA`（amount 规则 + 纯情绪规则），只差 intent 段，保证 A/B 严格可比。

## 踩坑提示

| 现象 | 解法 |
|---|---|
| `Invalid URL (.../chat/completions/chat/completions)` | `BASE_URL` 只填到 `/v1` |
| 输出带 JSON 代码围栏导致 `json.loads` 崩溃 | 脚本已做去围栏处理；写 prompt 时尽量别诱导模型围围栏 |
| 概率数字看着体面，批量一跑就露馅 | 用 `--repeat 3` 看「完全稳定率」，别只看单次 |

## 许可

代码 MIT，文章 CC BY-NC-SA 4.0。
