"""W09 财报 Agent —— LangGraph 版（零依赖规则版：验证编排 + interrupt + streaming）。

图形状（流水线 DAG + 一处人工批准）：
  START -> classify -> extract -> human_review(interrupt) -> normalize_persist -> verify -> END

复用 W08 的三件宝贝：
  1. MemorySaver checkpointer：同一 thread_id 可挂起后隔天续跑
  2. interrupt()：在"批量写库"这个危险操作前挂起，等人批准（对应 W08 的 approve_refund）
  3. 结构化状态路由：state 字段直接读，不解析 messages

与 W08 的区别：
  W08 是 对话式 while 循环(call_model <-> call_tool)；本图是 流水线 DAG，无 LLM 循环。
  因为 MVP 的 classify/extract 是规则版（extract 不调 LLM）。
  LLM 抽取节点留 TODO：真实年报用 LLM 从 PDF 抽表 -> extract_rows。

下一步（W09 ③）：FastAPI 用 app.stream() 把每个节点包成 SSE 帧转发给 Laravel。

运行（零 Key）：
  python graph.py
"""
from typing import TypedDict, Annotated

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt, Command
from langchain_core.messages import HumanMessage

import db
import extract
import normalize
import query


# ---------- 共享小工具：公司/报告期 upsert（自包含，不依赖 demo） ----------
def ensure_company(code, name, exchange):
    conn = db.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO fin_companies (code,name,exchange) VALUES (%s,%s,%s) "
                "ON DUPLICATE KEY UPDATE name=%s",
                (code, name, exchange, name),
            )
            conn.commit()
            cur.execute("SELECT id FROM fin_companies WHERE code=%s", (code,))
            return cur.fetchone()["id"]
    finally:
        conn.close()


def ensure_report(company_id, year):
    conn = db.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM fin_reports WHERE company_id=%s AND year=%s AND report_type='annual'",
                (company_id, year),
            )
            row = cur.fetchone()
            if row:
                return row["id"]
            cur.execute(
                "INSERT INTO fin_reports (company_id,year,report_type) VALUES (%s,%s,'annual')",
                (company_id, year),
            )
            conn.commit()
            return cur.lastrowid
    finally:
        conn.close()


# ---------- State：业务状态活在带类型字段，messages 仅作笔录 ----------
class State(TypedDict):
    messages: Annotated[list, add_messages]   # 笔录（LLM 用，累加）
    company_code: str
    company_name: str
    exchange: str
    year: int
    report_type: str                          # classify 产出（规则版直接读入参）
    raw_rows: list                            # 抽取输入
    rows: list                                # extract 产出 [(raw_name,value,unit,page)]
    report_id: int                            # ensure_report 产出
    decisions: list                          # normalize_persist 产出
    verification: list                       # verify 产出
    confirmed: bool                          # human_review 的 interrupt resume 结果
    auto_approve: bool                       # query 端点为真则跳过 interrupt 直接批准


# ---------- 节点 ----------
def classify(state):
    # TODO(真实模式): 用 LLM 判断 合并/母公司、年报/季报/中报
    # 规则版：直接采用入参 report_type（默认 annual）
    rt = state.get("report_type") or "annual"
    return {"report_type": rt}


def extract_node(state):
    rows = extract.extract_rows(state["raw_rows"])
    return {"rows": rows}


def human_review(state):
    # 复用 W08 的 interrupt：批量写库前挂起，等人批准
    # auto_approve=True 时（/agent/query 流式问值路径）跳过 interrupt 直接批准
    if state.get("auto_approve"):
        return {"confirmed": True}
    n = len(state["rows"])
    prompt = (f"确认将导入 {n} 条指标到 {state['company_name']} "
              f"{state['year']}（{state['report_type']}）？")
    preview = [r[0] for r in state["rows"][:5]]
    print(f"  [需人工批准] {prompt}  预览: {preview}")
    decision = interrupt({"ask": prompt, "preview": preview})
    return {"confirmed": bool(decision.get("approve"))}


def normalize_persist(state):
    if not state.get("confirmed"):
        return {"decisions": []}   # 未批准则不写库（after_review 已路由到 END）
    cid = ensure_company(state["company_code"], state["company_name"], state.get("exchange", "SH"))
    rid = ensure_report(cid, state["year"])
    decisions = []
    for raw_name, value, unit, page in state["rows"]:
        d = normalize.normalize(raw_name, report_id=rid, page=page)
        normalize.persist(rid, raw_name, value, unit, page, d)
        decisions.append({
            "raw_name": raw_name,
            "code": d.get("matched_code"),
            "status": d["status"],
            "method": d["method"],
        })
    return {"report_id": rid, "decisions": decisions}


