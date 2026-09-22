# W06 · RAG 完整链路：从"纯向量翻车"到"混合检索 + 重排 + 引用"

> Agent 开发实战 15 周 · 第 6 周 · 实际投入约 14 小时（含阶段1 六小节引导、三方案对比、真 cross-encoder 验证、收尾写作）
>
> 一句话钩子：**W05 你把"取数"跑通了——但那条路只认"意思近不近"。一上真实财报语料就会发现：查"扣非净利润"它给你"归母净利润"，查"INV-2024-001"它给你"INV-2024-002"。这周我们把它修成一条能打的完整链路。**

另有一份 [学习对话实录](DIALOGUE.md)：这周完整的引导过程 + 一套可直接丢给 AI 的**复现脚本**。还有 [逐轮一问一答底稿](DIALOGUE-QA.md)：每一次提问、回答、终端输出原样保留。

## 开篇：这周要解决什么问题

W05 你验证了向量检索强在"语义邻居"——"退款"和"退货"能认出来。但有个系统性盲区：**dense-only 在企业/技术语料上的 `Recall@10` 只有约 0.58–0.65**，混合检索（向量+BM25）能拉到 0.72–0.85（2026 多篇生产 RAG 文章一致结论）。

为什么会翻车？四类场景：

| 失效场景 | 为什么向量抓不准 | 财报里的真实例子 |
|---|---|---|
| ① 专有名词/模型名 | "Sonnet 3.7" 和 "Opus 4" 语义环境几乎一样，向量当邻居 | 要"扣非净利润"召回了"归母净利润" |
| ② 编码/标识符 | "INV-2024-001" 和 "002" 只在极小子空间差异 | 发票号、SKU、错误码、commit hash |
| ③ 罕见/领域术语 | 训练少见的词 embedding 校准差 | "TPMS 传感器重新标定"召回泛化文档 |
| ④ 否定与对比 | 负关系没被线性编码 | "**避免**内存泄漏"和"**检测**内存泄漏"向量几乎一样 |

技术文档 / 合同 / 财务 / 工单类语料里，**精确匹配类查询占真实流量的 20–40%**。只做向量 = 这部分系统性翻车。

> **PHP/Laravel 类比**：你用 MySQL `MATCH(content) AGAINST('退款')`（全文检索，本质是 lexical 的 BM25 思路）能**精确命中"退款"二字**，但遇到"把钱退回来"这种换说法就抓不到。向量检索正好**反过来**。两者互补，不是替代——就像你后台为同一个筛选条件**并发跑两条 SQL**：一条按语义（向量）、一条按精确关键词（`MATCH...AGAINST`），各 `LIMIT 20`，`UNION` 合并去重交给重排。

## 核心结论（先给答案）

1. **纯向量有"词法盲区"**：专有名词/编号/标识符类查询系统性翻车；BM25 互补，不是替代。财报里"扣非/归母"这种 token 不同的相近词，BM25 能分，向量反而当邻居。
2. **RRF 融合按排名不看分数**：余弦（0~1）和 BM25（无界）量纲不同，直接加分会被一路碾压；RRF 用 `1/(k+rank)` 消量纲、抬共识，`k` 默认 60。
3. **Cross-encoder 重排准但贵**：bi-encoder 各自编码、cross-encoder 把 query+doc 拼一起逐字 attention；只对融合后前 K 篇跑（K=20 甜点）。**但本机 CPU 跑 `bge-reranker-v2-m3` 实测 23 秒/query，生产 GPU 上才约 +100ms——差 ~230 倍。**
4. **检索层救不了"语义相近块"**：都讲"转股价"的两块，BM25（被共享 token 带偏）/ Dense（被共享语义带偏）/ 真 cross-encoder（只把目标从 #3 提到 #2）**三路都分不出优先级**。唯一解是入库时做"字段级归一化"（W09 毕业项目"零误匹配"验收的命门）。
5. **引用落库是 RAG 可信的第一步**：取 top 块当引用编号喂 LLM，答案每句可溯源，再写回库。

