#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
W04 · 带防护与审计的 Agent（在 W03 零框架循环上加固）

本周四件套（对应课表「学什么」）：
  ① 步骤上限   —— MAX_STEPS，到顶强制收口（W03 已埋伏笔）
  ② 超时       —— 每个工具调用包一层 timeout，卡死不拖垮全局
  ③ token 预算 —— 累计 token 接近预算触发摘要压缩，超限熔断
  ④ 重复调用检测 —— 同一「工具名+参数」连续出现 N 次直接拦（防死循环）

记忆三层：
  ① 历史   —— messages 表全量落库（Layer 1）
  ② 摘要压缩 —— 老轮次压成一条 kind='summary' 消息，对话里只留最近 K 轮原文
  ③ 外部存储 —— 工具结果落 steps.observation / tool_result，对话里只留引用

审计落库：runs(主表) + steps(ReAct 迭代) + messages(规范消息流)，三表联动可回放。

运行（无需 Key，立刻能跑，本地 agent_runtime 库已建）：
    python agent.py --mock            # 正常退款流程
    python agent.py --mock --deadloop # 故意制造死循环，验证防护④
    python agent.py --mock --edge     # 演示 异常转字符串 / 幂等 / 重复拦截 / 超时

运行（真实 API，无需手动设变量）：
    双击 start-env-windows.bat（仓库外那份，已填好 Key），在它弹出的窗口直接：
        python agent.py
    变量由 bat 注入（API_KEY / BASE_URL / MODEL）。DB 连接从环境变量读，默认 127.0.0.1:3306 root 空密码。

