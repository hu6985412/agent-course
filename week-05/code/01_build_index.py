#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
W05 阶段2 · 01 建索引（递归切分 + 百炼 embedding + pgvector 入库 + HNSW 索引）
------------------------------------------------------------------------------
对应阶段1 概念：
  - 第3节 切分：recursive_split 实现递归切分 + sliding-window overlap
  - 第1节 Embedding：调百炼 qwen3.7-text-embedding-flash 把每块变成 1024 维向量
  - 第4节 向量库：写入 pgvector 的 vector(1024) 列，建 HNSW 余弦索引

配置约定（沿用 CLI 红线）：Key/URL 只从环境变量读，不写死、不进 history。
本机执行前：双击 start-env-windows.bat 注入 API_KEY/BASE_URL，或 PS 里覆盖：
    $env:API_KEY = "sk-xxx"; $env:BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
依赖：pip install -r requirements.txt
"""
import os
import re
import sys
from openai import OpenAI
import psycopg2
from psycopg2.extras import execute_values

# ---------- 配置（只从环境变量读） ----------
API_KEY  = os.environ.get("API_KEY")
BASE_URL = os.environ.get("BASE_URL")   # 必须含 /v1
EMB_MODEL = "qwen3.7-text-embedding-flash"
DIM = 1024

PG = dict(host="127.0.0.1", port=5432, dbname="w05rag", user="amber", password="amber123")

CHUNK_SIZE = 400      # 块大小（字符）。太大→平均后不准；太小→丢上下文
OVERLAP    = 80       # 重叠 80 ≈ 块大小的 20%（sliding window）
BATCH      = 20       # 百炼 flash 单批上限 20 条

DOC_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_doc.md")


def die(msg):
    print("ERROR: " + msg, file=sys.stderr)
    sys.exit(1)


if not API_KEY or not BASE_URL:
    die("请先注入环境变量 API_KEY / BASE_URL（双击 start-env-windows.bat 或 PS 覆盖）")

client = OpenAI(base_url=BASE_URL, api_key=API_KEY)


# ---------- 递归切分（简化版 RecursiveCharacterTextSplitter） ----------
def _split_with_sep(text, sep):
    """按 sep 切，并把 sep 保留回每个 piece 末尾（最后一块除外）。"""
    if not sep:
        return list(text)
    pieces = re.split(f"({re.escape(sep)})", text)
    out = []
    for i in range(0, len(pieces) - 1, 2):
        out.append(pieces[i] + pieces[i + 1])
    if len(pieces) % 2 == 1 and pieces[-1]:
        out.append(pieces[-1])
    return [p for p in out if p]


def recursive_split(text, size, overlap, seps):
    """按分隔符优先级递归切：先 \n\n → \n → 。 → ！ → ？ → ； → ， → 空格。
    overlap：相邻块共享前块尾部 overlap 个字符（sliding window），避免边界句被劈开丢失语义。"""
    if not text.strip():
        return []
    if len(text) <= size:
        return [text]
    sep = seps[0]
    pieces = _split_with_sep(text, sep)
    chunks, cur = [], ""
    for p in pieces:
        if len(cur) + len(p) <= size:
            cur += p
        else:
            if cur:
                chunks.append(cur)
            if len(p) > size and len(seps) > 1:
                chunks.extend(recursive_split(p, size, overlap, seps[1:]))
            else:
                cur = p
    if cur:
        chunks.append(cur)
    # sliding window overlap
    if overlap > 0 and len(chunks) > 1:
        merged = [chunks[0]]
        for i in range(1, len(chunks)):
            prev = chunks[i - 1]
            ov = prev[-overlap:] if len(prev) >= overlap else prev
            merged.append(ov + chunks[i])
        chunks = merged
    return chunks


SEPS = ["\n\n", "\n", "。", "！", "？", "；", "，", " "]


def embed_batch(texts):
    resp = client.embeddings.create(model=EMB_MODEL, input=texts, dimensions=DIM)
    return [d.embedding for d in resp.data]


def main():
    text = open(DOC_PATH, encoding="utf-8").read()
    chunks = recursive_split(text, CHUNK_SIZE, OVERLAP, SEPS)
    print(f"切分完成：{len(chunks)} 个 chunk（chunk_size={CHUNK_SIZE}, overlap={OVERLAP}）")
    for i, c in enumerate(chunks[:3]):
        print(f"  chunk[{i}] ({len(c)}字): {c[:50]}...")

    conn = psycopg2.connect(**PG)
    cur = conn.cursor()
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    cur.execute("DROP TABLE IF EXISTS chunks;")
    cur.execute("""
        CREATE TABLE chunks (
            id      serial PRIMARY KEY,
            doc_id  text,
            content text,
            embedding vector(1024)
        );
    """)

    rows = []
    for i in range(0, len(chunks), BATCH):
        batch = chunks[i:i + BATCH]
        vecs = embed_batch(batch)
        for j, c in enumerate(batch):
            rows.append(("doc1", c, str(vecs[j])))   # str(vec) -> '[0.1, 0.2, ...]'，pgvector 自动解析
        print(f"  已 embedding 第 {i + 1}~{i + len(batch)} 条")

    execute_values(cur,
                   "INSERT INTO chunks (doc_id, content, embedding) VALUES %s",
                   rows)
    cur.execute("CREATE INDEX ON chunks USING hnsw (embedding vector_cosine_ops);")
    conn.commit()
    cur.execute("SELECT count(*) FROM chunks;")
    print("入库完成，chunks 总数：", cur.fetchone()[0])
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
