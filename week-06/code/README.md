# W06 阶段2 运行说明

## 目录
- `corpus/`：6 篇财报/可转债风格语料（切块 400/80）
- `corpus.py`：加载 + 递归切分（复用 W05）
- `bm25.py`：手搓 Okapi BM25（jieba 分词；无 jieba 退化为按字）
- `rrf.py`：RRF 融合（k=60）
- `dense.py`：Dense 向量检索（百炼 embedding + pgvector，Key 门控）
- `rerank.py`：Cross-encoder 重排（双模式：本地模型 / lexical 兜底）
- `eval.py`：三方案评测 + 判别力探针
- `testset.json`：30 题测试集（exact_token / semantic / question / antonym）

## 沙箱可直接跑（无需 Key，只需 jieba）
```
pip install jieba
python eval.py        # 只跑 BM25-only + 判别力探针
```

## 本机跑全三方案（PowerShell · 需百炼 Key + Docker）

前置：本机已装 Docker；已调用 `start-env-windows.bat` 加载 API_KEY/BASE_URL/MODEL
（bat 末尾会自动开一个 PowerShell 子进程，本窗口 `$env:API_KEY` 等直接可用）。
依赖：`pip install -r requirements.txt`（bat 已把 venv 的 pip 放进 PATH）。
```powershell
# 1) 校验环境（bat 的 PYTHON_HOME 须指向含 jieba 的 venv，否则 W06 的 import jieba 会挂）
python --version                       # 应显示 Python 3.13.x
python -c "import jieba, numpy; print('jieba+numpy ok')"

# 2) pgvector 连接（bat 不含，手写命令行加载；gp17 已建好 w06rag，本步告知 python 怎么连）
$env:PG_HOST="127.0.0.1"; $env:PG_PORT="5432"; $env:PG_DB="w06rag"; $env:PG_USER="amber"; $env:PG_PASSWORD="amber123"
#   ⚠️ 若 gp17 的 amber 密码不是 amber123，把上面 PG_PASSWORD 改成真实值

# 3) 灌库（首次建表 + 写 9 个 chunk 的 1024 维向量，需联网调百炼）
python -c "from corpus import load_chunks; import dense; dense.build_index(load_chunks('corpus'))"
#   预期：已写入 9 个 chunk 到 w06rag.chunks

# 4) 三方案对比（检测到 API_KEY 自动加跑 Hybrid / Hybrid+Rerank）
python eval.py
#   预期：方案从 1 个 → 3 个；判别力探针显示 [BM25] vs [Hybrid] 双列对照

# 5) 本地真 cross-encoder 重排（可选；首次下载 BAAI/bge-reranker-v2-m3）
$env:RERANKER="cross"
python eval.py

# 6) 引用落库：检索 top 块 → 拼带编号引用 prompt → LLM 生成 → 引用写回 w06rag.answers
$env:SCHEME="hybrid"
$env:Q="扣非净利润和归母净利润有什么区别"
python generate.py
#   预期：打印 top5 引用块 + LLM 答案；w06rag.answers 表写入 (query, answer, cited_chunk_ids, scheme)
#   沙箱无 Key 时只打印 BM25-only 的 top 块预览，不调 LLM
```

## 排错
- `python` 是 3.8.6 / `import jieba` 失败：bat 的 `PYTHON_HOME` 没指向 venv Scripts，改 bat 第57行 `set "PYTHON_HOME=C:\Users\amber\.workbuddy\binaries\python\envs\default\Scripts"`。
- `Hybrid 自动跳过`（只跑 BM25-only）：API_KEY/BASE_URL 没加载——确认是在 **bat 启动的 PowerShell 子进程**里跑，不是另开一个 PS 窗口。
- `connection refused (127.0.0.1:5432)`：gp17 容器没起，`docker ps` 看是否在跑（已建库则只需 `docker start gp17`）。
- `password authentication failed for user "amber"`：上面 `PG_PASSWORD` 与 gp17 实际密码不符，改成真实值。
- `No module named sentence_transformers`（第5步）：先 `pip install sentence-transformers`。
- 真重排慢/机器带不动：去掉 `$env:RERANKER="cross"` 回到 lexical fallback（演示流程，非真 cross-encoder）。
