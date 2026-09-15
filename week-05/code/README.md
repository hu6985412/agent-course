# W05 代码运行说明（week-05/code）

> 配套正文：[../README.md](../README.md)
> 这套脚本演示「文本 → Embedding → pgvector 入库 → 余弦检索 → 切分召回错根因」完整链路。

## 1. 依赖

```bash
pip install -r requirements.txt
# openai / psycopg2-binary / numpy
```

## 2. 环境准备（只需一次）

### 2.1 起 pgvector（Docker，与你的 MySQL agent_runtime 各管各的）

```bash
bash 00_start_pgvector.sh
# 等价于：docker run -d --name pgvector -e POSTGRES_PASSWORD=pgpass -p 5432:5432 pgvector/pgvector:pg17
```

### 2.2 建用户与库（让 01/02 零改动）

```bash
# 看容器名
docker ps --format "{{.Names}}\t{{.Image}}"
# 用你启动时的 postgres 密码替换 <PGPASS>（若当时是 trust 模式，去掉 -W <PGPASS>）
docker exec -i <容器名> psql -U postgres -W <PGPASS> -c "CREATE USER amber WITH PASSWORD 'amber123' SUPERUSER;"
docker exec -i <容器名> psql -U postgres -W <PGPASS> -c "CREATE DATABASE w05rag OWNER amber;"
# 验证
docker exec -i <容器名> psql -U amber -d w05rag -c "SELECT 1;"
```

## 3. 注入环境变量（Key 只从环境变量读，不写死）

用仓库外的 `start-env-windows.bat` 副本（BASE_URL 改成百炼地址）双击注入；或在 PS 窗口覆盖：

```powershell
$env:API_KEY = "sk-你的百炼key"
$env:BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
```

> 中转站若转发了 `/embeddings` 路由，把 BASE_URL 换回中转地址即可，其余不变。
> embedding 模型在 `01_build_index.py` 里写死为 `qwen3.7-text-embedding-flash`（1024 维），无需改。

## 4. 运行顺序

```powershell
# ① 建索引：递归切分(400/80) + 百炼 embedding + 入库 + 建 HNSW 余弦索引
python 01_build_index.py

# ② 查询（默认 top_k=5 阈值=0）
python 02_query.py "退款多久到账"

# 诊断：打印全部 chunk 相似度降序（看噪声块是否最低）
python 02_query.py "退款多久到账" 20 0 --show-all

# 调 top_k / 阈值观察召回
python 02_query.py "退款多久到账" 3 0        # top_k=3
python 02_query.py "退款多久到账" 5 0.3      # 阈值 0.3 剔噪声

# ③ 纯文本演示「切分导致召回错」根因（无需 Key）
python 03_bad_case.py
# 输出见 _03_result.txt
```

## 5. 实验 B：调切分粒度对比召回（验收用）

把 `01_build_index.py` 里 `CHUNK_SIZE=400` 改 `120`、`OVERLAP=80` 改 `0`，重跑 ① ②，对比最佳块相似度变化。
**实验完务必改回 400/80 再重跑 ①**，恢复正式库（W06 会基于它）。

## 6. 带过滤条件的混合 SQL（pgvector 核心优势）

向量列和普通列能在**一条 SQL** 里混合过滤——这是相对专用向量库的关键优势：

```sql
-- 只在 doc_id='doc1' 的文档里，找与查询向量最像、且相似度≥0.3 的 5 块
SELECT id, content,
       1 - (embedding <=> :query_vec) AS similarity
FROM chunks
WHERE doc_id = 'doc1'                         -- 普通列过滤
  AND embedding <=> :query_vec < 0.7          -- 余弦距离阈值（= 1 - similarity > 0.3）
ORDER BY embedding <=> :query_vec
LIMIT 5;
```

> 真正的「向量 + BM25 混合检索（RRF 融合）」是 W06 的内容，本周只做纯向量 + 上述带 WHERE 的混合 SQL。