---

## 一、概念：四个部件各自干啥

### 1.1 BM25 到底怎么算分（阶段1 第2节公式）

BM25 是"词袋（bag-of-words）"排序函数——只看词出现几次、在多少文档出现、文档多长，**完全不理解意思**。正因为"不懂意思"，它**脆但极准**。

```
score(D, Q) = Σ  IDF(qᵢ) · [ f(qᵢ,D)·(k1+1) ] / [ f(qᵢ,D) + k1·(1 - b + b·|D|/avgdl) ]
             每个查询词
```

| 部件 | 干的事 | 财报直觉 |
|---|---|---|
| `IDF(qᵢ)` | 越罕见的词权重越高；满篇都有的词（"公司"）权重≈0 | "扣非"在全库只出现几次 → 权重爆炸高 |
| `f·(k1+1)/(...)` | 词频饱和（边际递减，非线性） | 防某文档把"营收"刷 100 遍霸榜 |
| `b` + `|D|/avgdl` | 长度归一，长文档轻微罚分 | 年报块长短差异大，`b` 更该调 |

> **PHP/SQL 类比**：你 MySQL 的 `MATCH(content) AGAINST('扣非')` 和 BM25 **同源**（TF-IDF / BM25 同族）。区别只是 MySQL 把它封装成内置函数。所以你"没用过向量库"也完全不影响理解——**BM25 就是你一直在用的全文检索的精确数学版**。

### 1.2 多路召回 + RRF 融合（阶段1 第3/4节）

```
query ──┬─ Dense 路：query→embedding→pgvector 余弦 top_k → 有序列表 A
        └─ Sparse 路：query→分词→BM25 打分 top_k        → 有序列表 B
合并：A ∪ B（按 chunk id 去重）→ 候选集（各 top20，合并约 30~40 唯一块）
```

**为什么不能直接把两路分数相加**：Dense 余弦（0~1）和 BM25（无界，可能 18.4）量纲不同，直接加 BM25 会碾压全场，混合退化成纯 BM25。

**RRF（Reciprocal Rank Fusion，Cormack 2009）**：完全不看原始分数，只看排名：

```
fused(d) = Σ  1 / (k + rank_i(d) + 1)      # rank 0-based；k 默认 60
           每条路 i
```

排名第 1 贡献 `1/61`，第 2 贡献 `1/62`……越靠后越小，两路独立相加。文档 `d5` 在 Dense 排 #3、BM25 排 #2 → 融合后冲到前面（共识 > 单路极值）。

> **PHP/SQL 类比**：RRF 就是"**按名次投票，不按分数**"。两位面试官（语义面 + 关键词面）各排个序，录用不是把两人评分相加（面试 B 打 18.4 分会失真），而是"**两路都排前面的优先**"。

### 1.3 Cross-encoder 重排（阶段1 第6节）

| | bi-encoder（W05 用的） | cross-encoder（W06 新增） |
|---|---|---|
| 编码 | query、doc **各自独立** encode 成向量 | query + doc **拼一起**喂同一个 transformer |
| 交互 | 只有最后点积，**无真正词间注意力** | query 和 doc **每个 token 互相 attention** |
| 成本 | doc 向量可**预计算**存库，查询只算 query | **每次 query+doc 实时跑**，无法预存 |
| 位置 | 海量语料**初召回** | 候选集**精排**（只跑前 20~50） |

代价账：cross-encoder 不能对全库跑，只对 RRF 融合后前 K 篇重排（K=20 甜点）。2026 生产数据：rerank 20 篇 GPU 上约 **+80~120ms**，把 `Recall@10`/`MRR@10` 再抬 5~10 个点。

---

## 二、动手：从零搭完整链路

### 2.1 建语料（财报/可转债风格，故意埋相近词）

