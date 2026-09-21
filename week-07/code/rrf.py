#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
W06 阶段2 · RRF 融合（Reciprocal Rank Fusion）
------------------------------------------------------------------------------
对应阶段1 第4小节：两路（或更多）有序列表，按排名融合，完全不看原始分数。
  fused(d) = Σ  1 / (k + rank_i(d) + 1)      # rank 用 0-based，+1 后从 k+1 起
默认 k=60。共识（两路都靠前）的文档得分最高。
"""


def rrf_fuse(ranked_lists, k=60, top=40):
    """
    ranked_lists: list[list[(id, score)]]，每个元素是一路召回的有序结果。
    返回按融合分降序的 (id, fused_score) 列表，截断到 top。
    """
    fused = {}
    for rl in ranked_lists:
        for rank, (cid, _) in enumerate(rl):
            fused[cid] = fused.get(cid, 0.0) + 1.0 / (k + rank + 1)
    return sorted(fused.items(), key=lambda x: -x[1])[:top]


if __name__ == "__main__":
    # 演示：Dense 路 + BM25 路
    dense = [("d1", 0.82), ("d5", 0.65), ("d3", 0.51), ("d8", 0.40)]
    bm25 = [("d2", 18.4), ("d5", 12.1), ("d4", 9.0), ("d1", 6.2)]
    for cid, s in rrf_fuse([dense, bm25], k=60, top=6):
        print(f"  {cid}  fused={s:.4f}")
