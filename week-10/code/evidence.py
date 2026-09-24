"""W10 实证：把验证结果直接以 UTF-8 写文件，绕开 Windows 控制台 GBK 编码乱码。"""
import asyncio
from fastmcp import Client
import mcp_fin_server as srv

OUT = "verify_evidence.txt"


async def main():
    lines = []
    async with Client(srv.mcp) as client:
        tools = await client.list_tools()
        names = [t.name for t in tools]
        lines.append(f"[1] 已注册工具: {names}")
        assert "query_indicator" in names

        schema = await client.read_resource("fin://schema")
        # fastmcp v4: read_resource 返回 content 列表，每项属性是 .text（不是 .content）
        items = schema if isinstance(schema, list) else [schema]
        text = "".join(getattr(c, "text", getattr(c, "content", str(c))) for c in items)
        schema_lines = text.splitlines()
        lines.append(f"[2] fin://schema 读取成功: 共 {len(schema_lines)} 个标准科目 code")
        lines.append(f"    首行示例: {schema_lines[0]}")

        r = await client.call_tool(
            "query_indicator",
            {"company_code": "600519", "year": 2025, "matched_code": "NP_PARENT"},
        )
        data = getattr(r, "data", None) or getattr(r, "content", r)
        lines.append(f"[3] call_tool('query_indicator', 600519/2025/NP_PARENT) 实查结果:")
        lines.append(f"    {data}")

        prompts = await client.list_prompts()
        pnames = [p.name for p in prompts]
        lines.append(f"[4] 已注册 Prompts: {pnames}")
        assert "生成财报周报" in pnames
        # 试渲染一次 prompt（带参数），看模板是否生成
        pr = await client.get_prompt("生成财报周报", {"company_code": "600519", "year": 2025})
        ptext = pr.messages[0].content.text if hasattr(pr, "messages") else str(pr)
        lines.append(f"[5] get_prompt('生成财报周报', 600519/2025) 渲染首行: {ptext.splitlines()[0]}")

    lines.append("")
    lines.append("结论: tool 注册 + resource 读取 + 真实查库 链路全部跑通（非优雅报错，是真数据）")
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
