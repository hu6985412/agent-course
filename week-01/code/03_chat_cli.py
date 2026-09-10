# -*- coding: utf-8 -*-
"""
W01 第 4 节：终端聊天助手（多轮 + 流式 + 实时计费）

只用标准库（urllib / json / os），不需要 pip install 任何东西。
之所以不用 openai SDK，是因为 W01 的目的就是「把黑盒拆开看」——
SDK 会把 delta 拼接、usage 位置、messages 全量重发这些细节藏起来，
而这几件事恰恰是理解 Agent 成本与上下文的关键。W08 之后我们再用框架。

【配置从外部传入，代码里不写死任何 Key / URL / 模型名】
全部走环境变量；模型名读不到时才交互式询问。

方式一 · 环境变量（推荐，配合 tools/start-env-windows.bat 双击即用）
    export API_KEY="sk-xxx"          # Windows PowerShell: $env:API_KEY="sk-xxx"
    export BASE_URL="https://xxx/v1" # 只到 /v1，别带 /chat/completions
    export MODEL="deepseek-v4-flash" # 可选，不设则交互式询问
    python 03_chat_cli.py

方式二 · 一行搞定（当前 shell 内临时生效，关掉就没）
    API_KEY=sk-xxx BASE_URL=https://xxx/v1 MODEL=deepseek-v4-flash python 03_chat_cli.py

方式三 · 不需要 Key，本地模拟 SSE 验证链路
    python 03_chat_cli.py --mock

【为什么不支持 --api-key / --base-url 这种命令行参数】
    命令行上的内容会留在 shell history（~/.bash_history、PSReadLine 历史）里，
    也会出现在进程列表中。环境变量两者都不会，配好 bat 用完即焚更干净。

其它可用参数
    --no-stream          走非流式，跟流式对照首字延迟
    --window 65536       上下文窗口上限，接近时告警
    --system "..."       覆盖默认 system prompt
    --temperature 0.7    采样温度（注意：thinking 模型会静默忽略，见正文踩坑 #1）
    --price-in 0.14 --price-out 0.28    覆盖单价（元/百万 token），换模型时要改
    --price-in 0.14 --price-out 0.28 --no-cache-discount  关闭缓存一折（部分中转站不透传）

会话内命令：
    /cost    打印本会话累计成本明细
    /forget  丢掉全部历史（现场演示「模型失忆」）
    /keep N  只保留最近 N 条消息（现场演示上下文裁剪的代价）
    /exit    退出
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error
import argparse

# 默认按 DeepSeek V4 Flash 官方定价（元 / 百万 token），命中缓存的输入打一折。
# 换模型 / 换中转站时用 --price-in / --price-out 覆盖，别改这里的常量。
PRICE_IN = 0.14
PRICE_OUT = 0.28
CACHE_DISCOUNT = 0.1

DEFAULT_SYSTEM_PROMPT = "你是财务分析助手，回答简洁准确。涉及具体数字时必须说明来源科目。"

# 环境变量名。集中放这儿，方便一眼看清脚本依赖哪些外部配置。
ENV_API_KEY = "API_KEY"
ENV_BASE_URL = "BASE_URL"
ENV_MODEL = "MODEL"


# ---------------------------------------------------------------- 计费

class Meter:
    """累计计费器。注意：输入里的命中缓存部分按折扣价算，其余全价。"""

    def __init__(self, price_in=PRICE_IN, price_out=PRICE_OUT,
                 cache_discount=CACHE_DISCOUNT):
        self.prompt = 0
        self.cached = 0
        self.completion = 0
        self.price_in = price_in
        self.price_out = price_out
        self.cache_discount = cache_discount

    def add(self, usage):
        """从 usage 里取数。不同厂商字段名不一样，这里做兼容。"""
        if not usage:
            return
        pt = usage.get("prompt_tokens", 0)
        ct = usage.get("completion_tokens", 0)
        details = usage.get("prompt_tokens_details") or {}
        # OpenAI 系放在 prompt_tokens_details.cached_tokens
        # DeepSeek 另给了 prompt_cache_hit_tokens，两者取其一即可
        cached = details.get("cached_tokens") or usage.get("prompt_cache_hit_tokens") or 0
        self.prompt += pt
        self.cached += cached
        self.completion += ct
        return pt, ct, cached

    @property
    def cost(self):
        miss = max(self.prompt - self.cached, 0)
        return (miss / 1e6 * self.price_in
                + self.cached / 1e6 * self.price_in * self.cache_discount
                + self.completion / 1e6 * self.price_out)

    def report(self):
        miss = max(self.prompt - self.cached, 0)
        print("\n" + "-" * 58)
        print(f"{'累计输入 token':<22}{self.prompt:>10}")
        print(f"{'  其中命中缓存':<22}{self.cached:>10}  (打一折)")
        print(f"{'  全价输入':<22}{miss:>10}")
        print(f"{'累计输出 token':<22}{self.completion:>10}")
        print(f"{'折后总花费':<22}¥{self.cost:>9.6f}")
        hit = (self.cached / self.prompt * 100) if self.prompt else 0
        print(f"{'缓存命中率':<22}{hit:>9.1f}%")
        print("-" * 58 + "\n")


# ---------------------------------------------------------------- HTTP

def call_stream(base_url, api_key, model, messages, temperature=0, extra=None):
    """
    手打一次流式请求，逐块 yield。

    返回两种块：
        ('delta', text)   模型吐出的一个片段
        ('usage', dict)   最后一块（usage 挂在 [DONE] 之前）

    这里刻意手写 SSE 解析而不引 SDK —— 就是为了看清楚这三件事：
      1. 内容在 choices[0].delta.content，不是非流式的 choices[0].message.content
      2. usage 不是每块都有，只在最后一块出现，且必须在请求里加 include_usage
      3. 结束标志是 "data: [DONE]" 这一行，不是一个 JSON 字段
    """
    body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": True,
        "stream_options": {"include_usage": True},  # 不加这两行，usage 永远是 None
    }
    if extra:
        body.update(extra)

    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as resp:
        for raw in resp:
            line = raw.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue
            payload = line[len("data:"):].strip()
            if payload == "[DONE]":
                break
            try:
                chunk = json.loads(payload)
            except json.JSONDecodeError:
                continue
            usage = chunk.get("usage")
            if usage:
                yield ("usage", usage)
                continue
            choices = chunk.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            if delta.get("content"):
                yield ("delta", delta["content"])


def call_nonstream(base_url, api_key, model, messages, temperature=0, extra=None):
    """非流式版本，返回 (content, usage)。用于跟流式对照。"""
    body = {"model": model, "messages": messages, "temperature": temperature}
    if extra:
        body.update(extra)
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    msg = data["choices"][0]["message"]
    return msg.get("content", ""), data.get("usage")


def resolve_config(args):
    """
    解析配置：环境变量 > 交互式询问（仅模型名）。

    刻意不提供 --api-key / --base-url 这类命令行参数：
    命令行内容会进 shell history 和进程列表，环境变量不会。
    Key 的唯一入口是环境（配合 tools/start-env-windows.bat 用完即焚）。

    返回 (cfg_dict, sources)，sources 记录每一项来自哪里，启动时打出来方便排查。
    """
    def pick(env_name, prompt=None, required=False):
        env_val = os.environ.get(env_name, "").strip()
        if env_val:
            return env_val, f"环境变量 {env_name}"
        if prompt:
            val = input(prompt).strip()
            if val:
                return val, "交互式输入"
        if required:
            sys.exit(f"缺少配置：{env_name}。先 export {env_name}=... "
                     f"（BASE_URL 只到 /v1，不要带 /chat/completions）。\n"
                     f"Windows 用户可用 tools/start-env-windows.bat 双击加载。")
        return "", "未设置"

    cfg, src = {}, {}
    cfg["api_key"], src["api_key"] = pick(ENV_API_KEY, required=True)
    cfg["base_url"], src["base_url"] = pick(ENV_BASE_URL, required=True)
    cfg["model"], src["model"] = pick(ENV_MODEL, prompt="请输入模型名：")
    if not cfg["model"]:
        sys.exit("缺少模型名：先 export MODEL=...（或用 tools/start-env-windows.bat）")
    cfg["temperature"] = args.temperature
    cfg["system"] = args.system or os.environ.get("SYSTEM_PROMPT", "") or DEFAULT_SYSTEM_PROMPT
    src["system"] = "命令行参数" if args.system else (
        "环境变量 SYSTEM_PROMPT" if os.environ.get("SYSTEM_PROMPT") else "内置默认")
    return cfg, src


def mask(key):
    """打印时只露前 6 位，避免 Key 出现在截图 / 日志里。"""
    if not key:
        return "(空)"
    return key[:6] + "*" * max(len(key) - 6, 0) if len(key) > 10 else "***"


# ---------------------------------------------------------------- mock

def mock_stream(messages, seed=None):
    """
    本地模拟一次 SSE 响应。没有 Key 时用它可以把整条链路跑通，
    验证「delta 拼接」「usage 在最后一块」这些逻辑是对的。

    注意它模拟的是协议形状，不是模型能力 —— 别用它评估回答质量。
    """
    answer = ("[mock] 你说了：%s。这是一段用于验证流式拼接的模拟回答，"
              "它会一个字一个字地吐出来。" % messages[-1]["content"][:12])
    for ch in answer:
        time.sleep(0.02)
        yield ("delta", ch)
    n_in = sum(len(m.get("content", "")) for m in messages)
    yield ("usage", {
        "prompt_tokens": n_in,
        "completion_tokens": len(answer),
        "prompt_tokens_details": {"cached_tokens": 0},
    })


def mock_once(messages):
    answer = "[mock] 你说了：%s" % messages[-1]["content"][:20]
    return answer, {
        "prompt_tokens": sum(len(m.get("content", "")) for m in messages),
        "completion_tokens": len(answer),
        "prompt_tokens_details": {"cached_tokens": 0},
    }


# ---------------------------------------------------------------- 主循环

def estimate_tokens(text):
    """
    只对中文友好的粗估：中文 1 字 ≈ 1 token，英文 4 字符 ≈ 1 token。
    真实数字以服务端 usage 为准 —— 本地估这个只是用来做「快撞窗口了」的预警。
    """
    n = 0
    for ch in text:
        n += 1 if "\u4e00" <= ch <= "\u9fff" else 0.25
    return int(n)


def main():
    ap = argparse.ArgumentParser(
        description="W01 终端聊天助手",
        epilog="Key / URL / 模型名只从环境变量读取（API_KEY / BASE_URL / MODEL），"
               "不提供命令行传参，避免留在 shell history 与进程列表里。")
    ap.add_argument("--mock", action="store_true", help="本地模拟，不需要 Key")
    ap.add_argument("--no-stream", action="store_true", help="走非流式，跟流式对照")
    ap.add_argument("--window", type=int, default=0,
                    help="上下文窗口上限，超过即告警（如 65536）")
    # ---- 可选覆盖项（不含 Key / URL / 模型名，那些只从环境变量读）----
    ap.add_argument("--system", help="覆盖 system prompt；也可设环境变量 SYSTEM_PROMPT")
    ap.add_argument("--temperature", type=float, default=0.0, help="采样温度，默认 0")
    ap.add_argument("--price-in", type=float, default=PRICE_IN, help="输入单价（元/百万 token）")
    ap.add_argument("--price-out", type=float, default=PRICE_OUT, help="输出单价（元/百万 token）")
    ap.add_argument("--no-cache-discount", action="store_true",
                    help="关闭缓存一折（部分中转站不透传缓存，按全价估更准）")
    args = ap.parse_args()

    if args.mock:
        cfg = {"api_key": "mock", "base_url": "mock", "model": "mock",
               "temperature": args.temperature, "system": DEFAULT_SYSTEM_PROMPT}
        src = {k: "mock" for k in ("api_key", "base_url", "model", "system")}
        print("[mock 模式] 不需要 Key，回答是本地编的，只验证协议链路。\n")
    else:
        cfg, src = resolve_config(args)

    messages = [{"role": "system", "content": cfg["system"]}]
    meter = Meter(price_in=args.price_in, price_out=args.price_out,
                  cache_discount=0.0 if args.no_cache_discount else CACHE_DISCOUNT)

    if not args.mock:
        print("本次配置来源：")
        print(f"  API_KEY   {mask(cfg['api_key'])}   <- {src['api_key']}")
        print(f"  BASE_URL  {cfg['base_url']}   <- {src['base_url']}")
        print(f"  MODEL     {cfg['model']}   <- {src['model']}")
        print(f"  SYSTEM    {src['system']}   temperature={cfg['temperature']}")
        print(f"  单价      输入 ¥{args.price_in}/M · 输出 ¥{args.price_out}/M"
              + ("（缓存折扣已关闭）" if args.no_cache_discount else "（命中缓存打一折）"))
        print()

    print("=" * 58)
    print(" W01 终端聊天助手   /cost 看花费  /forget 清空历史  /exit 退出")
    print("=" * 58)

    while True:
        try:
            user = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user:
            continue

        if user == "/exit":
            break
        if user == "/cost":
            meter.report()
            continue
        if user == "/forget":
            messages = [{"role": "system", "content": cfg["system"]}]
            print("历史已清空 —— 现在问『我刚才说了什么』它就答不上来了。")
            continue
        if user.startswith("/keep "):
            try:
                n = int(user.split()[1])
            except ValueError:
                print("用法：/keep 4")
                continue
            messages = [messages[0]] + messages[-(n * 2):]
            print(f"只保留最近 {n} 轮，历史被裁掉。试试问早期的内容。")
            continue

        messages.append({"role": "user", "content": user})

        # 本地预警：这一轮要发出去多少 token
        local_est = sum(estimate_tokens(m.get("content", "")) for m in messages)
        print(f"[本地估算本轮输入 ≈ {local_est} token，实际以服务端 usage 为准]",
              end="" if args.no_stream else "\r")
        if args.window and local_est > args.window * 0.8:
            print(f"\n⚠️  已用 {local_est}，接近窗口上限 {args.window}")

        print("bot> ", end="", flush=True)

        t0 = time.time()
        first_at = None
        reply = []
        usage = None

        try:
            if args.mock:
                for kind, val in mock_stream(messages):
                    if kind == "delta":
                        if first_at is None:
                            first_at = time.time() - t0
                        reply.append(val)
                        print(val, end="", flush=True)
                    else:
                        usage = val
            elif args.no_stream:
                text, usage = call_nonstream(cfg["base_url"], cfg["api_key"], cfg["model"], messages,
                                temperature=cfg["temperature"])
                first_at = time.time() - t0
                reply.append(text)
                print(text, end="", flush=True)
            else:
                for kind, val in call_stream(cfg["base_url"], cfg["api_key"], cfg["model"], messages,
                             temperature=cfg["temperature"]):
                    if kind == "delta":
                        if first_at is None:
                            first_at = time.time() - t0
                        reply.append(val)
                        print(val, end="", flush=True)
                    else:
                        usage = val
        except urllib.error.HTTPError as e:
            print(f"\n\n❌ HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:400]}")
            messages.pop()
            continue
        except urllib.error.URLError as e:
            print(f"\n\n❌ 网络错误: {e}")
            messages.pop()
            continue

        elapsed = time.time() - t0
        content = "".join(reply)
        if not content.strip():
            content = "(空回复)"
        messages.append({"role": "assistant", "content": content})

        print()  # 换行
        pt, ct, cached = meter.add(usage)
        print(f"\n[{['非流式', '流式'][not args.no_stream]}] "
              f"首字 {first_at * 1000:.0f}ms · 总耗时 {elapsed * 1000:.0f}ms · "
              f"本轮 {pt} in / {ct} out"
              + (f"（缓存命中 {cached}）" if cached else ""))
        print(f"历史消息数：{len(messages)}（system 占 1 条）")

    meter.report()
    print("bye.")


if __name__ == "__main__":
    main()
