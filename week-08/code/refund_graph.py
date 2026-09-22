"""W08 退款 Agent —— LangGraph 版（v1: MemorySaver + mock 工具 + interrupt 人工批准）

对应课程第六小节蓝图：
  START → call_model →(条件边) call_tool / approve_refund / END
  call_tool → call_model（回边，显式化 W04 的 while 循环）
  approve_refund 用 interrupt() 在真实退款前挂起，等人批准

关键设计（来自第六小节你的 State 设计）：
  - 业务状态活在带类型字段 order 里，工具执行后覆盖写回，下游直接读，不解析 messages
  - 路由判断用 state["order"]["status"]（结构化状态），而不是"模型调了哪个工具"的隐式约定

运行：
  python refund_graph.py
v1 默认用内置 MockModel 验证图结构（循环 + 结构化状态路由 + interrupt 续跑），零额外依赖。
  即使在 bat 环境（已设 API_KEY）也默认走 MockModel，不联网、不依赖 langchain_openai。
真实 API 模式：设 W08_REAL=1 且存在 API_KEY / BASE_URL / MODEL（走 start-env-windows.bat），脚本才用 ChatOpenAI。
"""

import os
from typing import TypedDict, Annotated

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt, Command
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import tool

# ---------- 配置：只从环境变量读，不写死 Key ----------
API_KEY = os.getenv("API_KEY")
BASE_URL = os.getenv("BASE_URL")
# chat 模型：优先 CHAT_MODEL（区分场景），兼容老脚本读 MODEL
CHAT_MODEL = os.getenv("CHAT_MODEL") or os.getenv("MODEL", "deepseek-v4-flash")

# ---------- mock 订单库（真实模式替换为你的业务库查询）----------
ORDERS = {
    "ORD-1001": {"order_id": "ORD-1001", "status": "paid", "amount": 100, "user": "amber"},
}
# mock：脚本内固定订单号；真实模式由用户首条消息带入
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


# ---------- 模型：v1 默认 MockModel 验证图结构（零依赖）。
#            设 W08_REAL=1 且存在 API_KEY 才走真实 ChatOpenAI（v3 用）。----------
_WARNED_MOCK = False
def get_model():
    global _WARNED_MOCK
    use_real = os.getenv("W08_REAL") == "1" and bool(API_KEY)
    if not use_real:
        if API_KEY and not _WARNED_MOCK:
            print("  [MockModel] 检测到 API_KEY 但未设 W08_REAL=1，默认用 MockModel 验证图结构")
            _WARNED_MOCK = True
        return MockModel()
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(model=CHAT_MODEL, api_key=API_KEY, base_url=BASE_URL).bind_tools(TOOLS)


class MockModel:
    """无 Key 时验证图结构：第1步 fetch_order，第2步 request_refund，第3步请人批准。"""
    def bind_tools(self, tools):
        self.tools = tools
        return self

    def invoke(self, messages):
        n_tool = sum(1 for m in messages if isinstance(m, ToolMessage))
        if n_tool == 0:
            return AIMessage(
                content="先查一下订单",
                tool_calls=[{"id": "c1", "name": "fetch_order", "args": {"order_id": ORDER_ID}}],
            )
        if n_tool == 1:
            return AIMessage(
                content="发起退款请求",
                tool_calls=[{"id": "c2", "name": "request_refund", "args": {"order_id": ORDER_ID}}],
            )
        # 工具结果已齐，请人工批准（不再有 tool_calls）
        return AIMessage(content="订单已查、退款请求已发起，请人工批准。")


# ---------- 节点 ----------
def call_model(state):
    model = get_model()
    resp = model.invoke(state["messages"])
    return {"messages": [resp]}


def call_tool(state):
    last = state["messages"][-1]
    outputs = []
    for tc in last.tool_calls:
        fn = next(t for t in TOOLS if t.name == tc["name"])
        result = fn.invoke(tc["args"])               # 真实执行工具（request_refund 会把状态翻成 pending_refund）
        outputs.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))
    # 工具执行后刷新订单快照（覆盖写回，下游直接读 state["order"]）
    order = dict(ORDERS.get(state["order_id"], {}))
    return {"messages": outputs, "order": order}


def approve_refund(state):
    # 危险操作前挂起，把待确认信息返回给调用方；checkpoint 已落库，进程可退出
    decision = interrupt({"ask": f"确认退款 ¥{state['order']['amount']}？"})
    if decision.get("approve"):
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


# ---------- 编译（v1 用 MemorySaver；阶段2 后续换 PostgresSaver 接 gp17）----------
g = StateGraph(State)
g.add_node("call_model", call_model)
g.add_node("call_tool", call_tool)
g.add_node("approve_refund", approve_refund)
g.add_edge(START, "call_model")
g.add_conditional_edges("call_model", should_continue)
g.add_edge("call_tool", "call_model")
g.add_edge("approve_refund", END)
app = g.compile(checkpointer=MemorySaver())


if __name__ == "__main__":
    cfg = {"configurable": {"thread_id": "refund-1"}}

    # 第 1 次：跑到 interrupt() 挂起（进程此刻可退出）
    print("=== 第1次 invoke（跑到 interrupt 挂起）===")
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
    print("order 快照       :", snap.values["order"])   # status=pending_refund（request_refund 已执行）
    print("refunded         :", snap.values["refunded"])

    # 隔了一天，用户批准 → 同 thread_id + Command(resume=...)
    print("\n=== 隔天批准，Command(resume=...) 续跑 ===")
    app.invoke(Command(resume={"approve": True}), cfg)
    final = app.get_state(cfg).values
    print("最终 next        :", app.get_state(cfg).next)  # ()
    print("order 快照       :", final["order"])           # status=refunded
    print("refunded         :", final["refunded"])
    print("\n✅ 图跑通：循环(call_model↔call_tool) + 结构化状态路由 + interrupt 挂起 + 同 thread_id 续跑均验证")
