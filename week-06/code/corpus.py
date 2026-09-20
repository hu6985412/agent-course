#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
W06 阶段2 · 语料加载 + 递归切分
------------------------------------------------------------------------------
复用 W05 的 recursive_split(400/80)（滑动窗口 overlap），把 6 篇财报/可转债
语料切成 chunk，作为 BM25 / Dense / Rerank 三路检索的「单一事实来源」。
块 id 规则：{doc_id}#{序号}，如 指标定义#1。
"""
import os
import glob

SEPS = ["\n\n", "\n", "。", "！", "？", "；", "，", " "]
CHUNK_SIZE, OVERLAP = 400, 80


def _split_with_sep(text, sep):
    """按 sep 切，但把 sep 保留到每块末尾（对齐 recursive character splitter）。"""
    if not sep:
        return [text]
    parts = text.split(sep)
    out = []
    for i, p in enumerate(parts):
        out.append(p + sep if i < len(parts) - 1 else p)
    return out


def recursive_split(text, size, overlap, seps):
    if len(text) <= size:
        return [text] if text.strip() else []
    sep = seps[0]
    pieces = _split_with_sep(text, sep)
    chunks, cur = [], ""
    for p in pieces:
        if len(cur) + len(p) <= size:
            cur += p
        else:
            if cur.strip():
                chunks.append(cur)
            if len(p) > size and len(seps) > 1:
                chunks.extend(recursive_split(p, size, overlap, seps[1:]))
            else:
                cur = p
    if cur.strip():
        chunks.append(cur)
    if overlap > 0 and len(chunks) > 1:           # sliding window overlap
        merged = [chunks[0]]
        for i in range(1, len(chunks)):
            ov = chunks[i - 1][-overlap:]
            merged.append(ov + chunks[i])
        chunks = merged
    return chunks


def load_chunks(corpus_dir="corpus"):
    chunks = []
    for path in sorted(glob.glob(os.path.join(corpus_dir, "*.md"))):
        doc_id = os.path.splitext(os.path.basename(path))[0]
        with open(path, encoding="utf-8") as f:
            text = f.read()
        for i, p in enumerate(recursive_split(text, CHUNK_SIZE, OVERLAP, SEPS)):
            chunks.append({"id": f"{doc_id}#{i + 1}", "doc_id": doc_id, "content": p})
    return chunks


if __name__ == "__main__":
    cs = load_chunks()
    print(f"共 {len(cs)} 个 chunk")
    for c in cs:
        print(f"  {c['id']}  ({len(c['content'])}字)  {c['content'][:24]}")