def verify(state):
    # 零误匹配验证：扣非(NP_DEDUCT) vs 归母(NP_PARENT)
    d = query.query_indicator(state["company_code"], state["year"], "NP_DEDUCT")
    p = query.query_indicator(state["company_code"], state["year"], "NP_PARENT")

    def to_yi(row):
        return float(row["value"]) / 1e8 if row else None

    dv, pv = to_yi(d), to_yi(p)
    ok = dv is not None and pv is not None and abs(dv - pv) > 0.01
    return {"verification": [{
        "company": state["company_name"],
        "year": state["year"],
        "deduct": dv,
        "parent": pv,
        "zero_mismatch": ok,
    }]}


def after_review(state):
    return "normalize_persist" if state.get("confirmed") else END


# ---------- 编译（复用 W08 的 MemorySaver） ----------
g = StateGraph(State)
g.add_node("classify", classify)
g.add_node("extract_node", extract_node)
g.add_node("human_review", human_review)
g.add_node("normalize_persist", normalize_persist)
g.add_node("verify", verify)
g.add_edge(START, "classify")
g.add_edge("classify", "extract_node")
g.add_edge("extract_node", "human_review")
g.add_conditional_edges("human_review", after_review)
g.add_edge("normalize_persist", "verify")
g.add_edge("verify", END)
app = g.compile(checkpointer=MemorySaver())


def build_input(company_code, company_name, exchange, year, raw_rows, report_type="annual", auto_approve=False):
    return {
        "messages": [HumanMessage(f"导入 {company_name} {year} 年报")],
        "company_code": company_code,
        "company_name": company_name,
        "exchange": exchange,
        "year": year,
        "report_type": report_type,
        "raw_rows": raw_rows,
        "rows": [],
        "decisions": [],
        "verification": [],
        "confirmed": False,
        "auto_approve": auto_approve,
    }


def summarize(node, vals):
    if node == "extract_node":
        return f"抽取 {len(vals.get('rows', []))} 行"
    if node == "normalize_persist":
        ds = vals.get("decisions", [])
        matched = sum(1 for x in ds if x["status"] == "matched")
        return f"落库 {len(ds)} 条（命中 {matched}）"
    if node == "verify":
        v = (vals.get("verification") or [{}])[0]
        return (f"零误匹配验证: {'✅' if v.get('zero_mismatch') else '❌'} "
                f"扣非={v.get('deduct')}亿 归母={v.get('parent')}亿")
    if node == "classify":
        return f"报表类型={vals.get('report_type')}"
    return str(vals)[:80]


# 演示样本（与 pipeline_demo 一致；真实模式替换为 docling 解析结果）
MAOTAI_ROWS = [
    {"raw_name": "营业总收入", "value_raw": "1741.02", "unit": "亿元", "page": 12},
    {"raw_name": "归属于上市公司股东的净利润", "value_raw": "862.28", "unit": "亿元", "page": 12},
    {"raw_name": "归属于上市公司股东的扣除非经常性损益的净利润", "value_raw": "861.95", "unit": "亿元", "page": 12},
    {"raw_name": "稀释每股收益", "value_raw": "69.00", "unit": "元", "page": 12},
    {"raw_name": "总资产", "value_raw": "2989.45", "unit": "亿元", "page": 20},
    {"raw_name": "经营活动产生的现金流量净额", "value_raw": "924.56", "unit": "亿元", "page": 30},
]


if __name__ == "__main__":
    cfg = {"configurable": {"thread_id": "w09-maotai-2025"}}
    inp = build_input("600519", "贵州茅台", "SH", 2025, MAOTAI_ROWS)

    print("=== 第1段 stream（跑到 human_review 的 interrupt 挂起）===")
    for chunk in app.stream(inp, cfg, stream_mode="updates"):
        for node, vals in chunk.items():
            print(f"  [stream] {node}: {summarize(node, vals)}")

    snap = app.get_state(cfg)
    print("挂起点 next:", snap.next)          # ('human_review',)
    print("confirmed  :", snap.values.get("confirmed"))

    print("\n=== 第2段：人工批准，Command(resume=...) 续跑 ===")
    for chunk in app.stream(Command(resume={"approve": True}), cfg, stream_mode="updates"):
        for node, vals in chunk.items():
            print(f"  [stream] {node}: {summarize(node, vals)}")

    v = app.get_state(cfg).values["verification"][0]
    print(f"\n✅ 图跑通：DAG(classify→extract→human_review→normalize_persist→verify) "
          f"+ interrupt 挂起 + 同 thread_id 续跑 + 零误匹配={'✅' if v['zero_mismatch'] else '❌'}")