阶段1 你拍板用 B 方案：**建一份财报/可转债风格小语料**，让"专有名词相近"失效自然暴露。6 篇（指标定义 / 赎回与回售条款 / 转股价与下修 / 年报片段 / 信用评级与担保 / 票面利率与期限），递归切分(400/80) 后成 **9 个 chunk**——关键是把"扣非/归母""赎回/回售""下修/转股价"这些相近词**落到不同 chunk**（详见踩坑1）。

```python
# corpus.py（节选）：加载语料 + 递归切分
def load_chunks(corpus_dir):
    chunks = []
    for md in sorted(glob.glob(os.path.join(corpus_dir, "*.md"))):
        doc_id = os.path.basename(md)[:-3]
        text = open(md, encoding="utf-8").read()
        for i, piece in enumerate(recursive_split(text, 400, 80)):
            chunks.append({"id": f"{doc_id}#{i+1}", "doc_id": doc_id, "content": piece})
    return chunks
```

### 2.2 BM25 手搓（不依赖 rank_bm25，看清公式）

```python
# bm25.py（节选）：Okapi BM25 核心评分循环
def search(self, query, top_k=20):
    q = self._tok(query)                       # jieba 分词；中文"扣非净利润"必须分到词级
    out = []
    for i, d in enumerate(self.docs):
        dl = len(d)
        freq = {}
        for t in d: freq[t] = freq.get(t, 0) + 1
        score = 0.0
        for t in q:
            if t not in self.idf: continue
            f = freq.get(t, 0)
            if f == 0: continue
            # IDF · 词频饱和(k1) · 长度归一(b)
            score += self.idf[t] * (f * (self.k1 + 1)) / (
                f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
        out.append((self.chunks[i]["id"], score))
    out.sort(key=lambda x: -x[1])
    return out[:top_k]
```

**关键**：中文"扣非净利润"和"归母净利润"共享"净利润"三字，必须分词到**词级**，BM25 才能把这两个 token 当不同词分开——这正是第①类失效的命门。

### 2.3 RRF 融合（按排名，不看分数）

```python
# rrf.py
def rrf_fuse(ranked_lists, k=60, top=40):
    fused = {}
    for rl in ranked_lists:
        for rank, (cid, _) in enumerate(rl):
            fused[cid] = fused.get(cid, 0.0) + 1.0 / (k + rank + 1)
    return sorted(fused.items(), key=lambda x: -x[1])[:top]
```

### 2.4 Dense 路复用 W05（Key 门控）

```python
# dense.py（节选）：百炼 embedding + pgvector 余弦检索
def embed(text):
    return _client_get().embeddings.create(
        model="qwen3.7-text-embedding-flash", input=[text], dimensions=1024
    ).data[0].embedding

def search(query, top_k=40):
    qvec = embed(query)
    conn = psycopg2.connect(**PG)
    cur.execute("SELECT id, 1-(embedding <=> %s) AS sim FROM chunks "
                "ORDER BY embedding <=> %s LIMIT %s", (str(qvec), str(qvec), top_k))
    return [(rid, float(sim)) for rid, sim in cur.fetchall()]
```

### 2.5 Cross-encoder 重排（双模式：真模型 / lexical fallback）

```python
# rerank.py（节选）：真 cross-encoder 缓存为单例，避免 30 题加载 30 次
_CE_MODEL = None
def _get_ce():
    global _CE_MODEL
    if _CE_MODEL is None:
        from sentence_transformers import CrossEncoder
        _CE_MODEL = CrossEncoder("BAAI/bge-reranker-v2-m3")   # 首次下载权重约 2.2GB
    return _CE_MODEL

def rerank(query, candidates, top_k=8):
    if available():                                        # RERANKER=cross 且装了 sentence-transformers
        _ce = _get_ce()
        scores = _ce.predict([(query, c) for _, c in candidates])
        ranked = sorted(zip([cid for cid, _ in candidates], scores), key=lambda x: -x[1])
        return [(cid, float(s)) for cid, s in ranked[:top_k]]
    # lexical fallback：候选子集上重算 BM25，仅演示流程，非真 cross-encoder
    from bm25 import BM25
    bm = BM25(); bm.fit([{"id": cid, "content": c} for cid, c in candidates])
    return bm.search(query, top_k=top_k)
```

