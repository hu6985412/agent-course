"""W10 · Streamable HTTP (stateless) 实测：独立子进程起 HTTP 服务 + fin-agent(httpx) 调用端走通。

流程：
  1. 子进程起 `MCP_MODE=http python mcp_fin_server.py`（uvicorn @127.0.0.1:PORT, stateless）
  2. socket 轮询直到端口可连
  3. 用 fin_agent_client（httpx 手写 MCP 协议）走 initialize + list_tools + call_tool
  4. 写 verify_http_final_evidence.txt，kill 子进程
"""
import asyncio
import os
import socket
import subprocess
import sys
import time

# 必须在 import fin_agent_client 之前设置 MCP_BASE，
# 否则 client_mod 用默认 8000 而 server 起在下面 PORT，连错端口 tools/list 返回空。
PORT = 8123
BASE = f"http://127.0.0.1:{PORT}"
os.environ["MCP_BASE"] = BASE

import fin_agent_client as client_mod

OUT = "verify_http_final_evidence.txt"


def _wait_port(timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=2):
                return True
        except OSError:
            time.sleep(0.5)
    return False


async def main():
    lines = []
    env = dict(os.environ)
    env["MCP_MODE"] = "http"
    env["MCP_PORT"] = str(PORT)
    env["MCP_BASE"] = BASE
    py = sys.executable
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_srv_run.log")
    proc = subprocess.Popen(
        [py, "mcp_fin_server.py"],
        env=env,
        cwd=os.path.dirname(os.path.abspath(__file__)),
        stdout=open(log_path, "w", encoding="utf-8"),
        stderr=subprocess.STDOUT,
    )
    try:
        lines.append(f"[0] 启动 HTTP 服务子进程 pid={proc.pid} (MCP_MODE=http, stateless, port={PORT})")
        ok = _wait_port()
        lines.append(f"[1] 端口 {PORT} 就绪: {ok}")
        if not ok:
            lines.append("ERROR: 服务未在超时内就绪；服务日志：")
            try:
                with open(log_path, encoding="utf-8") as f:
                    lines.append(f.read()[-1500:])
            except Exception:
                pass
            return "\n".join(lines)

        sid = client_mod.initialize()
        lines.append(f"[2] initialize -> session_id={sid}")

        tools = client_mod.list_tools()
        lines.append(f"[3] list_tools 返回: {tools}")

        row = client_mod.call_query_indicator("600519", 2025, "NP_PARENT")
        lines.append(f"[4] call_tool(query_indicator, 600519/2025/NP_PARENT):")
        lines.append(f"    {row}")

        assert "query_indicator" in tools, "工具未注册"
        assert isinstance(row, dict) and row.get("company") == "贵州茅台", "未查到预期数据"
        lines.append("[5] 结论: HTTP(stateless) 模式下 fin-agent(httpx) 调用端 initialize+list_tools+call_tool 全链路走通 ✅")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        lines.append(f"[6] 已终止服务子进程 pid={proc.pid}")
    return "\n".join(lines)


if __name__ == "__main__":
    out = asyncio.run(main())
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(out + "\n")
    print(out)
