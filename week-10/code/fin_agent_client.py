"""W10 · fin-agent 调用端 —— 用 httpx 手写 MCP Streamable HTTP 协议调用。

为什么不用 FastMCP Client 的 streamable-http transport：
  FastMCP v4.0.3 的 streamable HTTP client 在发第二个请求时会把完整 URL
  错误地再拼一次（日志里出现 `POST http%3A//127.0.0.1%3A8000/mcp` 404），
  这是该版本的 client/server 配合 bug。手写 httpx 直接发 JSON-RPC 既能 100%
  走通，也更贴近协议本质（看清 MCP 到底在传什么）。

Server 端用 stateless 模式（MCP_MODE=http 启动），每请求独立、无需 session。
对应你 W09 那个「Laravel 后台调用端」的等价物——不再手写 HTTP/SSE，而是
按标准 MCP 协议发 JSON-RPC。你未来的 Laravel 端也可以用 Guzzle 同样发这几段。
"""
import json
import httpx
import os

# HTTP 版 Server 地址（stateless 模式，端点挂在 /mcp）。
# 默认 8000；可用 MCP_BASE 环境变量覆盖（如本机手动联调或并发测试）。
_BASE = os.environ.get("MCP_BASE", "http://127.0.0.1:8000")
MCP_URL = f"{_BASE.rstrip('/')}/mcp"

JSONRPC_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


def _parse_response(text: str):
    """MCP 响应可能是纯 JSON，也可能是 SSE（`data: {...}` 多行）。统一解析成 dict。"""
    text = (text or "").strip()
    if text.startswith("{"):
        return json.loads(text)
    # SSE：取最后一个 data: 行（首行通常是 event: message）
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("data:"):
            payload = line[len("data:"):].strip()
            try:
                return json.loads(payload)
            except Exception:
                continue
    return {}


def _post(payload: dict, session_id: str | None = None) -> tuple[int, dict, str | None]:
    """发一条 JSON-RPC 到 MCP 端点，返回 (status, parsed_body, session_id)。"""
    headers = dict(JSONRPC_HEADERS)
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    with httpx.Client(timeout=15) as client:
        r = client.post(MCP_URL, json=payload, headers=headers)
        new_sid = r.headers.get("mcp-session-id") or r.headers.get("Mcp-Session-Id")
        return r.status_code, _parse_response(r.text), new_sid


def initialize() -> str | None:
    """协议握手。stateless 模式下 server 不强制，但发了能拿到能力信息。"""
    status, body, sid = _post({
        "jsonrpc": "2.0", "id": 0, "method": "initialize",
        "params": {
            "protocolVersion": "2026-07-28",
            "capabilities": {},
            "clientInfo": {"name": "fin-agent-client", "version": "1.0.0"},
        },
    })
    # MCP 协议：initialize 之后必须发 notifications/initialized（无 id 的通知），
    # server 端才会开放 tools/list / tools/call 等后续请求。
    _post({
        "jsonrpc": "2.0", "method": "notifications/initialized", "params": {}
    })
    return sid


def list_tools() -> list[str]:
    status, body, _ = _post({
        "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}
    })
    if "error" in body:
        raise RuntimeError(f"tools/list 返回错误: {body['error']}")
    tools = (body.get("result") or {}).get("tools", [])
    return [t["name"] for t in tools]


def call_query_indicator(company_code: str, year: int, matched_code: str) -> dict:
    status, body, _ = _post({
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {
            "name": "query_indicator",
            "arguments": {
                "company_code": company_code,
                "year": year,
                "matched_code": matched_code,
            },
        },
    })
    result = body.get("result") or {}
    # tools/call 的结果：content[0].text 通常是 JSON 字符串（server 返回 dict 被序列化）
    content = result.get("content")
    if isinstance(content, list) and content:
        text = content[0].get("text")
        if isinstance(text, str):
            try:
                return json.loads(text)
            except Exception:
                return {"raw": text}
    return result.get("structuredContent") or {}


def main():
    print("=== initialize ===")
    sid = initialize()
    print("session_id:", sid)

    print("=== tools/list ===")
    tools = list_tools()
    print(tools)

    print("=== tools/call query_indicator(600519, 2025, NP_PARENT) ===")
    row = call_query_indicator("600519", 2025, "NP_PARENT")
    print(json.dumps(row, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
