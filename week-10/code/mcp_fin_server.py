"""W10 · 第一个 FastMCP Server —— 把 W09 财报查询能力暴露成 MCP。

按 2026-07-28 规范，FastMCP v4.0.3。
三原语：
  - @mcp.tool     query_indicator  —— 模型主动调用的「动作」
  - @mcp.resource fin://schema     —— 只读数据，客户端注入上下文
  - @mcp.prompt   生成财报周报      —— 用户一键触发的提示词模板

复用 W09：db.py(MySQL 连接) / query.py(query_indicator) / indicators_seed.json(科目清单)。
"""
import json
import traceback

from fastmcp import FastMCP
import db          # W09 的 MySQL 连接（读 env: FIN_DB_*，默认 127.0.0.1:3306 root 空密码 fin_agent）
import query       # W09 的 query_indicator(company_code, year, matched_code)

mcp = FastMCP("fin-agent")   # Server 名，客户端 list 时看到的就是它


@mcp.tool()
def query_indicator(company_code: str, year: int, matched_code: str) -> dict:
    """按 公司代码 + 年度 + 标准科目 code 查已归一化落库的值。

    参数：
      company_code: 股票代码，如 '600519'
      year:         报告年度，如 2025
      matched_code: 标准科目 code，如 'NP_PARENT'(归母净利润) / 'OPER_REV'(营业总收入) / 'NET_PROFIT'(净利润)
    返回：单行字典（company, code, year, matched_code, value, unit, method, confidence）
          查不到或出错时返回 {'error': '...'}，不会让 Server 崩溃。
    """
    try:
        row = query.query_indicator(company_code, year, matched_code)
        return row if row else {"error": "no match"}
    except Exception as e:   # 连不上库 / SQL 错 等情况：优雅返回，而非抛异常崩 Server
        return {"error": f"{type(e).__name__}: {e}"}


@mcp.resource("fin://schema")
def fin_schema() -> str:
    """只读：当前 fin_agent 库可用的标准科目 code 清单，供模型选型参考（不会被执行，只被读取）。"""
    with open("indicators_seed.json", encoding="utf-8") as f:
        items = json.load(f)
    lines = [f"{i['code']} = {i['name']}" for i in items]
    return "\n".join(lines)


@mcp.prompt()
def 生成财报周报(company_code: str, year: int) -> str:
    """一键生成「财报周报」提示词模板：引导模型先读 fin://schema 选科目，再调 query_indicator 拉关键指标，最后组织成周报。

    参数：
      company_code: 股票代码，如 '600519'
      year:         报告年度，如 2025
    触发方式：用户在客户端点选此 Prompt（不是模型自动调用），把下面这段提示词注入对话。
    """
    return (
        f"请为股票 {company_code} 的 {year} 年度报告撰写一份财报周报。\n\n"
        "执行步骤：\n"
        "1. 先读取 fin://schema 资源，了解可用的标准科目 code。\n"
        "2. 调用 query_indicator 工具，依次拉取以下关键指标（matched_code 见 schema）：\n"
        "   - 营业总收入   OPER_REV\n"
        "   - 归母净利润   NP_PARENT\n"
        "   - 净利润       NET_PROFIT\n"
        "   - 扣非净利润   NP_PARENT_DEDUCT（如已落库）\n"
        "3. 汇总各指标的金额、单位、method（L1 = 字段字典精准命中）、confidence。\n"
        "4. 按「经营概况 / 盈利质量 / 风险提示」三段输出周报，金额统一用「亿元」并标注原始 unit。\n"
    )


if __name__ == "__main__":
    import os
    import uvicorn

    # 默认 stdio：Host 把本脚本当子进程拉起（本地调试 / Claude Desktop / Inspector）
    # 切换到 HTTP 远程模式：MCP_MODE=http python mcp_fin_server.py
    #   —— 用 stateless 模式（2026-07-28 规范核心），每请求独立、无需 session，
    #      正好规避 FastMCP v4 有状态模式下 "INIT 的 SSE 流关闭后 session 被回收→后续 tools/list 404" 的坑。
    #   —— 独立部署时，任何能发 HTTP 的客户端（你的 Laravel 后台）都能 POST 调用。
    if os.environ.get("MCP_MODE", "stdio").lower() == "http":
        port = int(os.environ.get("MCP_PORT", "8000"))
        app = mcp.http_app(stateless_http=True)
        uvicorn.run(app, host="127.0.0.1", port=port)
    else:
        mcp.run()