### 2.6 引用落库（RAG 可信的第一步）

取融合后 top-k 块拼成带编号引用的 prompt 喂 LLM，答案末尾标 `[1][2]`，再把引用块 id 写回 `w06rag.answers`。

```python
# generate.py（节选）
def build_prompt(query, chunks_kv):
    body = ""
    for i, (cid, c) in enumerate(chunks_kv, 1):
        body += f"\n[{i}] ({cid})\n{c}"
    usr = f"{query}\n\n回答末尾用 [1][2] 标注引用了哪些片段编号。"
    return sys_p, body, usr

def save_answer(query, answer, cited):
    # CREATE TABLE answers(query, answer, cited_chunk_ids, scheme, created_at)
    # INSERT ... 引用落库
```

> **跑通实录**：本机 `python generate.py`（bat 已加载 Key + 已灌库）即生成带引用答案并落库。沙箱无 Key 时退化为预览 top 块，不调 LLM。

---

## 三、踩坑记录（5 条，均有实证）

### 坑 1：语料太小 → 相近词同块 → 判别力探针误报"混淆"

- **现象**：最初 6 篇每篇 <400 字，递归切分后**每篇只有 1 个 chunk**，"扣非净利润"和"归母净利润"被切进同一个块。判别力探针自然显示"混淆"（两个词在同一块里，rank 都是 #1）。
- **真因**：相近专有名词要能被检索分开，**必须落在不同 chunk 里**。一块同时含两个词，BM25 无法区分。
- **解法**：把每篇写大，让相近词落到不同 chunk → 9 个 chunk（扣非→`指标定义#1`、归母→`#2`；赎回→`#1`、回售→`#2`）。重跑探针，#1/#2 正确分离。

### 坑 2：判别力探针初版用"子串 in 块"误判

- **现象**：探针写"目标块含'扣非净利润'则算命中"，但 `指标定义#1`（扣非块）的解释里写了"扣非净利润 = 归母净利润 − 非经常性损益"，"归母净利润"子串也出现 → 误判为"混淆"。
- **真因**：子串判断分不清"块本身是讲扣非"还是"块里顺带提到归母"。
- **解法**：改成**直接比目标块 vs 干扰块的排名**（`rank[tgt] < rank[dis]` 才算分离）。修正后三列探针逻辑正确。

### 坑 3：gp17 容器建库——`role "postgres" does not exist` + `database "amber" does not exist`

- **现象**：`docker exec -i gp17 psql -U postgres ...` 报角色不存在；改 `psql -U amber` 又报库"amber"不存在。
- **真因**：gp17 容器管理员即 `amber`（建容器时设了 `POSTGRES_USER=amber`），**没有 postgres 角色**；`psql -U amber` 没指定 `-d`，默认连同名库 `amber`，该库不存在 → 连接阶段失败，`CREATE DATABASE` 根本没执行。
- **解法**：用系统模板库 `template1` 当跳板：`psql -U amber -d template1 -c "CREATE DATABASE w06rag OWNER amber;"`。建库脚本 `00_start_pgvector.sh` 同步补 `-d template1` 跳板。

### 坑 4：bat 的 PYTHON_HOME 为空 → `import jieba` 失败

- **现象**：`start-env-windows.bat` 启动的 PS 里 `python` 走系统 3.8.6（无 jieba），跑 `eval.py` 直接 `ModuleNotFoundError: No module named 'jieba'`；本机 `pip install jieba` 又因连 pypi.org 报 SSL EOF 装不上。
- **真因**：bat 第 57 行 `PYTHON_HOME` 为空，没指向含 jieba 的 managed venv；本机网络 TLS 中断导致 pypi 装包走不通。
- **解法**：**在沙箱用 managed venv 的 pip 代装** `jieba + numpy + openai + psycopg2 + sentence-transformers`（装的是本机文件，本机直接受益）。bat 的 `PYTHON_HOME` 改为 `C:\Users\amber\.workbuddy\binaries\python\envs\default\Scripts`。本机零网络装包即跑通。

