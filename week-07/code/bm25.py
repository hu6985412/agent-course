#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
W06 阶段2 · 手搓 BM25（Okapi BM25）
------------------------------------------------------------------------------
对应阶段1 第2小节公式。不依赖 rank_bm25，纯 Python 实现，方便你看清：
  score(D,Q) = Σ IDF(qᵢ) · f·(k1+1) / ( f + k1·(1-b+b·|D|/avgdl) )
中文分词用 jieba（生产可换 rank_bm25）；没有 jieba 时退化为按字 + 拉丁词。
关键：中文「扣非净利润」vs「归母净利润」共享「净利润」三字，必须分词到词级，
BM25 才能把这两个 token 当不同词分开——这正是 W06 第①类失效的命门。
"""
import math
import re

try:
    import jieba
    jieba.setLogLevel(20)
    _HAS_JIEBA = True
except Exception:
    _HAS_JIEBA = False


class BM25:
    def __init__(self, k1=1.5, b=0.75):
        self.k1 = k1
        self.b = b

    @staticmethod
    def _tok(text):
        if _HAS_JIEBA:
            toks = []
            for seg in jieba.lcut(text):
                seg = seg.strip()
                if not seg or re.fullmatch(r"[\s\W_]+", seg):
                    continue
                if re.search(r"[a-zA-Z0-9]", seg):
                    seg = seg.lower()
                toks.append(seg)
            return toks
        # 退化：CJK 按字、拉丁/数字按词
        toks = []
        for m in re.findall(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]", text):
            toks.append(m.lower() if re.search(r"[a-zA-Z0-9]", m) else m)
        return toks

    def fit(self, chunks):
        self.chunks = chunks
        self.docs = [self._tok(c["content"]) for c in chunks]
        n = len(self.docs)
        self.avgdl = sum(len(d) for d in self.docs) / n if n else 0
        df = {}
        for d in self.docs:
            for t in set(d):
                df[t] = df.get(t, 0) + 1
        self.idf = {t: math.log((n - c + 0.5) / (c + 0.5) + 1) for t, c in df.items()}
        self.N = n

    def search(self, query, top_k=20):
        q = self._tok(query)
        out = []
        for i, d in enumerate(self.docs):
            dl = len(d)
            freq = {}
            for t in d:
                freq[t] = freq.get(t, 0) + 1
            score = 0.0
            for t in q:
                if t not in self.idf:
                    continue
                f = freq.get(t, 0)
                if f == 0:
                    continue
                score += self.idf[t] * (f * (self.k1 + 1)) / (
                    f + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
                )
            out.append((self.chunks[i]["id"], score))
        out.sort(key=lambda x: -x[1])
        return out[:top_k]