依赖：标准库 + pymysql（用于落库；未装则自动降级为「不落库」模式，循环逻辑照常演示）。
"""

import json
import os
import re
import sys
import time
import concurrent.futures
import urllib.request
import urllib.error

# ---------------------------------------------------------------------------
# 配置常量（防护四件套参数）
# ---------------------------------------------------------------------------
MAX_STEPS = 12          # ① 步骤上限
REPEAT_LIMIT = 3        # ④ 同一「工具名+参数」连续出现几次后拦截
KEEP_RECENT = 2         # ② 摘要压缩：对话里保留最近几个『完整工具交互块』原文
TOKEN_BUDGET = 4000     # ③ token 预算（估算值），达到触发摘要压缩
TOKEN_HARD = 12000      # ③ 硬熔断：超过直接终止 run
TOOL_TIMEOUT = 8        # ② 单个工具超时（秒）
RUN_TIMEOUT = 120       # ② 整体运行超时（秒）

# ---------------------------------------------------------------------------
# 工具定义（退款业务场景：查订单 → 查物流 → 判断退款 → 执行退款）
# 描述是「给模型看的 API 文档」——说清做什么 + 何时用 + 参数约束
# ---------------------------------------------------------------------------
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_order",
            "description": "查询商城订单。当用户提供订单编号时查询订单详情，"
                           "获取订单状态、金额、下单用户。判断能否退款前必须先调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "订单编号，如'NO20260911001'"},
                },
                "required": ["order_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_logistics",
            "description": "查询订单物流轨迹。已知订单编号时查询承运商、运单号、"
                           "物流状态（运输中/已签收）、最近更新时间。判断退款前需确认收货状态。",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "订单编号"},
                },
                "required": ["order_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "decide_refund",
            "description": "根据订单状态与物流状态判定是否可退款。已签收且距下单≤7天可退，"
                           "其余不可退。返回 {refundable, reason, amount}。必须在查完订单与物流后调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "订单编号"},
                },
                "required": ["order_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_refund",
            "description": "执行退款（写操作，会真正发起退款）。仅当 decide_refund 判定可退时才调用。"
                           "注意：不可逆，请确认金额后再调用。相同 order_id 重复调用只退一次。",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "订单编号"},
                    "amount": {"type": "number", "description": "退款金额，应与 decide_refund 返回一致"},
                },
                "required": ["order_id", "amount"],
                "additionalProperties": False,
            },
        },
    },
]

# 模拟数据（真实场景这里会是 MySQL / 业务 API；本课重点是循环与防护，用 dict 代替）
FAKE_ORDERS = {
    "NO20260911001": {"order_id": "NO20260911001", "user_id": "U1001",
                      "status": "已签收", "amount": 299.0, "paid_at": "2026-09-10"},
    "NO20260911002": {"order_id": "NO20260911002", "user_id": "U1002",
                      "status": "运输中", "amount": 88.0, "paid_at": "2026-09-12"},
}
FAKE_LOGISTICS = {
    "NO20260911001": {"order_id": "NO20260911001", "carrier": "顺丰", "track_no": "SF123",
                      "status": "已签收", "last_update": "2026-09-11 18:00"},
    "NO20260911002": {"order_id": "NO20260911002", "carrier": "中通", "track_no": "ZT456",
                      "status": "运输中", "last_update": "2026-09-13 09:00"},
}
# 已退款记录（幂等去重表）：key = order_id
REFUND_STORE = {}


# ---------------------------------------------------------------------------
# 工具实现（异常转字符串 + 幂等 + 超时熔断，均在 execute_tool_safe 统一收口）
# ---------------------------------------------------------------------------
def query_order(order_id: str) -> str:
    order = FAKE_ORDERS.get(order_id)
    if not order:
        return f"未找到订单 {order_id}，请确认订单编号是否正确"
    return json.dumps(order, ensure_ascii=False)


def query_logistics(order_id: str) -> str:
    # --deadloop 模式：模拟物流接口 500，永远失败 -> 用来测死循环防护
    if os.environ.get("W04_DEADLOOP") == "1":
        raise RuntimeError("物流接口 HTTP 500（模拟故障）")
    logi = FAKE_LOGISTICS.get(order_id)
    if not logi:
        return f"未找到订单 {order_id} 的物流信息"
    return json.dumps(logi, ensure_ascii=False)


def decide_refund(order_id: str) -> str:
    order = FAKE_ORDERS.get(order_id)
    if not order:
        return f"Error: 订单 {order_id} 不存在，无法判定退款"
    logi = FAKE_LOGISTICS.get(order_id, {})
    # 业务规则：已签收 且 距下单 ≤7 天 -> 可退
    signed = logi.get("status") == "已签收"
    recent = order.get("paid_at", "") >= "2026-09-08"  # 简化：9-08 之后算 7 天内
    refundable = signed and recent
    reason = "已签收且在7天内" if refundable else ("未签收不可退" if not signed else "超7天不可退")
    return json.dumps({"refundable": refundable, "reason": reason,
                       "amount": order["amount"] if refundable else 0.0},
                      ensure_ascii=False)


def execute_refund(order_id: str, amount: float) -> str:
    # 幂等：相同 order_id 只退一次（类比 Stripe Idempotency-Key / Laravel 队列 unique）
    if order_id in REFUND_STORE:
        return f"[幂等去重] 订单 {order_id} 已退款过，跳过重复退款。原结果：{REFUND_STORE[order_id]}"
    result = f"已对订单 {order_id} 退款 {amount} 元，预计原路返回"
    REFUND_STORE[order_id] = result
    return result


def execute_tool_safe(name: str, arguments_json: str) -> str:
    """执行工具，任何异常都吞掉转成字符串回填（绝不 raise 冒泡）。"""
    try:
        args = json.loads(arguments_json) if arguments_json else {}
    except json.JSONDecodeError as e:
        return f"Error: 参数不是合法JSON: {e}"
    try:
        if name == "query_order":
            return query_order(**args)
        elif name == "query_logistics":
            return query_logistics(**args)
        elif name == "decide_refund":
            return decide_refund(**args)
        elif name == "execute_refund":
            return execute_refund(**args)
        else:
            return f"Error: 未知工具 {name}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


def run_with_timeout(fn, timeout, *a, **k) -> tuple:
    """② 超时熔断：工具卡死不拖垮全局。返回 (结果字符串, 是否超时)。"""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(fn, *a, **k)
        try:
            return fut.result(timeout=timeout), False
        except concurrent.futures.TimeoutError:
            return f"Error: 工具执行超时（>{timeout}s），已熔断", True


# ---------------------------------------------------------------------------
# LLM 调用：真实模式（urllib 打 OpenAI 兼容接口）+ mock 模式（无需 Key）
# ---------------------------------------------------------------------------
def _normalize(resp_json: dict) -> dict:
    msg = resp_json["choices"][0]["message"]
    tcs = [{"id": tc["id"], "name": tc["function"]["name"],
            "arguments": tc["function"]["arguments"]}
           for tc in (msg.get("tool_calls") or [])]
    return {"content": msg.get("content") or "", "tool_calls": tcs}


def real_llm(messages: list, use_tools: bool = True) -> dict:
    key = os.environ.get("OPENAI_API_KEY") or os.environ.get("API_KEY")
    base = os.environ.get("OPENAI_BASE_URL") or os.environ.get("BASE_URL")
    model = os.environ.get("OPENAI_MODEL") or os.environ.get("MODEL")
    if not (key and base and model):
        raise RuntimeError("真实模式需要环境变量 API_KEY / BASE_URL / MODEL 或 OPENAI_* 前缀")
    url = base.rstrip("/") + "/chat/completions"
    payload = {"model": model, "messages": messages}
    if use_tools:
        payload["tools"] = TOOLS
        payload["tool_choice"] = "auto"
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "User-Agent": "Mozilla/5.0 (compatible; w04-agent/1.0)"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return _normalize(json.loads(resp.read().decode("utf-8")))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        masked = (key[:6] + "...") if key else "(none)"
        raise RuntimeError(
            f"HTTP {e.code} @ {url}\n  key(打码)={masked}\n  model={model}\n  响应体={body[:800]}") from e


def executed_tools(messages: list) -> set:
    """扫描 messages，返回『已产生 tool 结果』的工具名集合。"""
    pending, done = {}, set()
    for m in messages:
        if m.get("role") == "assistant":
            for tc in m.get("tool_calls", []):
                pending[tc["id"]] = tc["function"]["name"]
        elif m.get("role") == "tool":
            name = pending.pop(m.get("tool_call_id"), None)
            if name:
                done.add(name)
    return done


def mock_llm(messages: list, done: set) -> dict:
    """mock 模式：启发式模拟模型决策，按『已执行工具(done)』决定下一步调用。

    注意：done 由 run_agent 维护，不靠扫描 messages——因为摘要压缩会把已执行的
    工具对从对话里摘掉（存进 steps 表），扫描会误判『没执行过』而重查。
    """
    # 死循环模式：无视状态，永远调 query_logistics（相同参数）-> 专门测防护④
    if os.environ.get("W04_DEADLOOP") == "1":
        oid = re.search(r"(NO\d+)", messages[0]["content"])
        oid = oid.group(1) if oid else "NO20260911001"
        return {"content": "", "tool_calls": [
            {"id": f"call_{int(time.time()*1000)}", "name": "query_logistics",
             "arguments": json.dumps({"order_id": oid}, ensure_ascii=False)}]}

    oid = re.search(r"(NO\d+)", messages[0]["content"])
    oid = oid.group(1) if oid else "NO20260911001"

    # 按业务顺序：订单 -> 物流 -> 判定 -> 执行 -> 收尾
    if "query_order" not in done:
        return _call("query_order", {"order_id": oid})
    if "query_logistics" not in done:
        return _call("query_logistics", {"order_id": oid})
    if "decide_refund" not in done:
        return _call("decide_refund", {"order_id": oid})
    if "execute_refund" not in done:
        # 从 decide 结果看是否可退，再决定是否执行退款
        for m in reversed(messages):
            if m.get("role") == "tool":
                try:
                    data = json.loads(m["content"])
                    if isinstance(data, dict) and "refundable" in data:
                        if data.get("refundable"):
                            return _call("execute_refund",
                                         {"order_id": oid, "amount": data["amount"]})
                        return {"content": f"（mock 整合）订单 {oid} 不可退款：{data.get('reason')}。",
                                "tool_calls": []}
                except Exception:
                    pass
                break
        return {"content": f"（mock 整合）订单 {oid} 退款流程结束。", "tool_calls": []}
    # execute 也 done -> 最终答复（不再重复调用，避免误触发重复检测）
    return {"content": f"（mock 整合）已完成订单 {oid} 的退款流程，已原路退款。", "tool_calls": []}


def _call(name, args):
    return {"content": "", "tool_calls": [
        {"id": f"call_{name}_{int(time.time()*1000)}", "name": name,
         "arguments": json.dumps(args, ensure_ascii=False)}]}


# ---------------------------------------------------------------------------
# ③ token 估算 + ② 摘要压缩
# ---------------------------------------------------------------------------
def est_tokens(s: str) -> int:
    """粗略估算 token（无 tiktoken 依赖；生产应换真实 tokenizer）。"""
    return max(1, len(s or "") // 4)


def build_summary(older_blocks: list, use_mock: bool) -> str:
    """把被压缩的老轮次归纳成一段摘要文本。"""
    if use_mock:
        lines = []
        for m in older_blocks:
            if m.get("tool_calls"):
                for tc in m["tool_calls"]:
                    lines.append(f"调 {tc['function']['name']}({tc['function']['arguments']})")
            elif m.get("role") == "tool":
                lines.append(f"  -> {str(m.get('content', ''))[:50]}")
        return ("（上下文压缩）以下早期步骤已归纳为摘要并存入 steps 表:\n" +
                "\n".join(lines))
    try:
        joined = "\n".join(
            f"[{m['role']}] {m.get('content','')}"
            + ("".join(f"  -> 调 {tc['function']['name']}({tc['function']['arguments']})"
                       for tc in m.get('tool_calls', [])) if m.get('tool_calls') else "")
            for m in older_blocks)
        r = real_llm([
            {"role": "system", "content": "把以下 Agent 中间步骤压缩成 2-3 句中文摘要，"
                                          "保留关键事实（订单状态、物流状态、退款判定），去掉冗余。"},
            {"role": "user", "content": joined},
        ], use_tools=False)
        return r["content"] or "（摘要生成失败，使用占位）"
    except Exception as e:
        return f"（摘要生成异常，使用占位）{e}"


def maybe_compress(messages: list, keep_recent: int, use_mock: bool):
    """② 摘要压缩：保留最近 keep_recent 个『完整工具交互块』原文，更早的整块压成 summary。

    ⚠️ 协议约束（OpenAI）：role='tool' 的消息必须紧跟在带 tool_calls 的 assistant 之后。
    因此压缩以『assistant(tool_calls) + 其全部 tool 响应』为一个不可分割单元——
    要么整块保留，要么整块移入摘要，绝不能只删 assistant 却留下它的 tool 响应
    （会制造悬空 tool 响应 → 400 "tool must be response to preceding tool_calls"）。
    """
    # 找所有『工具交互块』起点 = 带 tool_calls 的 assistant 索引
    block_starts = [i for i, m in enumerate(messages)
                    if m.get("role") == "assistant" and m.get("tool_calls")]
    if len(block_starts) <= keep_recent:
        return messages, None

    first_keep = block_starts[-keep_recent]   # 从这个块开始保留原文
    prefix = messages[:block_starts[0]]      # 首个块之前的前置消息（user/system 等）
    older = messages[block_starts[0]:first_keep]  # 被整块压缩的老块（完整，不含悬空）
    tail = messages[first_keep:]             # 保留的近期原文（从第一个保留块起）
    summary = build_summary(older, use_mock)
    summary_msg = {"role": "system", "content": summary, "_summary": True}
    new_messages = prefix + [summary_msg] + tail
    return new_messages, summary


def validate_messages(messages: list) -> list:
    """防御性校验 OpenAI tool 配对协议，返回问题列表（空=合法）。

    正确规则：
      ① 每条 tool 消息的 tool_call_id 必须对应『前面某个未消费的 tool_call』（a 带多
         tool_calls 时，其多个 tool 响应连续排列是合法的，不要求紧邻前一条是 assistant）。
      ② 每个 assistant(tool_calls) 发出的 tool_call 都必须收到对应 tool 响应，否则悬空。
    """
    issues = []
    pending = {}   # tool_call_id -> True（已发出、未收到响应的工具调用）
    for i, m in enumerate(messages):
        if m.get("role") == "assistant" and m.get("tool_calls"):
            for tc in m["tool_calls"]:
                pending[tc["id"]] = True
        elif m.get("role") == "tool":
            tcid = m.get("tool_call_id")
            if tcid not in pending:
                issues.append(f"索引{i}: tool({tcid}) 找不到对应 tool_call（悬空）")
            else:
                pending.pop(tcid, None)
    if pending:
        issues.append(f"存在未闭合的 tool_calls: {list(pending.keys())}")
    return issues


def _dump_messages(messages: list):
    print("  [诊断] 当前 messages 结构：")
    for i, m in enumerate(messages):
        tc = "tool_calls=" + ",".join(t["function"]["name"] for t in m.get("tool_calls", [])) \
            if m.get("tool_calls") else ""
        tcid = f"tool_call_id={m.get('tool_call_id')}" if m.get("role") == "tool" else ""
        flag = " <<summary>>" if m.get("_summary") else ""
        print(f"    [{i}] {m.get('role'):9} {tc} {tcid}{flag}")


# ---------------------------------------------------------------------------
# 落库层（agent_runtime）：runs / steps / messages
#   未装 pymysql 或连不上 -> 自动降级为不落库（循环逻辑照常演示）
# ---------------------------------------------------------------------------
DB_ENABLED = False
_conn = None


def db_init():
    global DB_ENABLED, _conn
    if "--no-db" in sys.argv:
        print("[DB] --no-db 指定，跳过落库")
        return
    try:
        import pymysql
        _conn = pymysql.connect(
            host=os.environ.get("DB_HOST", "127.0.0.1"),
            port=int(os.environ.get("DB_PORT", "3306")),
            user=os.environ.get("DB_USERNAME", "root"),
            password=os.environ.get("DB_PASSWORD", ""),
            database=os.environ.get("DB_NAME", "agent_runtime"),
            connect_timeout=5)
        DB_ENABLED = True
        print("[DB] 已连接 agent_runtime，落库开启")
    except Exception as e:
        DB_ENABLED = False
        print(f"[DB] 未启用落库（{type(e).__name__}: 循环逻辑照常演示）: {e}")


def db_cursor():
    if _conn:
        try:
            _conn.ping()
        except Exception:
            pass
        return _conn.cursor()


def db_insert_conversation(agent_id):
    if not DB_ENABLED:
        return None
    cur = db_cursor()
    cur.execute("INSERT INTO conversations (agent_id, status, created_at, updated_at) "
                "VALUES (%s,1,NOW(),NOW())", (agent_id,))
    _conn.commit()
    return cur.lastrowid


def db_insert_run(agent_id, task_input, model, conversation_id=None):
    if not DB_ENABLED:
        return None
    cur = db_cursor()
    cur.execute(
        "INSERT INTO runs (agent_id, conversation_id, task_input, model, status, created_at, updated_at) "
        "VALUES (%s,%s,%s,%s,'running',NOW(),NOW())",
        (agent_id, conversation_id, task_input, model))
    _conn.commit()
    return cur.lastrowid


def db_update_run(run_id, status, ended_reason, total_steps, total_tokens):
    if not DB_ENABLED or run_id is None:
        return
    cur = db_cursor()
    cur.execute(
        "UPDATE runs SET status=%s, ended_reason=%s, total_steps=%s, total_tokens=%s, "
        "finished_at=NOW(), updated_at=NOW() WHERE id=%s",
        (status, ended_reason, total_steps, total_tokens, run_id))
    _conn.commit()


def db_insert_step(run_id, step_no, span_type, thought=None, tool_name=None,
                   tool_args=None, observation=None, status="success",
                   guardrail=None, dedup_key=None, tokens=0, latency_ms=0):
    if not DB_ENABLED or run_id is None:
        return
    cur = db_cursor()
    cur.execute(
        "INSERT INTO steps (run_id, step_no, span_type, thought, tool_name, tool_args, "
        "observation, status, guardrail, dedup_key, tokens, latency_ms, created_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())",
        (run_id, step_no, span_type, thought, tool_name,
         json.dumps(tool_args, ensure_ascii=False) if tool_args is not None else None,
         observation, status, guardrail, dedup_key, tokens, latency_ms))
    _conn.commit()


def db_insert_message(run_id, conversation_id, role, content, kind="normal",
                      tool_call_id=None, metadata=None):
    if not DB_ENABLED or run_id is None:
        return
    cur = db_cursor()
    cur.execute(
        "INSERT INTO messages (conversation_id, run_id, role, content, kind, tool_call_id, metadata, created_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,NOW())",
        (conversation_id, run_id, role, content, kind, tool_call_id,
         json.dumps(metadata, ensure_ascii=False) if metadata else None))
    _conn.commit()


# ---------------------------------------------------------------------------
# 主循环：while 实现 tool_call -> 执行 -> 回填 -> 再请求，叠加四件套 + 落库
# ---------------------------------------------------------------------------
def run_agent(user_input: str, use_mock: bool) -> dict:
    db_init()
    model = (os.environ.get("OPENAI_MODEL") or os.environ.get("MODEL") or "mock").split("/")[-1]
    conv_id = db_insert_conversation(1)             # agent_id=1 (seed 的 refund-agent)
    run_id = db_insert_run(1, user_input, model, conv_id)
    if run_id:
        db_insert_message(run_id, conv_id, "user", user_input, kind="normal")

    messages = [{"role": "user", "content": user_input}]
    total_tokens = 0
    start_ts = time.time()
    done_tools = set()   # 已执行工具集合（独立于 messages，压缩后不丢失）

    # ④ 重复调用检测状态：跟踪「上一key」与连续计数
    last_key = None
    repeat_count = 0

    run_status = "done"
    ended_reason = "completed"

    for step in range(1, MAX_STEPS + 1):
        # ② 整体运行超时
        if time.time() - start_ts > RUN_TIMEOUT:
            run_status, ended_reason = "guarded", "timeout"
            print(f"\n⚠️ 整体运行超时（>{RUN_TIMEOUT}s），熔断")
            break

        print(f"\n===== 第 {step} 轮 | messages 共 {len(messages)} 条 =====")
        # 防御性校验：真实模式发请求前，确保 messages 满足 OpenAI tool 配对协议
        if not use_mock:
            issues = validate_messages(messages)
            if issues:
                _dump_messages(messages)
                raise RuntimeError("messages 违反 OpenAI tool 配对协议，已拦截。问题: "
                                   + "; ".join(issues))
        t0 = time.time()
        norm = mock_llm(messages, done_tools) if use_mock else real_llm(messages)
        llm_latency = int((time.time() - t0) * 1000)
        llm_tokens = est_tokens(json.dumps(norm, ensure_ascii=False))
        total_tokens += llm_tokens

        # Thought（ReAct 的 Thought）：assistant 的 content
        thought = norm["content"]
        assistant_msg = {"role": "assistant", "content": thought}
        if norm["tool_calls"]:
            assistant_msg["tool_calls"] = [
                {"id": t["id"], "type": "function",
                 "function": {"name": t["name"], "arguments": t["arguments"]}}
                for t in norm["tool_calls"]]
        messages.append(assistant_msg)
        # 落库：llm span（含 Thought）+ messages
        db_insert_step(run_id, step, "llm", thought=thought, tokens=llm_tokens,
                       latency_ms=llm_latency, status="success")
        db_insert_message(run_id, conv_id, "assistant", thought or "", kind="normal")

        if not norm["tool_calls"]:
            print("模型最终回答：", thought)
            run_status, ended_reason = "done", "completed"
            break

        # 逐个执行工具（串行；并行见 W03 README 说明）
        for t in norm["tool_calls"]:
            name, args_json = t["name"], t["arguments"]
            canonical = json.dumps(json.loads(args_json) if args_json else {},
                                  sort_keys=True, ensure_ascii=False)
            key = f"{name}|{canonical}"

            # ④ 重复调用检测：同一 key 连续出现 -> 拦
            if key == last_key:
                repeat_count += 1
            else:
                repeat_count = 1
                last_key = key
            if repeat_count > REPEAT_LIMIT:
                obs = (f"⚠️ 重复调用检测：工具 {name} 以相同参数连续调用 {repeat_count} 次，"
                       f"已拦截以防死循环（guardrail=repeat）")
                messages.append({"role": "tool", "tool_call_id": t["id"], "content": obs})
                db_insert_step(run_id, step, "tool", tool_name=name, tool_args=json.loads(args_json) if args_json else {},
                               observation=obs, status="repeat_blocked", guardrail="repeat",
                               dedup_key=key, tokens=0, latency_ms=0)
                db_insert_message(run_id, conv_id, "tool", obs, kind="normal", tool_call_id=t["id"])
                run_status, ended_reason = "guarded", "repeat"
                print(f"  🛑 {obs}")
                # 拦截后直接终止 run（死循环已收口）
                db_update_run(run_id, run_status, ended_reason, step, total_tokens)
                return {"run_id": run_id, "status": run_status, "messages": messages,
                        "total_tokens": total_tokens}

            # ② 超时熔断 + ③ 异常转字符串（统一在 run_with_timeout + execute_tool_safe 收口）
            t0 = time.time()
            result, timed_out = run_with_timeout(execute_tool_safe, TOOL_TIMEOUT, name, args_json)
            tool_latency = int((time.time() - t0) * 1000)
            status = "timeout" if timed_out else "success"
            guardrail = "timeout" if timed_out else None
            total_tokens += est_tokens(result)

            print(f"  -> 执行工具 {name}({args_json})")
            print(f"  <- 回填: {result[:120]}")
            messages.append({"role": "tool", "tool_call_id": t["id"], "content": result})
            db_insert_step(run_id, step, "tool", tool_name=name,
                           tool_args=json.loads(args_json) if args_json else {},
                           observation=result, status=status, guardrail=guardrail,
                           dedup_key=key, tokens=est_tokens(result), latency_ms=tool_latency)
            db_insert_message(run_id, conv_id, "tool", result, kind="normal", tool_call_id=t["id"])
            done_tools.add(name)   # 标记已执行（独立于 messages，压缩不丢失）

        # ② 摘要压缩：messages 过长则压缩老轮次（Layer 2）
        before = len(messages)
        messages, summary = maybe_compress(messages, KEEP_RECENT, use_mock)
        if summary:
            print(f"  🗜️ 触发摘要压缩：{before} 条 -> {len(messages)} 条（老轮次存入 steps 表）")
            if run_id:
                db_insert_message(run_id, conv_id, "system", summary, kind="summary",
                                  metadata={"compressed_from_turns": before})

        # ③ token 预算：达到硬熔断直接终止
        if total_tokens > TOKEN_HARD:
            run_status, ended_reason = "guarded", "token_budget"
            print(f"\n⚠️ 超过 token 硬熔断 {TOKEN_HARD}，终止")
            break
        # ③ token 预算：达到软预算则下一轮会触发摘要压缩（已在上方面对 KEEP_RECENT 演示）

    else:
        # while 跑满 MAX_STEPS 没 break -> 步数上限触发（最后兜底墙）
        run_status, ended_reason = "guarded", "max_steps"
        print(f"\n⚠️ 达到步数上限 {MAX_STEPS}，强制收口（防护①最后兜底）")

    db_update_run(run_id, run_status, ended_reason, min(step, MAX_STEPS), total_tokens)
    return {"run_id": run_id, "status": run_status, "messages": messages,
            "total_tokens": total_tokens}


# ---------------------------------------------------------------------------
# 演示：异常转字符串 / 幂等 / 重复拦截 / 超时（绕过 LLM 直接打工具）
# ---------------------------------------------------------------------------
def demo_edge():
    print("\n##### ③ 异常不抛，转成字符串回填给模型 #####")
    os.environ["W04_DEADLOOP"] = "1"   # 临时开启，让 query_logistics 真正抛异常
    print("query_logistics 抛异常 ->",
          execute_tool_safe("query_logistics", '{"order_id":"NO20260911001"}'))
    del os.environ["W04_DEADLOOP"]

    print("\n##### 幂等：相同订单退两次，第二次被去重 #####")
    a = execute_tool_safe("execute_refund", '{"order_id":"NOX","amount":10}')
    b = execute_tool_safe("execute_refund", '{"order_id":"NOX","amount":10}')
    print("第一次：", a)
    print("第二次：", b)

    print("\n##### ④ 重复调用检测：相同参数连续调 4 次，第 4 次被拦 #####")
    last, cnt = None, 0
    for i in range(4):
        key = f"query_logistics|{{\"order_id\": \"NO1\"}}"
        if key == last:
            cnt += 1
        else:
            cnt, last = 1, key
        blocked = cnt > REPEAT_LIMIT
        print(f"  第{i+1}次 key={key} 连续计数={cnt} -> {'🛑拦截' if blocked else '放行'}")

    print("\n##### ② 超时熔断（sleep 10s > TOOL_TIMEOUT 8s）#####")
    res, to = run_with_timeout(lambda: time.sleep(10) or "done", TOOL_TIMEOUT)
    print("结果：", res, "| 是否超时：", to)


def main():
    if "--edge" in sys.argv:
        demo_edge()
        return

    use_mock = "--mock" in sys.argv
    if not use_mock and not (os.environ.get("OPENAI_API_KEY") or os.environ.get("API_KEY")):
        print("未检测到 API Key（OPENAI_API_KEY 或 API_KEY），自动切 --mock 演示。\n"
              "真实调用：双击 start-env-windows.bat 后在弹出窗口 python agent.py\n")
        use_mock = True

    if os.environ.get("W04_DEADLOOP") == "1":
        print("⚠️ 死循环模式：物流接口将恒失败，用于验证防护④\n")

    # 支持 --order NOxxxx 指定订单号（默认 NO20260911001 可退；NO20260911002 运输中不可退）
    order_arg = None
    for a in sys.argv:
        m = re.search(r"(NO\d+)", a)
        if m:
            order_arg = m.group(1)
            break
    demo = f"帮我处理订单 {order_arg or 'NO20260911001'} 的退款"
    print("演示输入：", demo)
    result = run_agent(demo, use_mock)
    print(f"\n===== run 结束 | run_id={result['run_id']} status={result['status']} "
          f"tokens≈{result['total_tokens']} =====")
    if result["run_id"]:
        print("（可用 SELECT * FROM steps WHERE run_id=? 回放每一步）")


if __name__ == "__main__":
    main()
