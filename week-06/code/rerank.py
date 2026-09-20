#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
W06 阶段2 · Cross-encoder 重排（双模式）
------------------------------------------------------------------------------
对应阶段1 第6小节：对 RRF 融合后的前 K 篇做「query+doc 拼一起过 transformer」精排。
- 真·cross-encoder：RERANKER=cross 且装了 sentence-transformers 时，用 BAAI/bge-reranker-v2-m3。
- 兜底（无模型时）：lexical fallback = 在候选子集上重算 BM25 分数，纯粹用来演示
  「漏斗最窄处再做一次精排」的流程与延迟，并非真 cross-encoder（正文须如实标注）。
沙箱无模型 → 走兜底；你本机装好 sentence-transformers 后设 RERANKER=cross 即真重排。
"""
import os

# 真 cross-encoder 模型较重，缓存为模块级单例，避免 eval 跑 30 题重复加载 30 次。
_CE_MODEL = None


def _get_ce():
    global _CE_MODEL
    if _CE_MODEL is None:
        from sentence_transformers import CrossEncoder
        # 首次会从 HuggingFace 下载权重（约 2.2GB），之后走本地缓存
        _CE_MODEL = CrossEncoder("BAAI/bge-reranker-v2-m3")
    return _CE_MODEL


def available():
    return os.environ.get("RERANKER") == "cross"


def rerank(query, candidates, top_k=8):
    """
    candidates: list[(id, content)]
    返回 list[(id, score)] 降序，截断到 top_k。
    """
    if available():
        _ce = _get_ce()
        pairs = [(query, c) for _, c in candidates]
        scores = _ce.predict(pairs)
        ranked = sorted(zip([cid for cid, _ in candidates], scores), key=lambda x: -x[1])
        return [(cid, float(s)) for cid, s in ranked[:top_k]]
    # ---- lexical fallback（演示用，非真 cross-encoder）----
    from bm25 import BM25
    bm = BM25()
    tmp = [{"id": cid, "content": c} for cid, c in candidates]
    bm.fit(tmp)
    return bm.search(query, top_k=top_k)
