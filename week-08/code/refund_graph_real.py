"""W08 v3: 真实 API 模式（ChatOpenAI 驱动 tool_calls + PostgresSaver 持久化 + interrupt 人工批准）

与前两版的区别（融合 v1 图结构 + v2 持久化 + 真实 LLM）：
  - 模型用真实 LLM（ChatOpenAI），由 LLM 自己决定何时 fetch_order / request_refund（真正的 ReAct 循环）
  - v1/v2 用 MockModel 是"替 LLM 决定步骤"；这里让真实模型跑
  - 真实退款端点用 mock（simulate_refund_api），不真扣钱，但演示「危险操作需幂等 + 人工批准」
  - 编译用 PostgresSaver（接 w08lg），进程崩溃 / 跨天批准都能按 thread_id 续

前置（本机 PowerShell，bat 已设 API_KEY/BASE_URL/MODEL）：
  1) pgvector 容器在跑 + w08lg 库已建（同 v2）：
     $PG_CONTAINER_ID = (docker ps -q --filter "ancestor=pgvector/pgvector:0.8.6-pg17")
     docker exec -i $PG_CONTAINER_ID psql -U amber -d template1 -c "CREATE DATABASE w08lg OWNER amber;"
  2) langchain-openai 已装（共享 venv 已装好，无需再装）
  3) 连接信息走环境变量（不写死）：
     $env:PG_HOST="127.0.0.1"; $env:PG_PORT="5432"; $env:PG_DB="w08lg"
     $env:PG_USER="amber"; $env:PG_PASSWORD="amber123"

运行：
  cd w08-scratch
  $env:W08_REAL="1"
  python refund_graph_real.py
"""

import os
import psycopg
from typing import TypedDict, Annotated

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import interrupt, Command
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

# ---------- 配置：只从环境变量读，不写死 Key ----------
API_KEY = os.getenv("API_KEY")
BASE_URL = os.getenv("BASE_URL")
# chat 模型：优先 CHAT_MODEL（区分场景），兼容老脚本读 MODEL
CHAT_MODEL = os.getenv("CHAT_MODEL") or os.getenv("MODEL", "deepseek-v4-flash")

PG_DB = os.getenv("PG_DB", "w08lg")
PG_USER = os.getenv("PG_USER", "amber")
PG_PASSWORD = os.getenv("PG_PASSWORD", "amber123")
PG_HOST = os.getenv("PG_HOST", "127.0.0.1")
PG_PORT = os.getenv("PG_PORT", "5432")

# ---------- mock 订单库（真实模式替换为你的业务库查询）----------
ORDERS = {
    "ORD-1001": {"order_id": "ORD-1001", "status": "paid", "amount": 100, "user": "amber"},
}
ORDER_ID = "ORD-1001"


# ---------- State：业务状态活在带类型字段里，不靠 messages 解析 ----------
class State(TypedDict):
    messages: Annotated[list, add_messages]   # 对话笔录（LLM 用，累加）
    order_id: str                             # 查询键（覆盖）
    order: dict                               # 订单快照 status/amount/user（覆盖，工具刷新）
    refunded: bool                            # 是否已退款（覆盖，guard 标记）


# ---------- 工具（mock；真实模式把函数体换成 API 调用）----------
@tool
def fetch_order(order_id: str) -> dict:
    """按 order_id 查订单，返回订单快照。"""
    return ORDERS.get(order_id, {"error": "not found"})


@tool
def request_refund(order_id: str) -> dict:
    """发起退款请求：把订单标记为 pending_refund，返回待确认信息。"""
    o = ORDERS[order_id]
    o["status"] = "pending_refund"
    return {"order_id": order_id, "amount": o["amount"], "msg": "退款待批准"}


TOOLS = [fetch_order, request_refund]


# ---------- 真实退款端点（mock，不真扣钱）：演示危险操作需幂等 ----------
def simulate_refund_api(order_id: str, amount: int, idempotency_key: str) -> dict:
    """生产里换成你的退款网关 HTTP 调用。
    幂等键防止小节3 讲的「node 重入重复扣款」：崩溃续跑时同一 key 不会重复退款。
    """
    print(f"  [调用退款API-mock] order={order_id} amount={amount} idempotency={idempotency_key}")
    # 真实实现示例（示意，不执行）：
    #   requests.post(REFUND_URL, json={"order_id": order_id, "amount": amount},
    #                 headers={"Idempotency-Key": idempotency_key})
    return {"ok": True, "txn": f"mock-{idempotency_key}"}


