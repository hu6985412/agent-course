#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
W07 阶段2 · 复杂 PDF 解析 + 父子分段(small-to-big) + pgvector 入库
======================================================================
主解析器：Docling（IBM 开源，本地免费，Tier2 级：合并单元格/跨页表更稳）
回退解析器：PyMuPDF + 正则（Tier1 轻量，Docling 不可用时兜底，表格质量较弱）
父子分段：只 embed 子块；检索命中子块 -> 返回父块全文给 LLM（small-to-big）
  - 表格 = 原子父块，不劈（golden rule：tables are atomic chunks）
  - 文本父块按 ~PARENT_MAX 字切；父块再滑窗切子块(~CHILD_SIZE, overlap)

运行（PS）：
  # 解析+分段不入库（沙箱/无 Key 可跑，验证分段逻辑）
  python ingest.py --pdf "路径/600015_20260829_UUMS.pdf" --dry-run

  # 本机灌库（设好 Key + 已起 gp17 建 w07rag）
  $env:PG_DB="w07rag"; python ingest.py --pdf "路径/600015_20260829_UUMS.pdf" --pdf "路径/600015_20260829_JE2L.pdf"
"""
import os
import sys
import json
import argparse

os.environ.setdefault("PG_DB", "w07rag")  # W07 默认库；amber 本机设 PG_* 即可

DIM = 1024
PARENT_MAX = 1200      # 父块最大字数
CHILD_SIZE = 400       # 子块窗口
CHILD_OVERLAP = 80     # 子块滑动重叠


# ---------------- 解析层（Docling 主 / PyMuPDF 回退）----------------
def parse_docling(pdf_path):
    from docling.document_converter import DocumentConverter
    conv = DocumentConverter()
    res = conv.convert(pdf_path)
    return res.document.export_to_markdown()


def parse_pymupdf(pdf_path):
    import fitz
    doc = fitz.open(pdf_path)
    out = []
    for i, page in enumerate(doc):
        out.append(f"\n\n[page {i + 1}]\n" + page.get_text())
    return "\n".join(out)


def parse_pdfplumber(pdf_path):
    """Tier1.5：比 PyMuPDF 强——能识别表格并转成 Markdown 的 | 行，
    让 split_parent_child 的表格原子逻辑在沙箱也能验证。纯 python，不依赖 torch。"""
    import pdfplumber
    out = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            out.append(f"\n\n[page {i + 1}]\n")
            txt = page.extract_text() or ""
            if txt.strip():
                out.append(txt + "\n")
            for tbl in page.extract_tables():
                if not tbl:
                    continue
                md = []
                ncol = max(len(r) for r in tbl)
                for r in tbl:
                    cells = [(c if c is not None else " ") for c in r]
                    cells += [" "] * (ncol - len(cells))
                    md.append("| " + " | ".join(str(x) for x in cells) + " |")
                if md:
                    sep = "| " + " | ".join(["---"] * ncol) + " |"
                    out.append("\n" + md[0] + "\n" + sep + "\n" + "\n".join(md[1:]) + "\n")
    return "\n".join(out)


def parse_pdf(pdf_path):
    try:
        return parse_docling(pdf_path), "docling"
    except Exception as e:
        print(f"[回退] Docling 失败({e})，尝试 pdfplumber（可识别表格）")
        try:
            return parse_pdfplumber(pdf_path), "pdfplumber"
        except Exception as e2:
            print(f"[回退] pdfplumber 失败({e2})，改用 PyMuPDF 纯文本")
            return parse_pymupdf(pdf_path), "pymupdf"


# ---------------- 父子分段 ----------------
def _is_table_line(line):
    s = line.strip()
    return s.startswith("|") and s.endswith("|") and "|" in s[1:-1]


def _split_text_window(text, size, overlap):
    """滑窗切分文本为子块（保留 overlap）。"""
    if len(text) <= size:
        return [text] if text.strip() else []
    chunks, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        seg = text[start:end]
        if seg.strip():
            chunks.append(seg)
        if end == len(text):
            break
        start = end - overlap
    return chunks


def split_parent_child(markdown, doc_id, doc_title):
    """
    返回 (parents, children)
    parents:  [{id, doc_id, content, meta}]
    children: [{id, doc_id, content, parent_id, meta}]
    """
    lines = markdown.split("\n")
    parents, children = [], []
    buf = []
    cur_section = ""
    p_idx = 0
    c_idx = 0

    def flush_text_parent():
        nonlocal p_idx, c_idx
        text = "\n".join(buf).strip()
        buf.clear()
        if not text:
            return
        p_idx += 1
        pid = f"{doc_id}#P{p_idx}"
        meta = {"doc_title": doc_title, "section": cur_section, "kind": "text"}
        parents.append({"id": pid, "doc_id": doc_id, "content": text, "meta": meta})
        for sub in _split_text_window(text, CHILD_SIZE, CHILD_OVERLAP):
            c_idx += 1
            cid = f"{pid}#C{c_idx}"
            children.append({"id": cid, "doc_id": doc_id, "content": sub,
                             "parent_id": pid, "meta": meta})

    i = 0
    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if s.startswith("#"):                      # 标题 -> 更新 section
            cur_section = s.lstrip("#").strip()
            i += 1
            continue
        if _is_table_line(line):                    # 表格块（连续 | 行）
            flush_text_parent()
            tbl_lines = []
            while i < len(lines) and _is_table_line(lines[i]):
                tbl_lines.append(lines[i])
                i += 1
            tbl = "\n".join(tbl_lines).strip()
            if not tbl:
                continue
            p_idx += 1
            pid = f"{doc_id}#P{p_idx}"
            meta = {"doc_title": doc_title, "section": cur_section, "kind": "table"}
            parents.append({"id": pid, "doc_id": doc_id, "content": tbl, "meta": meta})
            c_idx += 1                              # 表格原子：子块=自身（不劈）
            cid = f"{pid}#C{c_idx}"
            children.append({"id": cid, "doc_id": doc_id, "content": tbl,
                             "parent_id": pid, "meta": meta})
            continue
        if s == "":                                 # 空行：超阈值切父块
            if buf and len("\n".join(buf)) >= PARENT_MAX:
                flush_text_parent()
            else:
                buf.append("")
            i += 1
            continue
        buf.append(line)
        i += 1
    flush_text_parent()
    return parents, children


# ---------------- 入库 ----------------
def embed(text):
    import dense
    return dense.embed(text)


def build_index(parents, children):
    import psycopg2
    PG = dict(
        host=os.environ.get("PG_HOST", "127.0.0.1"),
        port=int(os.environ.get("PG_PORT", 5432)),
        dbname=os.environ.get("PG_DB", "w07rag"),
        user=os.environ.get("PG_USER", "amber"),
        password=os.environ.get("PG_PASSWORD", "amber123"),
    )
    conn = psycopg2.connect(**PG)
    cur = conn.cursor()
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    cur.execute("""CREATE TABLE IF NOT EXISTS parent_chunks(
        id text PRIMARY KEY, doc_id text, content text, meta jsonb);""")
    cur.execute("""CREATE TABLE IF NOT EXISTS chunks(
        id text PRIMARY KEY, doc_id text, content text,
        embedding vector(1024), parent_id text);""")
    cur.execute("CREATE INDEX IF NOT EXISTS chunks_hnsw ON chunks USING hnsw (embedding vector_cosine_ops);")
    for p in parents:
        cur.execute(
            "INSERT INTO parent_chunks(id, doc_id, content, meta) VALUES(%s,%s,%s,%s) "
            "ON CONFLICT (id) DO UPDATE SET content=EXCLUDED.content, meta=EXCLUDED.meta;",
            (p["id"], p["doc_id"], p["content"], json.dumps(p["meta"], ensure_ascii=False)),
        )
    for c in children:
        vec = embed(c["content"])
        cur.execute(
            "INSERT INTO chunks(id, doc_id, content, embedding, parent_id) VALUES(%s,%s,%s,%s,%s) "
            "ON CONFLICT (id) DO UPDATE SET content=EXCLUDED.content, embedding=EXCLUDED.embedding, parent_id=EXCLUDED.parent_id;",
            (c["id"], c["doc_id"], c["content"], str(vec), c["parent_id"]),
        )
    conn.commit()
    cur.close()
    conn.close()
    print(f"入库完成：{len(parents)} 父块 / {len(children)} 子块 -> {PG['dbname']}")


def _require_pdf(pdf):
    """PDF 不随附仓库（.gitignore 忽略 *.pdf），缺失时给出明确下载指引而非裸报错。"""
    if os.path.exists(pdf):
        return
    print(f"[错误] 找不到 PDF 文件：{pdf}")
    print("  本示例文档为华夏银行 2026 年半年度报告（公开披露，非本仓库随附）。")
    print("  请从以下来源下载一份对应的中文财报，按文件名放入本目录：")
    print("    全文：巨潮资讯网 cninfo.com.cn 或 上交所 stock.sse.com.cn 搜『华夏银行 2026 年半年度报告』")
    print("    业绩摘要：同站搜『华夏银行 2026 年半年度主要会计数据和指标』")
    print("  命名规则（与 code/README.md 一致）：")
    print("    600015_20260829_UUMS.pdf  <- 半年度报告全文")
    print("    600015_20260829_JE2L.pdf  <- 业绩摘要")
    print("  （仓库不随附 PDF 是刻意规避体积与版权问题；详见 code/README.md『示例文档』说明）")
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", action="append", required=True, help="PDF 路径，可多次")
    ap.add_argument("--dry-run", action="store_true", help="只解析+分段，不连 PG 不 embed")
    args = ap.parse_args()

    all_parents, all_children = [], []
    for pdf in args.pdf:
        _require_pdf(pdf)
        doc_id = os.path.splitext(os.path.basename(pdf))[0]
        print(f"\n=== 解析 {pdf} ===")
        md, engine = parse_pdf(pdf)
        print(f"解析引擎: {engine} | markdown 长度: {len(md)} 字")
        parents, children = split_parent_child(md, doc_id, doc_title=os.path.basename(pdf))
        tbl = sum(1 for p in parents if p["meta"]["kind"] == "table")
        print(f"父块 {len(parents)}（其中表格原子 {tbl}） / 子块 {len(children)}")
        all_parents += parents
        all_children += children

    if args.dry_run:
        print("\n[dry-run] 不连 PG。样例：")
        for p in all_parents[:3]:
            print(f"  父 {p['id']} [{p['meta']['kind']}] {p['content'][:50].replace(chr(10), ' ')}...")
        for c in all_children[:3]:
            print(f"  子 {c['id']} -> 父 {c['parent_id']} {c['content'][:40].replace(chr(10), ' ')}...")
        print(f"\n合计 父块 {len(all_parents)} / 子块 {len(all_children)}")
        return

    if not (os.environ.get("API_KEY") and os.environ.get("BASE_URL")):
        print("[错误] 入库需 API_KEY/BASE_URL（embed 子块）。请先用 bat 加载环境，或加 --dry-run。")
        sys.exit(1)
    build_index(all_parents, all_children)


if __name__ == "__main__":
    main()