### 坑 5：真 cross-encoder 的成本认知——"GPU +100ms" 和 "CPU 23秒" 差 230 倍

- **现象**：阶段1 第6节我引了生产基线"rerank 20 篇 +80~120ms"，但实际本机 CPU 跑 `bge-reranker-v2-m3`：30 题花了约 11 分钟，**平均 22996.9ms/query**。而且真重排的 `MRR@10=0.983` **等于** lexical fallback、**低于** Hybrid(RRF) 的 1.000。
- **真因**："+100ms"是 **GPU 推理延迟**；CPU 无 GPU 跑大模型差 ~230 倍。且 9 块小语料上，RRF 已把 expected 排得很好（MRR 1.000），cross-encoder 重排的"洗牌"噪声 > 信号增益——重排价值在**几百~几千候选**的大语料才显著（生产文章说的 +5~10pt 是那个场景）。
- **解法**：成本表把"GPU +100ms"和"本机 CPU ~23s"**并列标注**，不误导；W09 毕业项目部署成本决策要清醒（要么上 GPU、要么换轻量 reranker、要么靠字段级归一化兜底）。

---

## 四、验收清单（对照 CURRICULUM）

| 验收项 | 状态 | 证据 |
|---|---|---|
| 有一张自己跑出来的对比数据表 | ✅ | 三方案 Recall@10 / MRR@10 / 延迟表（下方第五节） |
| 能说清"多花的重排成本换了多少准确率" | ✅ | 成本账：+23s/query(CPU) vs GPU 100ms；小语料 MRR 未提升、大语料 +5~10pt |
| 加 BM25 通路做 RRF 融合 | ✅ | `rrf_fuse` 按排名融合，三方案对比 |
| 30 题测试集对比三方案 | ✅ | `testset.json` 30 题（exact_token/semantic/question/antonym 四类） |
| 答案带引用出处 | ✅ | `generate.py` 取 top 块拼 `[1][2]` 引用 + 落库 `w06rag.answers` |
| **Query 改写落地代码** | ⚠️ 未做 | 阶段1 第5节只讲了概念（轻量版：解指代+关键词提取），代码未实现，留 W07 |

> 诚实标注：CURRICULUM 写"Query 改写 → 多路召回 → RRF → Rerank → 拼上下文 → 生成 → 引用"。本周落地了**多路召回 + RRF + Rerank + 引用落库**；**Query 改写**仅讲了原理、未写代码（判定为"需要时再加"，非空喊完成）。

---

## 五、数据 / 实测结果

所有数字来自 amber 本机真实运行（Python 3.13，百炼 `qwen3.7-text-embedding-flash` 1024维，Docker pgvector:pg17，gp17 容器 `w06rag` 库）。

### 5.1 三方案对比（9 chunks / 30 题）

| 方案 | Recall@10 | MRR@10 | 延迟/query | 说明 |
|---|---|---|---|---|
| **BM25-only** | 1.000 | 0.983 | 0.2 ms | 词法，无 API 调用 |
| **Hybrid(RRF)** | 1.000 | **1.000** | ~290 ms | + 百炼 embed 网络延迟 |
| **Hybrid+Rerank（真 cross-encoder）** | 1.000 | 0.983 | **22996.9 ms（CPU）** | + 本地 `bge-reranker-v2-m3` 推理 |

分类型 Recall@10 三方案全 1.000（exact_token 12/12 · semantic 8/8 · question 6/6 · antonym 4/4）——**这是小语料天花板**：9 个 chunk、top10 必含全部块，Recall 区分不出方案优劣。真实区分力在 **MRR@10** 与**判别力探针**。

### 5.2 判别力探针（相近专有名词能否被检索分开）—— 三路对照

