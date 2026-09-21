#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
W06 阶段2 · Dense 向量检索（复用 W05 写法，Key 门控）
------------------------------------------------------------------------------
embedding 用百炼 qwen3.7-text-embedding-flash(1024维)；
向量库用 pgvector，复用本机 gp17 容器里的 w06rag 库（与 w05rag 是同一实例的不同 database）。
需要本机已注入 API_KEY / BASE_URL 环境变量（见 .env.example / start-env-windows.bat）。
PG 连接参数从环境变量读（PG_HOST/PG_PORT/PG_DB/PG_USER/PG_PASSWORD，见 .env.example），带默认值，
后续课程只改 .env 的 PG_DB=w07rag 即可复用同一套代码，不必改硬编码。
沙箱无 Key 时 available() 返回 False，评测自动跳过 Hybrid / Rerank 两路。
"""
import os

EMB_MODEL = "qwen3.7-text-embedding-flash"
DIM = 1024
PG = dict(
    host=os.environ.get("PG_HOST", "127.0.0.1"),
    port=int(os.environ.get("PG_PORT", 5432)),
    dbname=os.environ.get("PG_DB", "w06rag"),
    user=os.environ.get("PG_USER", "amber"),
    password=os.environ.get("PG_PASSWORD", "amber123"),
)

_client = None


def available():
    return bool(os.environ.get("API_KEY") and os.environ.get("BASE_URL"))


def _client_get():
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(base_url=os.environ["BASE_URL"], api_key=os.environ["API_KEY"])
    return _client


def embed(text):
    r = _client_get().embeddings.create(model=EMB_MODEL, input=[text], dimensions=DIM)
    return r.data[0].embedding


def search(query, top_k=40):
    import psycopg2
    qvec = embed(query)
    conn = psycopg2.connect(**PG)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, 1-(embedding <=> %s) AS sim FROM chunks ORDER BY embedding <=> %s LIMIT %s",
        (str(qvec), str(qvec), top_k),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [(rid, float(sim)) for rid, sim in rows]


def build_index(chunks):
    """把 chunks 写入 pgvector（阶段2 你本机跑：先 00_start_pgvector.sh 起库建表）。"""
    import psycopg2
    conn = psycopg2.connect(**PG)
    cur = conn.cursor()
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    cur.execute(
        "CREATE TABLE IF NOT EXISTS chunks ("
        " id text PRIMARY KEY, doc_id text, content text, embedding vector(1024));"
    )
    cur.execute("CREATE INDEX IF NOT EXISTS chunks_hnsw ON chunks USING hnsw (embedding vector_cosine_ops);")
    for c in chunks:
        vec = embed(c["content"])
        cur.execute(
            "INSERT INTO chunks(id, doc_id, content, embedding) VALUES (%s,%s,%s,%s) "
            "ON CONFLICT (id) DO UPDATE SET content=EXCLUDED.content, embedding=EXCLUDED.embedding;",
            (c["id"], c["doc_id"], c["content"], str(vec)),
        )
    conn.commit()
    cur.close()
    conn.close()
    print(f"已写入 {len(chunks)} 个 chunk 到 w06rag.chunks")