# ---------- 节点 ----------
def call_model(state):
    model = ChatOpenAI(model=CHAT_MODEL, api_key=API_KEY, base_url=BASE_URL).bind_tools(TOOLS)
    resp = model.invoke(state["messages"])
    return {"messages": [resp]}


def call_tool(state):
    last = state["messages"][-1]
    outputs = []
    for tc in last.tool_calls:
        fn = next(t for t in TOOLS if t.name == tc["name"])
        result = fn.invoke(tc["args"])               # 真实执行工具（request_refund 翻状态）
        outputs.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))
    # 工具执行后刷新订单快照（覆盖写回，下游直接读 state["order"]）
    order = dict(ORDERS.get(state["order_id"], {}))
    return {"messages": outputs, "order": order}


def approve_refund(state):
    # 危险操作前挂起，把待确认信息返回给调用方；checkpoint 已落库，进程可退出
    decision = interrupt({"ask": f"确认退款 ¥{state['order']['amount']}？"})
    if decision.get("approve"):
        # 幂等键 = order_id（演示用；生产加 thread_id 更稳），防 node 重入重复退款
        simulate_refund_api(state["order_id"], state["order"]["amount"],
                            idempotency_key=f"refund-{state['order_id']}")
        ORDERS[state["order_id"]]["status"] = "refunded"
        return {"refunded": True, "order": dict(ORDERS[state["order_id"]])}
    return {"refunded": False, "order": dict(ORDERS[state["order_id"]])}


def should_continue(state):
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
        return "call_tool"                           # 还有工具要执行
    # 无 tool_calls：用结构化状态路由，而不是"模型调了哪个工具"的隐式约定
    if state["order"].get("status") == "pending_refund":
        return "approve_refund"                      # 退款请求已发起 → 人工批准
    return END


# ---------- 编译：真实 LLM + PostgresSaver 持久化 ----------
g = StateGraph(State)
g.add_node("call_model", call_model)
g.add_node("call_tool", call_tool)
g.add_node("approve_refund", approve_refund)
g.add_edge(START, "call_model")
g.add_conditional_edges("call_model", should_continue)
g.add_edge("call_tool", "call_model")
g.add_edge("approve_refund", END)


def connect():
    # autocommit=True：setup() 内含 CREATE INDEX CONCURRENTLY，不能在事务块中运行
    return psycopg.connect(
        f"dbname={PG_DB} user={PG_USER} password={PG_PASSWORD} host={PG_HOST} port={PG_PORT}",
        autocommit=True,
    )


if __name__ == "__main__":
    if not API_KEY:
        raise SystemExit("未检测到 API_KEY，请先用 start-env-windows.bat 加载环境变量后再跑 v3。")

    cfg = {"configurable": {"thread_id": "refund-real-1"}}

    conn = connect()
    saver = PostgresSaver(conn)
    saver.setup()                       # 首次自动建表
    app = g.compile(checkpointer=saver)

    # 第 1 次：真实 LLM 跑 ReAct 循环，跑到 interrupt() 挂起（进程此刻可退出）
    print("=== 第1次 invoke（真实 LLM，跑到 interrupt 挂起）===")
    app.invoke(
        {
            "messages": [HumanMessage("给我退 ORD-1001")],
            "order_id": ORDER_ID,
            "order": {},
            "refunded": False,
        },
        cfg,
    )
    snap = app.get_state(cfg)
    print("挂起点 next      :", snap.next)             # ('approve_refund',)
    print("order 快照       :", snap.values["order"])   # status=pending_refund
    print("refunded         :", snap.values["refunded"])

    # 隔了一天，用户批准 → 同 thread_id + Command(resume=...)
    print("\n=== 隔天批准，Command(resume=...) 续跑（真实退款端点被调用）===")
    app.invoke(Command(resume={"approve": True}), cfg)
    final = app.get_state(cfg).values
    print("最终 next        :", app.get_state(cfg).next)  # ()
    print("order 快照       :", final["order"])           # status=refunded
    print("refunded         :", final["refunded"])
    print("\n✅ 真实 LLM + PostgresSaver 持久化 + interrupt 人工批准 全链路验证")
    conn.close()