| 探针 | [BM25] | [Hybrid] | [Rerank] | 结论 |
|---|---|---|---|---|
| 扣非净利润（目标`指标定义#1` / 干扰`指标定义#2`） | ✅ #1/#3 | ✅ #1/#3 | ✅ #1/#2 | token 不同，三路都分得出 |
| 赎回条款（目标`赎回与回售条款#1` / 干扰`#2`） | ✅ #1/#2 | ✅ #1/#2 | ✅ #1/#2 | token 不同，三路都分得出 |
| **下修条款（目标`转股价与下修#2` / 干扰`#1`）** | ❌ #3/#1 | ❌ #3/#1 | ❌ #2/#1 | **三路都没分离** |

**诚实修正（我阶段1 两次预测"Hybrid 翻盘"被打脸）**：

- 两块（`转股价与下修#1` 讲"转股价+下修触发条件"、`#2` 讲"下修流程"）语义环境都围绕"转股价"，bi-encoder 给的向量距离同样近 → Dense 也分不清。
- BM25 被共享 token"转股价"带偏，Dense 被共享语义带偏，**两路都救不了**。
- 真 cross-encoder 确实"看见"了 #2 含"下修"，把目标从 #3 提到 #2，但干扰块 #1（"当股价低于转股价 85% 触发**下修条款**"）也含"下修"且和"转股价"强绑定，仍排 #1 —— **仍是 ❌，只是部分缓解**。

→ **结论**：语义高度相似的块，检索层（BM25/Dense/RRF）+ 重排层（真 cross-encoder）**三道防线全失效**，唯一解是入库时做"**字段级归一化**"（把 `metric=下修 / 转股价` 抽成结构化字段，比字段相等而非文本相似）。这正是 W09 毕业项目"**扣非/归母零误匹配**"验收的命门。

### 5.3 成本账（验收核心：多花的重排成本换了多少准确率）

| 维度 | 本机实测（CPU 无 GPU） | 生产基线（GPU） | 说明 |
|---|---|---|---|
| rerank 20 篇延迟 | **22996.9 ms/query（≈23s）** | +80~120 ms | 差 ~230 倍 |
| MRR 增益（9 块小语料） | 0（真重排 0.983 = Hybrid 1.000 反降） | 大语料 +5~10pt | 重排价值在大语料才显著 |
| 部署成本 | CPU 跑不动生产 | 需 GPU / 轻量 reranker | W09 决策点 |

> 关键认知：**"多花的重排成本"在本机小语料上没换来准确率**（MRR 反而略降）；真 cross-encoder 的价值在候选集几百~几千、质量参差时才释放。所以生产选型不能只看"加个 reranker"，要先看语料规模与硬件。

---

## 六、这周的取舍

### 做了什么

- 阶段1 六小节全讲透（纯向量翻车 / BM25 公式 / 多路召回 / RRF 融合 / Query 改写 / Cross-encoder 重排），每节停下等反馈、用 PHP/SQL 类比打底。
- 阶段2 实操跑通：财报风格语料（9 chunks）+ 手搓 BM25 + RRF 融合 + 复用 W05 Dense（百炼+pgvector）+ 真 cross-encoder 重排（双模式，单例缓存）+ 三方案评测 + 判别力探针（三列）+ 引用落库。
- 真 cross-encoder 本机验证（装 `sentence-transformers`，首次下载 2.2GB 权重），拿到 CPU 23s/query 的真实成本。

### 放弃了什么 / 留到后面

- **Query 改写代码**：阶段1 第5节只讲概念（轻量版：解指代+关键词提取；多轮里"指代+问句"常同现，需两个动作串联），代码未实现，**留 W07**。HyDE 也留 W07。
- **语义切分（semantic splitting）**：最准但最贵，W07 再碰。
- **字段级归一化**：检索+重排三层都救不了语义相似块，唯一兜底在"入库时结构化字段"——这是 **W09 毕业项目验收"零误匹配"的核心**，本周只埋伏笔。
- **真 cross-encoder 生产化**：本机 CPU 太慢（23s/query），生产要么上 GPU、要么换 `ms-marco-MiniLM` 级轻量 reranker。本周用真模型验证了"重排层也救不了语义相似块"，但部署方案留待毕业项目决策。

