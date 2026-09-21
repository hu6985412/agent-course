#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
W07 阶段2 · HyDE / 多查询 A/B 评测（接 W06 检索栈，增强版）
======================================================================
目的：验证 amber 在引导学习里的预测——财报取数题上「多查询」增益更大、「HyDE」平平。
      上一轮 baseline(hybrid) 在小语料上饱和 Recall=1.000，增量看不见。
      本轮新增 bm25_only(原句纯关键词) 维度 + 口语/异名词难题集，让差异在「难题子集」显形。

策略：
  baseline   = BM25原句 + Dense原句 + RRF 融合 (hybrid，和上一轮可比)
  bm25_only  = 原句纯 BM25 关键词检索 (暴露纯关键词检索的天花板)
  hyde       = LLM生成假设答案后 embed (改写增强 Dense)
  multiquery = LLM生成N个同义问取并集 (改写增强 Dense)

评测：top10 父块是否含 expected_keywords（软评测，不依赖预知块id）
注意：本评测刻意不启用 rerank，纯粹看「查询修饰」对召回的影响（rerank 价值 W06 已证）。

运行（PS，需本机 Key + 已灌库 w07rag）：
  $env:PG_DB="w07rag"; python hyde_eval.py
"""
import os
import sys
import json
import time

os.environ.setdefault("PG_DB", "w07rag")
from bm25 import BM25
import dense
from rrf import rrf_fuse
import psycopg2


def llm_chat(system, user, model=None):
    from openai import OpenAI
    client = OpenAI(base_url=os.environ["BASE_URL"], api_key=os.environ["API_KEY"])
    m = model or os.getenv("GENERATE_MODEL", "deepseek-v4-flash")
    r = client.chat.completions.create(model=m, messages=[
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ], temperature=0.3)
    return r.choices[0].message.content


def gen_hypo(query):
    sys_p = ("你是金融分析助手。针对用户的问题，写一段『假设的答案片段』"
            "（120字以内，陈述句，像从上市公司年报里摘出来的原文风格），用于检索相似段落。"
            "只输出片段本身，不要解释、不要序号。")
    return llm_chat(sys_p, query)


def gen_multi(query, n=3):
    sys_p = (f"你是金融分析助手。把下面用户的问题改写成 {n} 个不同措辞的同义问法，"
            "覆盖上市公司年报里可能出现的不同用词。每行一个，不要序号、不要解释、不要重复原句。")
    out = llm_chat(sys_p, query)
    qs = []
    for l in out.splitlines():
        l = l.strip().lstrip("0123456789.、- ")
        if l:
            qs.append(l)
    return qs[:n]


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


def dense_search(query, mode):
    """mode: baseline / hyde / multiquery"""
    def _pg_search(vec):
        conn = psycopg2.connect(**dense.PG)
        cur = conn.cursor()
        cur.execute("SELECT id,1-(embedding <=> %s) AS sim FROM chunks ORDER BY embedding <=> %s LIMIT %s",
                    (str(vec), str(vec), 40))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [(r[0], float(r[1])) for r in rows]

    if mode == "baseline":
        return _pg_search(dense.embed(query))
    if mode == "hyde":
        hypo = gen_hypo(query)
        return _pg_search(dense.embed(hypo))
    if mode == "multiquery":
        qs = gen_multi(query)
        merged = {}
        for q in qs:
            for cid, sim in dense.search(q, top_k=20):   # dense.search 读 chunks 子块
                merged[cid] = max(merged.get(cid, 0.0), sim)
        return sorted(merged.items(), key=lambda x: -x[1])
    raise ValueError(mode)


def retrieve(strategy, bm25, query):
    if strategy == "bm25_only":
        return bm25.search(query, top_k=10)   # 纯关键词，暴露短板
    bm25_res = bm25.search(query, top_k=40)
    dense_res = dense_search(query, strategy)
    fused = rrf_fuse([bm25_res, dense_res], k=60, top=40)
    return fused[:10]   # 评测刻意不 rerank，纯粹看查询修饰对召回的影响


def run_strategy(name, tests, chunks, parents, bm25, strategy):
    print(f"\n===== 策略: {name} =====")
    recall = 0
    mrr = 0.0
    by_type = {}
    hard_tests = [t for t in tests if t.get("type") == "口语"]
    hard_recall = 0
    n = len(tests)
    hn = len(hard_tests)
    for t in tests:
        exp = t["keywords"]
        res = retrieve(strategy, bm25, t["q"])
        hit_rank = None
        hit_pid = None
        for rank, (cid, _) in enumerate(res[:10]):
            c = next((x for x in chunks if x["id"] == cid), None)
            pid = c["parent_id"] if c else cid
            pcontent = parents.get(pid) or parents.get(cid, "")
            if pcontent and any(kw in pcontent for kw in exp):
                if hit_rank is None:
                    hit_rank = rank + 1
                    hit_pid = pid
                break
        hit = hit_rank is not None
        if hit:
            recall += 1
            mrr += 1.0 / hit_rank
            if t.get("type") == "口语":
                hard_recall += 1
        bt = by_type.setdefault(t.get("type", "other"), [0, 0])
        bt[0] += 1
        if hit:
            bt[1] += 1
    print(f"Recall@10(整体) = {recall}/{n} = {recall / n:.3f}")
    print(f"MRR@10(整体)    = {mrr / n:.3f}")
    if hn:
        print(f"Recall@10(难题) = {hard_recall}/{hn} = {hard_recall / hn:.3f}")
    print("  分类型 Recall@10:")
    for typ, (tot, h) in by_type.items():
        print(f"    {typ:8s} {h}/{tot} = {h / tot:.3f}")
    return recall, hard_recall, hn


def main():
    if not (os.environ.get("API_KEY") and os.environ.get("BASE_URL")):
        print("[错误] 需 API_KEY/BASE_URL（HyDE/多查询要调 LLM 生成，embed 要 Key）。")
        sys.exit(1)
    chunks, parents = load_all()
    print(f"已加载子块 {len(chunks)} / 父块 {len(parents)}")
    bm25 = BM25()
    bm25.fit(chunks)
    with open("testset.json", encoding="utf-8") as f:
        tests = json.load(f)

    base, base_h, hn = run_strategy("baseline(hybrid 原query)", tests, chunks, parents, bm25, "baseline")
    bm25o, bm25o_h, _ = run_strategy("bm25_only(原句纯关键词)", tests, chunks, parents, bm25, "bm25_only")
    hyde, hyde_h, _ = run_strategy("HyDE(假设答案embed)", tests, chunks, parents, bm25, "hyde")
    mq, mq_h, _ = run_strategy("多查询(同义并集)", tests, chunks, parents, bm25, "multiquery")

    print("\n===== 对比小结（整体）=====")
    print(f"  baseline(hybrid) Recall@10 = {base / len(tests):.3f}")
    print(f"  bm25_only        Recall@10 = {bm25o / len(tests):.3f}  (Δ vs hybrid = {(bm25o - base) / len(tests):+.3f})")
    print(f"  HyDE             Recall@10 = {hyde / len(tests):.3f}  (Δ vs hybrid = {(hyde - base) / len(tests):+.3f})")
    print(f"  多查询           Recall@10 = {mq / len(tests):.3f}  (Δ vs hybrid = {(mq - base) / len(tests):+.3f})")

    if hn:
        print("\n===== 对比小结（难题子集: 口语/异名词）=====")
        print(f"  baseline(hybrid) 难题 Recall = {base_h}/{hn} = {base_h / hn:.3f}")
        print(f"  bm25_only        难题 Recall = {bm25o_h}/{hn} = {bm25o_h / hn:.3f}  (关键词检索短板)")
        print(f"  HyDE             难题 Recall = {hyde_h}/{hn} = {hyde_h / hn:.3f}")
        print(f"  多查询           难题 Recall = {mq_h}/{hn} = {mq_h / hn:.3f}")
        print(f"  → 难题上 HyDE/多查询 对 bm25_only 的增益:")
        print(f"    HyDE   Δ = {(hyde_h - bm25o_h) / hn:+.3f}")
        print(f"    多查询 Δ = {(mq_h - bm25o_h) / hn:+.3f}")


if __name__ == "__main__":
    main()
