#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
W06 阶段2 · 引用落库（生成带引用的答案，并把引用写回 w06rag.answers）
------------------------------------------------------------------------------
复用 eval.retrieve 取融合后 top-k 块；纯检索/拼 prompt 部分沙箱可验证（无需 Key），
LLM 生成 + 落库部分需本机注入 API_KEY / PG_* 后运行。

运行（PS）：
  # 沙箱/无 Key：只看 BM25-only 的 top 块（不调 LLM）
  python generate.py

  # 本机（bat 已加载 API_KEY，且已灌库）：Hybrid 方案生成 + 落库
  $env:SCHEME="hybrid"; $env:Q="扣非净利润和归母净利润有什么区别"; python generate.py

  # 指定生成模型（默认 deepseek-v4-flash，走 BASE_URL 兼容层）
  $env:GENERATE_MODEL="deepseek-v4-flash"; python generate.py
"""
import os
import json

import psycopg2

from corpus import load_chunks
from bm25 import BM25
import dense
from eval import retrieve


def top_chunks(strategy, bm25, chunks, query, k=5):
    """取融合结果 top-k 块，返回 [(chunk_id, content), ...] 供拼 prompt 与引用。"""
    res = retrieve(strategy, bm25, chunks, query)[:k]
    content = {c["id"]: c["content"] for c in chunks}
    return [(cid, content.get(cid, "")) for cid, _ in res]


def build_prompt(query, chunks_kv):
    """拼带编号引用的 prompt：系统约束 + 参考片段 + 引用格式要求。"""
    sys_p = "你是可转债/财报分析助手。只依据下面带编号的参考片段回答，不得编造；" \
            "若片段不足以回答，明说'参考片段未覆盖'。"
    body = ""
    for i, (cid, c) in enumerate(chunks_kv, 1):
        body += f"\n[{i}] ({cid})\n{c}"
    usr = f"{query}\n\n回答末尾用 [1][2] 标注引用了哪些片段编号。"
    return sys_p, body, usr


def save_answer(query, answer, cited):
    """把 query + 答案 + 引用块 id 写回 w06rag.answers（引用落库）。"""
    pg = dict(
        host=os.getenv("PG_HOST", "127.0.0.1"),
        port=int(os.getenv("PG_PORT", 5432)),
        dbname=os.getenv("PG_DB", "w06rag"),
        user=os.getenv("PG_USER", "amber"),
        password=os.getenv("PG_PASSWORD", "amber123"),
    )
    conn = psycopg2.connect(**pg)
    cur = conn.cursor()
    cur.execute(
        """CREATE TABLE IF NOT EXISTS answers(
            id SERIAL PRIMARY KEY,
            query TEXT,
            answer TEXT,
            cited_chunk_ids TEXT,
            scheme TEXT,
            created_at TIMESTAMPTZ DEFAULT now()
        )"""
    )
    cur.execute(
        "INSERT INTO answers(query, answer, cited_chunk_ids, scheme) VALUES(%s,%s,%s,%s)",
        (query, answer, json.dumps(cited, ensure_ascii=False), os.getenv("SCHEME", "bm25")),
    )
    conn.commit()
    cur.close()
    conn.close()


def main():
    chunks = load_chunks("corpus")
    bm25 = BM25()
    bm25.fit(chunks)

    # 无 Key 时退化为 bm25；有 Key 时默认 hybrid（RRF 融合后取 top 块作引用）
    strat = os.getenv("SCHEME", "hybrid") if dense.available() else "bm25"
    q = os.getenv("Q") or "扣非净利润和归母净利润有什么区别"
    kvs = top_chunks(strat, bm25, chunks, q, k=5)
    sys_p, body, usr = build_prompt(q, kvs)

    print(f"=== 方案: {strat} | 检索到 top {len(kvs)} 块（将作为引用喂给 LLM）===")
    for i, (cid, c) in enumerate(kvs, 1):
        print(f"  [{i}] {cid}: {c[:60].replace(chr(10), ' ')}...")

    if not dense.available():
        print("\n[跳过] 无 API_KEY，未调用 LLM。上面是 BM25-only 的 top 块预览。")
        return

    # ---- LLM 生成（本机注入 Key 后执行）----
    from openai import OpenAI

    client = OpenAI(api_key=os.getenv("API_KEY"), base_url=os.getenv("BASE_URL"))
    chat_model = os.getenv("GENERATE_MODEL", "deepseek-v4-flash")
    resp = client.chat.completions.create(
        model=chat_model,
        messages=[
            {"role": "system", "content": sys_p + body},
            {"role": "user", "content": usr},
        ],
        temperature=0.3,
    )
    answer = resp.choices[0].message.content
    cited = [cid for cid, _ in kvs]

    print(f"\n=== 生成答案（模型 {chat_model}）===\n{answer}")
    try:
        save_answer(q, answer, cited)
        print(f"\n[落库] w06rag.answers 已写入（{len(cited)} 条引用：{cited}）")
    except Exception as e:  # 落库失败不影响输出答案
        print(f"\n[落库失败] {e}")


if __name__ == "__main__":
    main()
