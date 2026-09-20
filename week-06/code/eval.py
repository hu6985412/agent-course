#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
W06 阶段2 · 三方案评测骨架
------------------------------------------------------------------------------
测试集 testset.json：每题 {q, expected_doc:[...], type}
  - type ∈ exact_token / semantic / question / antonym（用于分组看各方案的强弱）
指标：Recall@10（top10 中是否含任一相关 doc 的块）、MRR@10（首个相关块排名倒数）
另含「判别力探针」：验证 BM25 能否把相近专有名词（扣非/归母、赎回/回售、下修/转股期）分开。

运行：python eval.py            # 沙箱无 Key → 跑 BM25-only + 判别力探针
      （本机注入 Key 后）python eval.py   # 自动加跑 Hybrid / Hybrid+Rerank
"""
import json
import time

from corpus import load_chunks
from bm25 import BM25
import dense, rerank
from rrf import rrf_fuse


def retrieve(strategy, bm25, chunks, query):
    bm25_res = bm25.search(query, top_k=40)
    if strategy == "bm25":
        return bm25_res
    # hybrid / rerank 需要 Dense
    dense_res = dense.search(query, top_k=40)
    fused = rrf_fuse([bm25_res, dense_res], k=60, top=40)
    if strategy == "hybrid":
        return fused
    # rerank：只对融合后前 20 篇精排
    content = {c["id"]: c["content"] for c in chunks}
    cand = [(cid, content[cid]) for cid, _ in fused[:20] if cid in content]
    return rerank.rerank(query, cand, top_k=8)


def run_strategy(name, chunks, bm25, strategy, tests):
    print(f"\n===== 方案: {name} =====")
    recall = 0
    mrr = 0.0
    lat = 0.0
    by_type = {}
    n = len(tests)
    for t in tests:
        q = t["q"]
        exp = set(t["expected_doc"])
        t0 = time.time()
        res = retrieve(strategy, bm25, chunks, q)
        lat += time.time() - t0
        first_rank = None
        for rank, (cid, _) in enumerate(res[:10]):
            if cid.split("#")[0] in exp:
                if first_rank is None:
                    first_rank = rank + 1
                break
        hit = first_rank is not None
        if hit:
            recall += 1
            mrr += 1.0 / first_rank
        bt = by_type.setdefault(t["type"], [0, 0])
        bt[0] += 1
        if hit:
            bt[1] += 1
    print(f"Recall@10 = {recall}/{n} = {recall / n:.3f}")
    print(f"MRR@10    = {mrr / n:.3f}")
    print(f"平均延迟  = {lat / n * 1000:.1f} ms/query")
    print("  分类型 Recall@10:")
    for typ, (tot, hit) in by_type.items():
        print(f"    {typ:12s} {hit}/{tot} = {hit / tot:.3f}")


def discrimination(chunks, bm25):
    # 直接比「目标块」与「干扰块」的排名（同一近义词对里，query 应把目标块排到干扰块前面）
    # 注入 Key 时额外输出 Hybrid(RRF) 下的排名；若再设 RERANKER=cross 则再加一列 [Rerank]
    # 直观对照「BM25 翻车 / Hybrid 兜住 / 真 cross-encoder 能否再兜一层」
    probes = [
        ("扣非净利润", "指标定义#1", "指标定义#2"),
        ("赎回条款", "赎回与回售条款#1", "赎回与回售条款#2"),
        ("下修条款", "转股价与下修#2", "转股价与下修#1"),
    ]
    use_rerank = dense.available() and rerank.available()
    content = {c["id"]: c["content"] for c in chunks}

    def rank_in(res_list, tgt, dis):
        rank = {cid: i + 1 for i, (cid, _) in enumerate(res_list)}
        return rank.get(tgt), rank.get(dis)

    print("\n===== 判别力探针（相近专有名词能否被检索分开）=====")
    if use_rerank:
        print("  [BM25] / [Hybrid] / [Rerank] 三路对照（[Rerank] 为真 cross-encoder 时才有意义）")
    for q, tgt, dis in probes:
        res = bm25.search(q, top_k=40)
        rt_bm, rd_bm = rank_in(res, tgt, dis)
        ok_bm = rt_bm is not None and (rd_bm is None or rt_bm < rd_bm)
        line = f"  Q='{q}': [BM25]  目标 #{rt_bm} | 干扰 #{rd_bm} -> {'✅ 分离' if ok_bm else '❌ 混淆'}"
        if dense.available():
            d_res = dense.search(q, top_k=40)
            fused = rrf_fuse([res, d_res], k=60, top=40)
            rt_hy, rd_hy = rank_in(fused, tgt, dis)
            ok_hy = rt_hy is not None and (rd_hy is None or rt_hy < rd_hy)
            line += f"   ||   [Hybrid] 目标 #{rt_hy} | 干扰 #{rd_hy} -> {'✅ 分离' if ok_hy else '❌ 混淆'}"
            if use_rerank:
                cand = [(cid, content[cid]) for cid, _ in fused[:20] if cid in content]
                rr = rerank.rerank(q, cand, top_k=8)
                rt_rr, rd_rr = rank_in(rr, tgt, dis)
                ok_rr = rt_rr is not None and (rd_rr is None or rt_rr < rd_rr)
                line += f"   ||   [Rerank] 目标 #{rt_rr} | 干扰 #{rd_rr} -> {'✅ 分离' if ok_rr else '❌ 混淆'}"
        print(line)


def main():
    chunks = load_chunks("corpus")
    print(f"语料块数: {len(chunks)}")
    bm25 = BM25()
    bm25.fit(chunks)

    with open("testset.json", encoding="utf-8") as f:
        tests = json.load(f)

    run_strategy("BM25-only", chunks, bm25, "bm25", tests)
    if dense.available():
        run_strategy("Hybrid(RRF)", chunks, bm25, "hybrid", tests)
        run_strategy("Hybrid+Rerank", chunks, bm25, "rerank", tests)
    else:
        print("\n[跳过] Dense 检索不可用（未注入 API_KEY/BASE_URL）。")
        print("         Hybrid / Hybrid+Rerank 需你本机注入 Key 后运行 eval.py。")
    discrimination(chunks, bm25)


if __name__ == "__main__":
    main()
