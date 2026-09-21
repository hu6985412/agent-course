# W07 · 进阶 RAG 实验代码

把「复杂 PDF（表格密集、跨页）」跑通成「解析 → 结构化 → 父子分段 → 入库 → 可问答 + 每句溯源」的完整链路。

> 本目录以**华夏银行 2026 年半年度报告**（公开披露，`600015_20260829_UUMS.pdf` 全文 + `600015_20260829_JE2L.pdf` 业绩摘要）为示例文档，演示「解析 → 父子分段 → 入库 → 可问答 + 每句溯源」完整链路。示例文档为公开披露文件，请从巨潮资讯网（cninfo）或上交所下载后，按上述文件名放入本目录。

## 1. 依赖安装

```bash
pip install psycopg2-binary openai docling pdfplumber pymupdf reportlab jieba
```

- `docling`：Tier2 主解析器（本地免费，合并单元格 / 跨页表更稳），装不上会自动回退 `pdfplumber` → `PyMuPDF`。
- `pymupdf`：回退纯文本解析。
- `openai`：embedding 与生成问答（走 OpenAI 兼容协议）。

## 2. 环境变量

把 `.env.example` 复制为 `.env` 并填入（**真实 Key 只在终端环境变量里，不进文件**）：

```powershell
$env:API_KEY="你的Key"; $env:BASE_URL="https://你的网关/v1"; $env:MODEL="deepseek-v4-flash"; $env:PG_DB="w07rag"
```

## 3. 快速开始（无需数据库）

```bash
# 只解析 + 父子分段，不连 PG、不 embed（验证分段逻辑，最快）
python ingest.py --pdf 600015_20260829_UUMS.pdf --dry-run

# 分段逻辑单测（不连 PG）
python test_split.py
```

## 4. 接入真实文档与数据库

```bash
# 1) 起 pgvector（与课程其它周共用容器 gp17，按库名区分周次 w07rag）
docker run -d --name gp17 -e POSTGRES_PASSWORD=amber123 -p 5432:5432 pgvector/pgvector:pg17
docker exec -i gp17 psql -U postgres -c "CREATE DATABASE w07rag OWNER postgres;"

# 2) 解析 + 入库（需 API_KEY/BASE_URL 做 embedding）
python ingest.py --pdf "路径/600015_20260829_UUMS.pdf" --pdf "路径/600015_20260829_JE2L.pdf"

# 3) 溯源问答：命中子块 -> 返回父块 -> LLM -> 句末 [n] 标注引用
$env:Q="华夏银行2026上半年营业收入是多少"; python qa.py

# 4) 查询改写 / HyDE 评测对比
python hyde_eval.py

```

## 5. 单测（不连 PG，纯函数验证）

```bash
```
python test_compute.py

## 6. 文件清单

| 文件 | 作用 |
|---|---|
| `ingest.py` | 复杂 PDF 解析回退链（docling→pdfplumber→PyMuPDF）+ 父子分段（small-to-big）+ pgvector 入库 |
| `qa.py` | 双路召回（BM25 + 向量）→ RRF 融合 → 重排 → 返回父块 → LLM → 每句 `[n]` 溯源 |
| `hyde_eval.py` | 查询改写 / HyDE 多策略召回评测对比（Recall@10 / MRR@10） |
| `bm25.py` / `dense.py` / `rrf.py` / `rerank.py` | 检索组件：BM25、向量检索、RRF 融合、cross-encoder 重排 |
| `compute_qa.py` + `test_compute.py` | 计算型问答（通用范式）：程序化取数 + safe_eval 沙箱 + 逐步溯源 + 与报告原文校验 |
| `testset.json` | 15 题评测集（取数 / 指标 / 口语三类），用于 HyDE/多查询 A/B |
| `test_*.py` | 上述各能力的纯函数单测 |

> 示例文档为华夏银行 2026 半年报（公开披露），请从巨潮资讯网或上交所下载后按文件名 `600015_20260829_UUMS.pdf` / `600015_20260829_JE2L.pdf` 放入本目录。