### 一个方法论提醒

我们联网核对了 2026 年 RAG 生产实践（向量 + BM25 + RRF + Cross-encoder 是默认架构），确认 W06 内容未过时。但**生产数字（Recall 0.72–0.85、rerank +100ms）是"大语料 + GPU"场景**；小语料（9 块）+ CPU 实测会颠覆其中部分结论（Recall 全 1.000 是天花板、CPU 23s 是硬件现实），正文已如实区分，不拿基线当自己语料的真值。

---

## 下一篇

W07 讲 **进阶 RAG**——把未落地的 Query 改写做成代码（HyDE、指代消解）、啃复杂 PDF（表格密集、跨页、OCR）、父子分段（small-to-big）、上下文压缩、GraphRAG 了解。那套"真 cross-encoder 在 CPU 太慢"的痛点，W07 会用"先扩展查询再检索""上下文压缩减少候选"来缓解，但根治仍在 W09 的字段级归一化。

> 本周尾巴：Query 改写代码（W07）；语义切分（W07）；真 cross-encoder 生产化（GPU/轻量模型，毕业项目决策）；字段级归一化（W09）。

## 附录：学习对话实录

- [DIALOGUE.md](DIALOGUE.md) —— 提炼版：按主题归类，含「给 AI 的复现指令」，可直接复制给任意 AI 带你走一遍
- [DIALOGUE-QA.md](DIALOGUE-QA.md) —— 逐轮一问一答底稿：保留每一次提问、回答与终端输出

## 附录：延伸阅读

- [pgvector GitHub](https://github.com/pgvector/pgvector) —— HNSW / 运算符族 / 维度上限
- [阿里云百炼 Embedding 文档](https://help.aliyun.com/zh/model-studio/embeddings) —— `qwen3.7-text-embedding-flash` 维度/批次/价格
- [BAAI/bge-reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3) —— 真 cross-encoder 重排模型
- 2026 实践：中文 RAG 默认架构 = 向量 + BM25 + RRF + Cross-encoder；Recall@10 从 dense-only 0.58–0.65 提升到混合 0.72–0.85

---

## 发布检查

- [x] 代码实际跑过，输出贴进正文（三方案 + 探针三列 + 23s/query 真实延迟）
- [x] 至少 2 条真实踩坑（实际 5 条：语料太小/探针子串误判/gp17建库/ bat PYTHON_HOME/CPU 23s vs GPU 100ms）
- [x] 有数字/表格（三方案 Recall/MRR/延迟；探针三列；CPU vs GPU 成本账）
- [x] 有 PHP / SQL 类比（MATCH...AGAINST 同源 / UNION 多路召回 / 按名次投票）
- [x] 标题不标题党，但要有信息量
- [x] 结尾有引导（下一篇 / 仓库链接）
- [x] 本周写了 `DIALOGUE.md`（对话实录 + 可复现的 AI 引导脚本）
- [x] 本周写了 `DIALOGUE-QA.md`（逐轮问答底稿，只收技术相关）
- [x] Query 改写未落地代码一事诚实披露（留 W07），未假装本周完成
- [x] 真 cross-encoder MRR 反降、CPU 23s 等反直觉结果如实记录，未只报漂亮数字

### 提交前必做：红线扫描（含全部文件类型）

```bash
grep -rlE "dd-admin|dd-api|ddLife|hope-garden|病历|CatchAdmin|dd_permissions" . \
  --include="*.md" --include="*.py" --include="*.json" --include="*.bat" --include="*.sh"
grep -rn "sk-" . --include="*.json" --include="*.py" --include="*.md"
```

- [ ] 红线扫描覆盖了 `.md` `.py` `.json` `.bat` `.sh`
- [ ] 无 `sk-` 开头的 Key 出现在任何待提交文件里
- [ ] `.bat` 是 CRLF，其余文件是 LF
