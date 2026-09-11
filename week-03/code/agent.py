#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
W03 · 零框架 Agent 循环（手搓 tool_call -> 执行 -> 回填 -> 再请求）

对应课程四节：
  ① 循环机制         —— run_agent() 里的 while 循环
  ② 粒度/命名/描述   —— TOOLS 定义（描述是给模型看的 API 文档）
  ③ 失败回填不抛异常 —— execute_tool_safe() 把异常转成字符串
  ④ 并行 + 幂等      —— send_notification 带幂等键；可并行的是只读工具

运行（无需 Key，立刻能跑）：
    python agent.py --mock

运行（真实 API，无需手动设变量）：
    双击 start-env-windows.bat（仓库外那份，已填好 Key），在它弹出的窗口直接：
        python agent.py
    变量由 bat 注入当前窗口（API_KEY / BASE_URL / MODEL），关闭窗口即失效，不落盘。
    兼容写法：也可手动 export OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL。

本文件零第三方依赖，只用到标准库（urllib / json / re / os / sys）。
真实模式用 urllib 直接打 OpenAI 兼容的 /chat/completions，不需要 openai SDK。
"""

import json
import os
import re
import sys
import urllib.request
import urllib.error

MAX_STEPS = 8  # 步数上限（W04 防护伏笔）：到顶强制收口，防止烧 token

# ---------------------------------------------------------------------------
# ② 工具定义：name / description / parameters
#    description 是「给模型看的 API 文档」——说清做什么 + 何时用 + 参数约束
# ---------------------------------------------------------------------------
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "获取指定城市的实时天气。当用户询问天气、温度、出行建议或是否适合外出时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "城市名，如'北京'、'上海'",
                        "examples": ["北京", "上海"],
                    },
                    "date": {
                        "type": "string",
                        "description": "日期，格式 YYYY-MM-DD，默认今天",
                        "pattern": r"^\d{4}-\d{2}-\d{2}$",
                    },
                },
                "required": ["city"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_order",
            "description": "查询商城订单数据。根据用户提供的订单编号或用户ID查询，"
                           "当需要获取订单详情、用户历史订单、发货状态时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "订单编号，如'NO20260911001'"},
                    "user_id": {"type": "string", "description": "用户ID，与order_id二选一"},
                },
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_notification",
            "description": "向指定用户发送通知（写操作，会真正发出消息）。"
                           "当用户要求提醒某人、发送消息、通知用户时使用。"
                           "注意：这是不可逆的写操作，请确认内容后再调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "接收通知的用户ID"},
                    "message": {"type": "string", "description": "通知内容"},
                    "idempotency_key": {
                        "type": "string",
                        "description": "幂等键，相同键重复提交只发一次；不传则由系统按内容派生",
                    },
                },
                "required": ["to", "message"],
                "additionalProperties": False,
            },
        },
    },
]

# 模拟的订单库（真实场景这里会是 MySQL 查询；本课重点是循环，用 dict 代替）
FAKE_ORDERS = {
    "NO20260911001": {"order_id": "NO20260911001", "user_id": "U1001", "status": "已发货", "amount": 299.0},
    "NO20260911002": {"order_id": "NO20260911002", "user_id": "U1002", "status": "待付款", "amount": 88.0},
}
# 已发送通知的去重表：key = 幂等键，value = 发送结果（模拟服务端记录）
SENT_STORE = {}


# ---------------------------------------------------------------------------
# ③ 工具实现 + 异常转字符串（核心：绝不 raise，转成字符串回填）
# ---------------------------------------------------------------------------
def get_weather(city: str, date: str = "今天") -> str:
    # 用 city 哈希造一个稳定的"气温"，让 mock 看起来像真数据
    temp = 18 + (hash(city) % 15)
    return json.dumps({"city": city, "date": date, "weather": "晴", "temp": f"{temp}°C"},
                     ensure_ascii=False)


def query_order(order_id: str = None, user_id: str = None) -> str:
    # 参数校验：两个都没传 -> 抛异常，测试 execute_tool_safe 的捕获
    if not order_id and not user_id:
        raise ValueError("必须提供 order_id 或 user_id 至少一个")
    if order_id:
        order = FAKE_ORDERS.get(order_id)
        if not order:
            # 逻辑上的"没查到"不是异常，是正常结果 -> 直接返回字符串
            return f"未找到订单 {order_id}，请确认订单编号是否正确"
        return json.dumps(order, ensure_ascii=False)
    # 按 user_id 查（简化：遍历）
    matched = [o for o in FAKE_ORDERS.values() if o["user_id"] == user_id]
    if not matched:
        return f"用户 {user_id} 暂无订单"
    return json.dumps(matched, ensure_ascii=False)


def send_notification(to: str, message: str, idempotency_key: str = None) -> str:
    # ④ 幂等：key 从「操作内容」派生，不是随机 UUID
    if not idempotency_key:
        canon = json.dumps({"to": to, "message": message}, sort_keys=True, ensure_ascii=False)
        idempotency_key = f"send_notification:{canon}"
    if idempotency_key in SENT_STORE:
        # 第二次相同 key -> 返回原结果，不重复发（避免双发通知）
        return f"[幂等去重] 该通知已发送过，跳过重复发送。原结果：{SENT_STORE[idempotency_key]}"
    result = f"已向用户 {to} 发送通知：{message}"
    SENT_STORE[idempotency_key] = result
    return result


def execute_tool_safe(name: str, arguments_json: str) -> str:
    """执行工具，任何异常都吞掉转成字符串回填给模型（绝不冒泡）。"""
    try:
        args = json.loads(arguments_json) if arguments_json else {}
    except json.JSONDecodeError as e:
        return f"Error: 参数不是合法JSON: {e}"

    try:
        if name == "get_weather":
            return get_weather(**args)
        elif name == "query_order":
            return query_order(**args)
        elif name == "send_notification":
            return send_notification(**args)
        else:
            return f"Error: 未知工具 {name}"
    except Exception as e:
        # 兜底：任何运行时异常都变成字符串，模型下一轮能看到并自我修正
        return f"Error: {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# LLM 调用：真实模式（urllib 打 OpenAI 兼容接口） + mock 模式（无需 Key）
# ---------------------------------------------------------------------------
def _normalize(resp_json: dict) -> dict:
    """把不同来源的响应统一成 {content, tool_calls:[{id,name,arguments}]}"""
    msg = resp_json["choices"][0]["message"]
    tcs = []
    for tc in msg.get("tool_calls") or []:
        tcs.append({
            "id": tc["id"],
            "name": tc["function"]["name"],
            "arguments": tc["function"]["arguments"],
        })
    return {"content": msg.get("content") or "", "tool_calls": tcs}


def real_llm(messages: list) -> dict:
    # 变量名与 start-env-windows.bat 对齐：优先 OPENAI_* 前缀，回退无前缀的 API_KEY/BASE_URL/MODEL
    key = os.environ.get("OPENAI_API_KEY") or os.environ.get("API_KEY")
    base = os.environ.get("OPENAI_BASE_URL") or os.environ.get("BASE_URL")
    model = os.environ.get("OPENAI_MODEL") or os.environ.get("MODEL")
    if not (key and base and model):
        raise RuntimeError("真实模式需要环境变量 API_KEY / BASE_URL / MODEL（来自 start-env-windows.bat）或 OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL")
    url = base.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "tools": TOOLS,
        "tool_choice": "auto",
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json",
                 "User-Agent": "Mozilla/5.0 (compatible; w03-agent/1.0)"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return _normalize(json.loads(resp.read().decode("utf-8")))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        masked = (key[:6] + "...") if key else "(none)"
        raise RuntimeError(
            f"HTTP {e.code} @ {url}\n"
            f"  key(打码)   = {masked}\n"
            f"  model       = {model}\n"
            f"  响应头      = {dict(e.headers)}\n"
            f"  响应体      = {body[:800]}"
        ) from e


def mock_llm(messages: list) -> dict:
    """
    mock 模式：不联网，纯启发式模拟模型决策，专门用来演示循环。
    - 若已有 tool 结果 -> 给出最终整合回答
    - 否则解析用户意图 -> 产生 tool_calls
    """
    if any(m["role"] == "tool" for m in messages):
        results = [m["content"] for m in messages if m["role"] == "tool"]
        joined = " ; ".join(results)
        return {"content": f"（mock 整合结果）根据工具返回：{joined}。据此给出最终答复。",
                "tool_calls": []}

    user_text = messages[-1]["content"]
    calls = []
    n = 0

    # 天气：检测 "X天气" 或 "天气 X"
    m_city = re.search(r"(北京|上海|广州|深圳|杭州)", user_text)
    if "天气" in user_text and m_city:
        n += 1
        calls.append({"id": f"call_{n}", "name": "get_weather",
                      "arguments": json.dumps({"city": m_city.group(1)}, ensure_ascii=False)})

    # 订单：检测订单号 NO... 或 "用户" + 数字
    m_order = re.search(r"(NO\d+)", user_text)
    m_user = re.search(r"用户([A-Za-z0-9]+)", user_text)  # \w 会把中文也算进去，必须限定字母数字
    if "订单" in user_text and (m_order or m_user):
        n += 1
        if m_order:
            args = {"order_id": m_order.group(1)}
        else:
            args = {"user_id": m_user.group(1)}
        calls.append({"id": f"call_{n}", "name": "query_order",
                      "arguments": json.dumps(args, ensure_ascii=False)})

    # 通知：检测 "通知/提醒/发消息" + 用户 + 内容
    if re.search(r"通知|提醒|发消息", user_text) and m_user:
        n += 1
        # 简单取"说/内容为"后面的内容
        m_msg = re.search(r"(?:说|内容为|内容)[：:]\s*(.+)", user_text)
        msg = m_msg.group(1) if m_msg else "这是一条通知"
        calls.append({"id": f"call_{n}", "name": "send_notification",
                      "arguments": json.dumps({"to": m_user.group(1), "message": msg},
                                              ensure_ascii=False)})

    return {"content": "", "tool_calls": calls}


# ---------------------------------------------------------------------------
# ① 主循环：while 实现 tool_call -> 执行 -> 回填 -> 再请求
# ---------------------------------------------------------------------------
def run_agent(user_input: str, use_mock: bool) -> list:
    messages = [{"role": "user", "content": user_input}]

    for step in range(1, MAX_STEPS + 1):
        print(f"\n===== 第 {step} 轮 | messages 当前共 {len(messages)} 条 =====")
        norm = mock_llm(messages) if use_mock else real_llm(messages)

        # 先把带 tool_calls 的 assistant 消息原样存回（关键：不能丢）
        assistant_msg = {"role": "assistant", "content": norm["content"]}
        if norm["tool_calls"]:
            assistant_msg["tool_calls"] = [
                {"id": t["id"], "type": "function",
                 "function": {"name": t["name"], "arguments": t["arguments"]}}
                for t in norm["tool_calls"]
            ]
        messages.append(assistant_msg)

        # 没有 tool_calls -> 模型觉得可以收尾，直接回答并退出循环
        if not norm["tool_calls"]:
            print("模型最终回答：", norm["content"])
            break

        # 逐个执行工具并回填（此处为清晰起见串行；并行见 README 说明）
        for t in norm["tool_calls"]:
            print(f"  -> 执行工具 {t['name']}({t['arguments']})")
            result = execute_tool_safe(t["name"], t["arguments"])
            messages.append({
                "role": "tool",
                "tool_call_id": t["id"],
                "content": result,
            })
            print(f"  <- 回填: {result[:100]}")

    else:
        # while 正常跑完 MAX_STEPS 没 break -> 步数上限触发
        print(f"\n⚠️ 达到步数上限 {MAX_STEPS}，强制收口（W04 防护伏笔）")

    return messages


def demo_edge():
    """单独演示 ③ 异常转字符串 + ④ 幂等去重，绕过 LLM 直接打工具。"""
    print("\n##### ③ 异常不抛，转成字符串回填给模型 #####")
    print("调用 query_order({}) ->", execute_tool_safe("query_order", "{}"))
    print("（若直接 raise，while 循环会崩；这里变成模型能读到的 Error 字符串）\n")

    print("##### ④ 幂等：相同内容发两次，第二次被去重 #####")
    a = execute_tool_safe("send_notification",
                          json.dumps({"to": "U7", "message": "您的订单已发货"}, ensure_ascii=False))
    b = execute_tool_safe("send_notification",
                          json.dumps({"to": "U7", "message": "您的订单已发货"}, ensure_ascii=False))
    print("第一次：", a)
    print("第二次（同内容）：", b)
    print("（第二次返回原结果、未重复发送 -> 避免双发通知 / 双扣款）")


def main():
    if "--edge" in sys.argv:
        demo_edge()
        return

    use_mock = "--mock" in sys.argv
    if not use_mock and not (os.environ.get("OPENAI_API_KEY") or os.environ.get("API_KEY")):
        print("未检测到 API Key 环境变量（OPENAI_API_KEY 或 API_KEY），自动切换到 --mock 模式演示。")
        print("若要真实调用：双击 start-env-windows.bat 后，在它弹出的窗口里直接 python agent.py\n")
        use_mock = True

    demo = "帮我查一下北京天气，再查订单 NO20260911001，然后通知用户U1001说内容为：您的订单已发货"
    print("演示输入：", demo)
    run_agent(demo, use_mock)


if __name__ == "__main__":
    main()
