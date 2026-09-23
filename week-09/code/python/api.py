"""W09 财报 Agent —— FastAPI 把 LangGraph 图暴露为 SSE 流（Laravel 调用端的数据源）。

这是「服务化边界」里 Python 侧的 HTTP 出口：
  - /agent/query  问值/导入一条年报：auto_approve=True，逐节点流式返回中间过程
  - /agent/import 批量导入长任务：auto_approve=False 挂起 -> 返回 thread_id -> 带 thread_id+confirm 续跑
    （演示 W08 interrupt 在 HTTP 上的对应物：批量写库前人工批准）

Laravel 调用端用 Guzzle stream(true) 消费本服务的 SSE，再用 Response::stream() 原样转发浏览器。

依赖: fastapi, uvicorn  (langgraph 已装)
运行: uvicorn api:app --port 8000
测试:
  curl -N "http://127.0.0.1:8000/agent/query?company_code=600519&year=2025"
  curl -N "http://127.0.0.1:8000/agent/import?company_code=600519&year=2025"   # 拿 thread_id
  curl -N "http://127.0.0.1:8000/agent/import?thread_id=<上一步>&confirm=true"  # 批准续跑

注: MVP 样本为硬编码 demo 科目；真实模式把 SAMPLES 换成 docling 解析结果。
"""
import json

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from langgraph.types import Command

import graph

app = FastAPI(title="FinReportAgent")

# ---------- MVP 样本（按 company_code 路由；真实模式替换为 docling 解析结果） ----------
NAME_MAP = {"600519": "贵州茅台", "300750": "宁德时代", "002594": "比亚迪"}
SAMPLES = {
    "600519": [
        {"raw_name": "营业总收入", "value_raw": "1741.02", "unit": "亿元", "page": 12},
        {"raw_name": "归属于上市公司股东的净利润", "value_raw": "862.28", "unit": "亿元", "page": 12},
        {"raw_name": "归属于上市公司股东的扣除非经常性损益的净利润", "value_raw": "861.95", "unit": "亿元", "page": 12},
        {"raw_name": "稀释每股收益", "value_raw": "69.00", "unit": "元", "page": 12},
        {"raw_name": "总资产", "value_raw": "2989.45", "unit": "亿元", "page": 20},
        {"raw_name": "经营活动产生的现金流量净额", "value_raw": "924.56", "unit": "亿元", "page": 30},
    ],
    "300750": [
        {"raw_name": "营业收入", "value_raw": "3620.13", "unit": "亿元", "page": 15},
        {"raw_name": "归属于上市公司股东的净利润", "value_raw": "507.45", "unit": "亿元", "page": 15},
        {"raw_name": "归属于上市公司股东的扣除非经常性损益的净利润", "value_raw": "540.23", "unit": "亿元", "page": 15},
        {"raw_name": "净利润", "value_raw": "515.00", "unit": "亿元", "page": 15},
        {"raw_name": "资产总计", "value_raw": "7866.58", "unit": "亿元", "page": 22},
    ],
    "002594": [
        {"raw_name": "营业总收入", "value_raw": "7771.02", "unit": "亿元", "page": 10},
        {"raw_name": "归属于上市公司股东的净利润", "value_raw": "402.54", "unit": "亿元", "page": 10},
        {"raw_name": "归属于上市公司股东的扣除非经常性损益的净利润", "value_raw": "369.83", "unit": "亿元", "page": 10},
        {"raw_name": "净利润", "value_raw": "415.00", "unit": "亿元", "page": 10},
        {"raw_name": "负债合计", "value_raw": "5846.57", "unit": "亿元", "page": 18},
    ],
}


def _sse(obj: dict) -> str:
    # default=str 处理 pymysql 返回的 Decimal（W09 已知坑：Decimal 不可直接 json.dumps）
    return "data: " + json.dumps(obj, ensure_ascii=False, default=str) + "\n\n"


@app.get("/agent/query")
def agent_query(company_code: str, year: int, report_type: str = "annual"):
    """流式问值/导入一条年报：auto_approve=True，逐节点 SSE 返回中间过程。

    这是验收「Laravel 页面能看到流式中间过程」的 Python 侧真相：
    每跑完一个 LangGraph 节点（classify→extract→落库→verify）就 yield 一帧。
    """
    rows = SAMPLES.get(company_code, SAMPLES["600519"])
    name = NAME_MAP.get(company_code, "贵州茅台")
    tid = f"q-{company_code}-{year}"
    cfg = {"configurable": {"thread_id": tid}}
    inp = graph.build_input(company_code, name, "SH", year, rows, report_type, auto_approve=True)

    def stream():
        # MVP: langgraph app.stream 是同步的，直接包同步生成器。
        # 生产应在 run_in_threadpool 里跑，避免阻塞事件循环。
        for chunk in graph.app.stream(inp, cfg, stream_mode="updates"):
            if "__interrupt__" in chunk:
                yield _sse({"step": "need_approval", "thread_id": tid})
                return
            for node, vals in chunk.items():
                yield _sse({"step": node, "data": vals})
        yield _sse({"step": "done"})

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/agent/import")
def agent_import(company_code: str, year: int, report_type: str = "annual",
                 confirm: bool = False, thread_id: str = None):
    """批量导入长任务（演示 interrupt 在 HTTP 上的对应物）：

    首次（无 thread_id）：auto_approve=False -> 跑到 human_review 挂起 ->
        返回 {step:'need_approval', thread_id} 让前端弹批准框。
    续跑（带 thread_id + confirm=true）：Command(resume) 从挂起点继续 -> 落库 -> verify。
    """
    if thread_id:
        cfg = {"configurable": {"thread_id": thread_id}}
        inp = Command(resume={"approve": confirm})
        tid = thread_id
    else:
        rows = SAMPLES.get(company_code, SAMPLES["600519"])
        name = NAME_MAP.get(company_code, "贵州茅台")
        tid = f"imp-{company_code}-{year}"
        cfg = {"configurable": {"thread_id": tid}}
        inp = graph.build_input(company_code, name, "SH", year, rows, report_type, auto_approve=False)

    def stream():
        for chunk in graph.app.stream(inp, cfg, stream_mode="updates"):
            if "__interrupt__" in chunk:
                iv = chunk["__interrupt__"][0].value
                yield _sse({"step": "need_approval", "thread_id": tid,
                            "ask": iv.get("ask"), "preview": iv.get("preview")})
                return
            for node, vals in chunk.items():
                yield _sse({"step": node, "data": vals})
        yield _sse({"step": "done"})

    return StreamingResponse(stream(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
