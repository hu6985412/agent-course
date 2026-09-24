"""W10 验证脚本：用 FastMCP 内存 Client 无头跑通链路。

不依赖真客户端、不依赖浏览器 Inspector：
  1) list_tools      —— 确认 query_indicator 已注册
  2) read_resource   —— 确认 fin://schema 能读（不碰 MySQL）
  3) call_tool       —— 调 query_indicator（沙箱连不上本机 MySQL，预期返回 {error:...} 而非崩溃）
"""
import asyncio
from fastmcp import Client
import mcp_fin_server as srv


def _text_of(res):
    """read_resource 返回的是 content 列表，兜底取文本。"""
    if isinstance(res, list):
        return "".join(getattr(c, "content", str(c)) for c in res)
    return getattr(res, "content", str(res))


async def main():
    async with Client(srv.mcp) as client:
        # 1) 工具清单
        tools = await client.list_tools()
        names = [t.name for t in tools]
        print("[1] registered tools:", names)
        assert "query_indicator" in names, "query_indicator 未注册！"

        # 2) Resource 读取（只读 json，不连库）
        schema = _text_of(await client.read_resource("fin://schema"))
        lines = schema.splitlines()
        print(f"[2] fin://schema OK: {len(lines)} 个科目 code，首行 = {lines[0]}")

        # 3) 调工具（沙箱无 MySQL，预期优雅返回 error 字典）
        r = await client.call_tool(
            "query_indicator",
            {"company_code": "600519", "year": 2025, "matched_code": "NP_PARENT"},
        )
        data = getattr(r, "data", None)
        if data is None:  # 旧结构兜底
            data = getattr(r, "content", r)
        print("[3] call_tool result:", data)

    print("\nALL CHECKS PASSED (tool 注册 + resource 读取 + 调用链路无崩溃)")


if __name__ == "__main__":
    asyncio.run(main())
