#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
W07 阶段2 · 溯源问答（small-to-big：命中子块 -> 返回父块 -> LLM -> 每句标注引用）
======================================================================
验证 W07 验收标准②：答案每句可溯源。检索命中子块后映射父块全文喂 LLM，
答案句末用 [1][2] 标注引用了哪个父块编号，并落库 w07rag.answers(cited_chunk_ids=父块id)。

运行（PS，需本机 Key + 已灌库）：
  $env:PG_DB="w07rag"; $env:Q="华夏银行2026上半年营业收入是多少"; python qa.py
"""
import os
import sys
import json

os.environ.setdefault("PG_DB", "w07rag")
import psycopg2
from bm25 import BM25
import dense
from rrf import rrf_fuse
import rerank


def load_all():
    PG = dict(
        host=os.environ.get("PG_HOST", "127.0.0.1"),
        port=int(os.environ.get("PG_PORT", 5432)),
        dbname=os.environ.get("PG_DB", "w07rag"),
        user=os.environ.get("PG_USER", "amber"),
        password=os.environ.get("PG_PASSWORD", "amber123"),
    )
    conn = psycopg2.connect(**PG)
    cur = conn.cursor()
    cur.execute("SELECT id, doc_id, content, parent_id FROM chunks")
    chunks = [{"id": r[0], "doc_id": r[1], "content": r[2], "parent_id": r[3]} for r in cur.fetchall()]
    cur.execute("SELECT id, content FROM parent_chunks")
    parents = {r[0]: r[1] for r in cur.fetchall()}
    cur.close()
    conn.close()
    return chunks, parents


def retrieve(query, bm25, chunks, k=6):
    bm25_res = bm25.search(query, top_k=40)
    dense_res = dense.search(query, top_k=40)
    fused = rrf_fuse([bm25_res, dense_res], k=60, top=40)
    content = {c["id"]: c["content"] for c in chunks}
    cand = [(cid, content[cid]) for cid, _ in fused[:20] if cid in content]
    if rerank.available():
        return rerank.rerank(query, cand, top_k=k)
    return fused[:k]


def save_answer(query, answer, cited):
    PG = dict(
        host=os.environ.get("PG_HOST", "127.0.0.1"),
        port=int(os.environ.get("PG_PORT", 5432)),
        dbname=os.environ.get("PG_DB", "w07rag"),
        user=os.environ.get("PG_USER", "amber"),
        password=os.environ.get("PG_PASSWORD", "amber123"),
    )
    conn = psycopg2.connect(**PG)
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS answers(
        id SERIAL PRIMARY KEY, query TEXT, answer TEXT,
        cited_chunk_ids TEXT, scheme TEXT, created_at TIMESTAMPTZ DEFAULT now());""")
    cur.execute("INSERT INTO answers(query, answer, cited_chunk_ids, scheme) VALUES(%s,%s,%s,%s)",
                (query, answer, json.dumps(cited, ensure_ascii=False), "w07-small-to-big"))
    conn.commit()
    cur.close()
    conn.close()


def main():
    if not (os.environ.get("API_KEY") and os.environ.get("BASE_URL")):
        print("[错误] 需 API_KEY/BASE_URL。"); sys.exit(1)
    q = os.getenv("Q") or "华夏银行2026上半年营业收入是多少"
    chunks, parents = load_all()
    bm25 = BM25()
    bm25.fit(chunks)
    res = retrieve(q, bm25, chunks, k=6)
    ctx = []
    cited = []
    for cid, _ in res:
        c = next((x for x in chunks if x["id"] == cid), None)
        pid = c["parent_id"] if c else cid
        pcontent = parents.get(pid) or parents.get(cid, "")
        ctx.append((pid, pcontent))
        cited.append(pid)
    sys_p = ("你是华夏银行财报分析助手。只依据下面带编号的参考片段回答，不得编造；"
             "若片段不足以回答，明说『参考片段未覆盖』。回答中在相关句末用 [1][2] 标注引用了哪些片段编号。")
    body = ""
    for i, (pid, pc) in enumerate(ctx, 1):
        body += f"\n[{i}] ({pid})\n{pc[:1500]}"
    from openai import OpenAI
    client = OpenAI(base_url=os.environ["BASE_URL"], api_key=os.environ["API_KEY"])
    chat_model = os.getenv("GENERATE_MODEL", "deepseek-v4-flash")
    ans = client.chat.completions.create(model=chat_model, messages=[
        {"role": "system", "content": sys_p + body},
        {"role": "user", "content": q},
    ], temperature=0.3).choices[0].message.content
    print(f"=== 问题：{q} ===\n")
    print(ans)
    print(f"\n[引用父块] {cited}")
    try:
        save_answer(q, ans, cited)
        print(f"[落库] w07rag.answers 已写入（{len(cited)} 条父块引用）")
    except Exception as e:
        print(f"[落库失败] {e}")


if __name__ == "__main__":
    main()
