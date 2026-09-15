#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
W05 阶段2 · 02 查询（余弦检索 + 调 top_k 与相似度阈值）
------------------------------------------------------------------------------
对应阶段1 概念：
  - 第2节 余弦相似度：pgvector 的 <=> 是余弦距离，1-(a<=>b)=余弦相似度
  - 第4节 HNSW：ORDER BY embedding <=> %s 走 HNSW 索引，LIMIT 取最像的 top_k

用法（在已注入 API_KEY/BASE_URL 的窗口里）：
  python 02_query.py "退款多久到账"            # top_k=5, 阈值=0（全返回）
  python 02_query.py "退款多久到账" 3 0.2     # top_k=3, 相似度>=0.2
  python 02_query.py "退款多久到账" 20 0 --show-all   # 打印全部 chunk 相似度（诊断切分召回错用）

验收要求：亲手调 top_k 与阈值，观察召回变化；并能解释某条查询为何召回错。
"""
import os
import sys
import argparse
from openai import OpenAI
import psycopg2

API_KEY  = os.environ.get("API_KEY")
BASE_URL = os.environ.get("BASE_URL")
EMB_MODEL = "qwen3.7-text-embedding-flash"
DIM = 1024
PG = dict(host="127.0.0.1", port=5432, dbname="w05rag", user="amber", password="amber123")

if not API_KEY or not BASE_URL:
    print("ERROR: 请先注入环境变量 API_KEY / BASE_URL", file=sys.stderr)
    sys.exit(1)

client = OpenAI(base_url=BASE_URL, api_key=API_KEY)


def embed(text):
    r = client.embeddings.create(model=EMB_MODEL, input=[text], dimensions=DIM)
    return r.data[0].embedding


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", help="用户问题")
    ap.add_argument("top_k", nargs="?", type=int, default=5, help="返回最相似的几条")
    ap.add_argument("threshold", nargs="?", type=float, default=0.0, help="相似度下限（0~1）")
    ap.add_argument("--show-all", action="store_true", help="打印全部 chunk 相似度（诊断用）")
    args = ap.parse_args()

    qvec = embed(args.query)
    conn = psycopg2.connect(**PG)
    cur = conn.cursor()

    if args.show_all:
        cur.execute(
            "SELECT id, content, 1-(embedding <=> %s) AS sim FROM chunks ORDER BY sim DESC;",
            (str(qvec),))
        rows = cur.fetchall()
        print(f"查询：{args.query} ｜ 全部 {len(rows)} 个 chunk 相似度（降序）：")
        for rid, content, sim in rows:
            print(f"  #{rid}  sim={sim:.4f}  {content[:48]}")
    else:
        cur.execute("""
            SELECT id, content, 1-(embedding <=> %s) AS sim
            FROM chunks
            WHERE 1-(embedding <=> %s) >= %s
            ORDER BY embedding <=> %s
            LIMIT %s;
        """, (str(qvec), str(qvec), args.threshold, str(qvec), args.top_k))
        rows = cur.fetchall()
        print(f"查询：{args.query} ｜ top_k={args.top_k} 阈值={args.threshold} ｜ 命中 {len(rows)} 条：")
        for rid, content, sim in rows:
            print(f"  #{rid}  sim={sim:.4f}\n    {content}\n")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
