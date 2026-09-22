"""W08 v2: PostgresSaver 跨进程崩溃续跑 + 时间旅行（接本机 pgvector 容器，库 w08lg）

实证小节3：MemorySaver 进程一退就没；PostgresSaver 把 checkpoint 落 Postgres，
进程崩溃 / 跨进程 / 跨天都能按 thread_id 续跑。

前置（本机 PowerShell 执行）：
  1) pgvector 容器在跑（用 CONTAINER ID 引用，不写死 name）；库 w08lg 已建：
     $PG_CONTAINER_ID = (docker ps -q --filter "ancestor=pgvector/pgvector:0.8.6-pg17")   # 取 ID（按镜像绕开 name 解析坑）
     docker exec -i $PG_CONTAINER_ID psql -U amber -d template1 -c "CREATE DATABASE w08lg OWNER amber;"
  2) 依赖（venv 的 pip）：
     pip install langgraph-checkpoint-postgres
  3) 连接信息走环境变量（不写死）：
     $env:PG_HOST="127.0.0.1"; $env:PG_PORT="5432"; $env:PG_DB="w08lg"
     $env:PG_USER="amber"; $env:PG_PASSWORD="amber123"

运行： python refund_graph_pg.py
"""

import os
import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command
from langchain_core.messages import HumanMessage
from refund_graph import g  # 复用 v1 的图定义（StateGraph，未编译）

# 连接信息只从环境变量读
PG_DB = os.getenv("PG_DB", "w08lg")
PG_USER = os.getenv("PG_USER", "amber")
PG_PASSWORD = os.getenv("PG_PASSWORD", "amber123")
PG_HOST = os.getenv("PG_HOST", "127.0.0.1")
PG_PORT = os.getenv("PG_PORT", "5432")


def connect():
    # autocommit=True：PostgresSaver.setup() 内含 CREATE INDEX CONCURRENTLY，
    # 不能在事务块中运行，必须 autocommit（psycopg3 默认关闭）
    return psycopg.connect(
        f"dbname={PG_DB} user={PG_USER} password={PG_PASSWORD} host={PG_HOST} port={PG_PORT}",
        autocommit=True,
    )


if __name__ == "__main__":
    cfg = {"configurable": {"thread_id": "refund-pg-1"}}

    # ===== 进程 A：跑到 interrupt 挂起，然后"崩溃退出" =====
    conn_a = connect()
    saver_a = PostgresSaver(conn_a)
    saver_a.setup()                       # 首次自动建表
    app_a = g.compile(checkpointer=saver_a)
    app_a.invoke(
        {
            "messages": [HumanMessage("给我退 ORD-1001")],
            "order_id": "ORD-1001",
            "order": {},
            "refunded": False,
        },
        cfg,
    )
    print("进程A 挂起 next:", app_a.get_state(cfg).next)   # ('approve_refund',)
    print("→ 进程 A 崩溃退出（checkpoint 已落 Postgres）")
    conn_a.close()

    # ===== 进程 B：全新连接 + 全新 app 实例，复用同一 thread_id =====
    # 关键：app_b 是重新编译的、saver_b 是重新连的，没有任何内存状态。
    # 能续跑，证明持久化在 Postgres，不在进程内存（MemorySaver 此时会丢失）。
    conn_b = connect()
    saver_b = PostgresSaver(conn_b)
    app_b = g.compile(checkpointer=saver_b)
    print("进程B 从 Postgres 读 checkpoint 续跑...")
    app_b.invoke(Command(resume={"approve": True}), cfg)
    final = app_b.get_state(cfg).values
    print("最终 order:", final["order"], "refunded:", final["refunded"])

    # ===== 时间旅行：回看每一步快照（小节3 的 get_state_history）=====
    # get_state_history 默认「新→旧」（最新在前），这里反转成正序更直观：
    # 步0=__start__（order 尚未查，status=None）→ 步N=终态（refunded）
    print("\n=== 时间旅行：state history（正序：__start__ → 终态）===")
    for i, s in enumerate(reversed(list(app_b.get_state_history(cfg)))):
        print(f"  步{i}: next={s.next} order.status={s.values.get('order', {}).get('status')}")
    conn_b.close()
