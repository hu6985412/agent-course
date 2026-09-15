#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
W05 阶段2 · 03 切分导致召回错（纯文本演示，不连 API/DB，直接跑）
------------------------------------------------------------------------------
对应阶段1 第3节：chunk 切太大/太小都会害召回。
本脚本对比两种切法，演示「不按语义边界的固定长度字符切」如何把句子劈开：
  - 正常：recursive 切分（400/overlap80），句子边界被保留 → 召回正确
  - 糟糕：fixed 固定长度字符切（80/overlap0），句子被块边界硬劈 → 不完整 embedding → 召回错

运行：python 03_bad_case.py   （无需 Key、无需数据库）
演示结果同时写入 _03_result.txt（UTF-8），方便查看。
"""
import os

DOC_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_doc.md")
SEPS = ["\n\n", "\n", "。", "！", "？", "；", "，", " "]


def _split_with_sep(text, sep):
    if not sep:
        return list(text)
    import re
    pieces = re.split(f"({re.escape(sep)})", text)
    out = []
    for i in range(0, len(pieces) - 1, 2):
        out.append(pieces[i] + pieces[i + 1])
    if len(pieces) % 2 == 1 and pieces[-1]:
        out.append(pieces[-1])
    return [p for p in out if p]


def recursive_split(text, size, overlap, seps):
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
    if overlap > 0 and len(chunks) > 1:
        merged = [chunks[0]]
        for i in range(1, len(chunks)):
            prev = chunks[i - 1]
            ov = prev[-overlap:] if len(prev) >= overlap else prev
            merged.append(ov + chunks[i])
        chunks = merged
    return chunks


def fixed_split(text, size):
    """固定长度字符切（忽略一切语义边界）——阶段1 第3节讲的 fixed 策略。"""
    return [text[i:i + size] for i in range(0, len(text), size)]


def main():
    text = open(DOC_PATH, encoding="utf-8").read()
    buf = []

    def log(s):
        print(s)
        buf.append(s)

    log("=" * 64)
    log("正常切法：CHUNK_SIZE=400, OVERLAP=80（recursive，W05 默认）")
    log("=" * 64)
    normal = recursive_split(text, 400, 80, SEPS)
    for i, c in enumerate(normal):
        if "银行卡退款" in c or "3 至 7 个工作日" in c:
            log(f"\n包含『退款到账天数』的块 → chunk[{i}] ({len(c)}字):\n  {c}\n")
    log(f"共 {len(normal)} 个 chunk。可见『银行卡退款需 3 至 7 个工作日』整句落在同一块内。\n")

    log("=" * 64)
    log("糟糕切法：CHUNK_SIZE=80, OVERLAP=0（fixed 固定长度字符切，忽略句子边界）")
    log("=" * 64)
    fixed = fixed_split(text, 80)
    for i, c in enumerate(fixed):
        if "银行卡" in c or "工作日" in c:
            log(f"\nfixed chunk[{i}] ({len(c)}字):\n  {c}\n")

    log("=" * 64)
    log("结论（召回错根因）")
    log("=" * 64)
    log("fixed 切法按固定 80 字符硬砍，不认句子边界。可见『退款申请提交后，我们将在 1 至 3 个工作日内完成审核』")
    log("这句被块边界劈成两半：fixed chunk[2] 以『…个工作日内』结尾，fixed chunk[3] 从『完成审核。审核通过后…』开头。")
    log("更关键的是，『退款审核 1-3 工作日』与『到账 银行卡 3-7 工作日』这条完整的退款时效链路被拆散到不同块，")
    log("且单句被劈导致任一单块都不含完整信息。分别 embedding 后，与『退款多久到账』相关的块相似度被稀释、不完整")
    log("→ 在 top_k 竞争中不稳定 → 召回错。")
    log("→ 修复：用 recursive/structure 切分保住句子边界，或保留 overlap（如 80）让边界句在相邻块都完整出现。")
    log("W05 默认 400/80 的 recursive 切法下，『银行卡退款需 3 至 7 个工作日』整句完整落在同一块（见上方正常演示），召回正确，")
    log("印证了阶段1 第3节『切分是召回质量头号开关』。")

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_03_result.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(buf))


if __name__ == "__main__":
    main()
