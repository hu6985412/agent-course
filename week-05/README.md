# W05 · Embedding 与向量检索：RAG 的"取数"环节

> Agent 开发实战 15 周 · 第 5 周 · 实际投入约 11 小时（含 endpoint 选型曲折、切分实验、bad case 修正）
>
> 一句话钩子：**W04 我们把"记忆三层"的外部存储从一个退款 Agent 的临时结果，升级成了"可跨会话检索的知识库"。这一周，我们正式进入 RAG 的"取数"环节——把文本变成向量、存进数据库、再按语义查回来。**

**另有一份 [学习对话实录](DIALOGUE.md)**：这周的完整学习过程，包括 endpoint 选型的反复、被真实数据"教育"的地方，以及一套可以直接丢给 AI 的**引导脚本**——照着它能用同样的方式带你走一遍。

## 开篇：这周要解决什么问题

W04 的 Agent 跑完一趟，工具结果落进 `steps` 表，但那只是"单次任务的临时记忆"。真正实用的知识库，得能**跨会话**把"退款政策第几段写了什么"这种知识存下来，用户问"退款多久到账"时，精准捞回那段。

这就是 RAG（Retrieval-Augmented Generation）的"R"——检索。而检索的前提是：**把文本变成可以比"近不近"的数字**。这周不碰 LLM 生成，只把"取数"这一层从概念到代码跑通。

四个要搞懂的概念：① Embedding 是什么 ② 余弦相似度为什么用 ③ 切分策略 ④ 向量库选型与索引。然后动手：Docker 起 pgvector、递归切分、调百炼 embedding、写余弦检索 SQL、亲手调参观察召回。

## 核心结论（先给答案）

1. **Embedding 把"意思"编码成定长浮点数组**。相似输入→相似向量，相当于一个"对语义敏感的哈希"——和 `md5` 故意让相似输入离散（雪崩效应）正好相反，Embedding 是"相似输入落在连续空间里相近的坐标"。
2. **向量检索用余弦相似度，不用欧氏距离**。Embedding 的向量模长不代表任何语义，余弦只比方向、忽略长度，天然免疫"一长一短同义句被判不相关"的坑。pgvector 运算符 `<=>` 就是余弦距离，**越小越像**。
3. **切分是召回质量的头号开关**：太大→多话题平均后不准、给 LLM 噪音多；太小→脱离上下文、易劈句、块太多易被挤出 top_k。**没有一刀切的 chunk size**，适中切分 + 合理 overlap（如 400/80）是稳健默认，但应按文档和查询类型调。
4. **向量库选 pgvector**——向量就是表里一列，能 `JOIN` 业务表、带 `WHERE` 混合过滤，复用你全部 SQL 能力（这是相对专用向量库的核心优势）。索引默认 **HNSW**（快、召回高、少改数据）。

---

## 一、Embedding：把"意思"变成一串数字

先想你最熟的：**MySQL 全文检索** `MATCH(content) AGAINST('退款')`。它的本质缺陷是**字面匹配**——只有当文档里真出现了"退款"这两个字才命中。"把钱退回来""我不想要了想退货"这些**意思一样但用词不同**的句子，全文检索一个都捞不到。这正是 RAG 要解决的"语义"问题。

**Embedding 干的事，就是给"意思"编码成数字。**

一句话 → 一个固定长度的浮点数组（也叫**向量 / vector**）。比如百炼 `qwen3.7-text-embedding-flash` 输出 **1024 个数字**，OpenAI `text-embedding-3-small` 输出 1536 个。关键性质：**意思相近的句子，向量也相近；意思不沾边的，向量差很远**。

**为什么模型能学会"语义"？** 核心假设叫 *distributional hypothesis*（"观其伴而知其义"）：一个词的意思由它常出现的上下文决定。"苹果手机"和"iPhone"总出现在差不多的句子里，训练后向量自然靠近——不是规则硬编，是统计出来的。

> **PHP/Laravel 类比**：你写推荐系统时，会给用户建"兴趣特征向量" `[爱运动, 爱科技, 价格敏感, ...]` 算相似度。Embedding 就是**模型自动学会的"语义特征向量"**——只是维度不是你手定，是模型从海量语料学出来的。
> 反差类比：`md5($text)` 也是"文本→定长串"，但哈希**故意让相似输入得到完全不同结果**（雪崩效应）。Embedding 正好反过来——**相似输入得到相似向量**，相当于一个"对语义敏感的哈希"，只不过落在连续空间里。

## 二、余弦相似度：只比方向，忽略模长

两个向量都是 Float 数组，怎么算"近"？三种常见度量：

| 度量 | 看什么 | pgvector 运算符 | 直觉 |
|---|---|---|---|
| **余弦 cosine** | 两向量的**夹角/方向** | `<=>`（距离 = 1−相似度） | "朝同一方向"=相似 |
| 欧氏距离 L2 | 两点间**直线距离** | `<->` | "物理位置近"=相似 |
| 点积 inner product | 方向+长度一起算 | `<#>` | 长度也参与 |

**本课重点 + 坑：Embedding 检索几乎都用余弦，不用欧氏距离。** 因为你那串 1024 个数字的**"长度"（模长）通常不代表任何语义**——模型输出有的长有的短，纯粹是归一化与否造成的。余弦相似度**只比方向、忽略长度**，正好把这件没意义的事刨掉。

具体例子（2 维方便看）：

```
a = (0.8, 0.6)      → 模长 |a| = 1.0
b = (0.4, 0.3)      → 模长 |b| = 0.5   （b 正好是 a 的一半，方向一模一样）
```

- **余弦**：`(0.8×0.4 + 0.6×0.3) / (1.0 × 0.5) = 0.5 / 0.5 = 1.0` → 相似度满分，意为"等价"。
- **欧氏距离**：`√((0.8−0.4)² + (0.6−0.3)²) = 0.5` → 它说"离得挺远"。

同一个意思，欧氏距离却说"远"。**这就是坑**：用欧氏距离，一句长一句短的同义句会被判"不相关"。余弦只看方向，天然免疫。

> 给你推荐系统角度的对齐：你算"用户 A 和用户 B 兴趣像不像"，用的也是余弦（把评分向量归一后比方向），不是比绝对打了多少分。所以你的直觉方向对——只是 Embedding 场景里"向量长度"比推荐系统里**更没意义**，余弦是默认且最稳的选择。

落到 pgvector 的 SQL（本周全程用它）：

```sql
-- 查和用户问题最相似的 5 个文档块
SELECT id, content,
       1 - (embedding <=> :query_vec) AS similarity   -- 1 - 余弦距离 = 余弦相似度
FROM chunks
ORDER BY embedding <=> :query_vec                     -- <=> 余弦距离，越小越像
LIMIT 5;
```

`similarity` 范围约 `[-1, 1]`，归一化后模型通常在 `[0, 1]`，越接近 1 越像。

## 三、切分策略（chunk / overlap）：召回质量的头号开关

为什么不能直接把整篇文档丢进 Embedding？① 模型有上下文上限（百炼单行最大 128000 token，但一篇手册几万字，块太大仍稀释语义）；② 一个向量若代表"整本书"，是整本书的"平均意思"，具体某句话被稀释。所以必须切成 **chunk（块）**。

| 切太大 | 切太小 |
|---|---|
| 一个向量混了多个话题，"平均"后哪个都不准 | 单句脱离上下文，产生歧义（"它"指啥？） |
| 召回后塞给 LLM 的噪音多、token 贵 | 块太多，排序压力大，相关块可能被挤到 top_k 之外 |
| 反例：把整章当一块 | 反例：按句号每句一块 |

**四种切分策略**：

| 策略 | 做法 | PHP 类比 |
|---|---|---|
| **固定 fixed** | 每 N 字符/token 一刀切 | `chunk_split($text, 500)`——dumb 但可预测，不管语义边界 |
| **递归 recursive** | 按分隔符优先级：`\n\n`→`\n`→`。`→`！`→`？`→`；`→`，`→空格 | 递归下降解析：优先在大边界断开，断不开再退而求其次 |
| **按结构 structure** | 按 Markdown 标题/代码块/JSON 顶层键/表格行切 | 按 `<h2>` 或 JSON 的 key 把大对象拆成记录，保留层级 |
| **语义 semantic** | 用 Embedding 判断"话题是否变了"再切 | 先对每段算相似度，相似度骤降处才下刀——最准但最贵 |

**overlap（重叠）**：相邻块故意重叠一部分（通常块大小的 10%~20%）。否则若一句话正好卡在块边界被劈成两半，embedding 两半都不完整，检索时这条信息就"丢了"。overlap 让边界句在前后两块都完整出现一次；代价是存储和检索量翻倍。

> **最贴的 PHP 类比**：overlap 就是**滑动窗口（sliding window）**。你做时间序列移动平均时，窗口每次往前挪一格、和上一个窗口共享大部分数据点——chunk overlap 一模一样，只是挪的是"文本窗口"。

**实践结论**：规范 Markdown 用 structure 能保住层级语义；但 recursive 是**默认首选**——它在没有清晰结构边界时（纯文本/长段落）按分隔符逐级退让，是"结构优先、结构缺失时兜底"的最稳策略。本周代码用 recursive + overlap=80。

## 四、向量库选型 + HNSW vs IVFFlat 索引

**为什么需要索引**：朴素检索是"把用户问题向量和库里每个向量算一遍余弦"——暴力扫描 O(N×D)。100 万条 × 1024 维，每次查询要算 10 亿次乘法，慢到不可用。索引的作用就是**跳过明显不可能的候选**，把查询从"全表扫"变成"走索引"。

| 库 | 形态 | 强项 | 课程选否 |
|---|---|---|---|
| **pgvector** | Postgres 扩展，向量就是表里一列 | 向量检索写成一条 SQL，能 `JOIN` 业务表、带 `WHERE` 过滤 | ✅ 选（贴合 SQL 背景，Docker 起即跑） |
| **Qdrant** | Rust 专用向量库，独立 HTTP API | 性能极致、过滤语法强、生产规模首选 | 进阶可选 |
| **Chroma** | Python 原生 embedded | 单机原型最快，代码最少 | 实验可选 |

> **PHP/SQL 类比**：pgvector 就像给 MySQL 加了个 `VECTOR` 列类型和 `<=>` 运算符——你已有的全部 SQL 能力（连表、过滤、事务）直接复用，不用再学一套新系统的心智模型。这正是课程选它的原因。

**两种索引（pgvector 都支持）**：

- **HNSW**（Hierarchical Navigable Small World，多层图）：把向量建成"高速路网"，查询从顶层入口贪心下降到底层，跳过绝大多数节点。快、召回高，但建索引吃内存、删改成本高（常需重建）。适合**少改动、查询频繁**的数据。
- **IVFFlat**（Inverted File Flat，倒排聚类）：先聚类成 K 个簇，查询只扫最近几个簇。插入友好，但召回略低，需手调 `lists`/`probes`。

| | HNSW | IVFFlat |
|---|---|---|
| 查询速度 | 快（对数级） | 中（取决于 probes） |
| 召回率 | 高 | 中（调得好接近 HNSW） |
| 删/改成本 | 高（常需重建） | 低（新向量直接归簇） |
| 参数 | 少（`m`/`ef`） | 多（`lists`/`probes`） |
| 适合 | 文档灌完基本不变 | 持续写入、内存紧 |

```sql
CREATE INDEX ON chunks USING hnsw (embedding vector_cosine_ops);   -- HNSW（生产默认）
-- CREATE INDEX ON chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);  -- IVFFlat
```

**课程默认 HNSW**——RAG 知识库通常"灌完一轮、查询频繁、偶尔全量更新"，正好对上 HNSW 的甜区。

---

## 五、动手：Docker pgvector + 递归切分 + 百炼 embedding + 余弦检索

### 5.1 Embedding 端点选型（曲折，但值得记）

原本想复用你的中转站 Key，实测 `/embeddings` 返回 **503 空 body**，但 `/chat/completions` 正常——说明**该中转只代理了 chat，没接 embeddings 后端**（不是账号问题）。遂转向 **阿里云百炼**，核实 2026 现状后定下：

| 模型 | 维度 | 批次上限 | 单行 token | 价格 | 语种 |
|---|---|---|---|---|---|
| **`qwen3.7-text-embedding-flash`** ✅ | 1024 | 20 条/批 | 128,000 | ¥0.125/百万 | 201 种 |

选它的理由：中文 201 语种（服务毕业项目财报/可转债中文检索）、flash 便宜、批次大、且**带 sparse embedding**（正好对接 W06 混合检索）。OpenAI 兼容端点 `https://dashscope.aliyuncs.com/compatible-mode/v1`，和现有"环境变量注入"机制无缝衔接。`vector(1024)` 建表维度对得上。

### 5.2 起库 + 建表（Docker，与你的 MySQL `agent_runtime` 各管各的）

```bash
bash 00_start_pgvector.sh     # docker run pgvector/pgvector:pg17，端口 5432
# 建 amber 用户 + w05rag 库（让 01/02 零改动）
docker exec -i <容器名> psql -U postgres -W <PGPASS> \
  -c "CREATE USER amber WITH PASSWORD 'amber123' SUPERUSER;"
docker exec -i <容器名> psql -U postgres -W <PGPASS> \
  -c "CREATE DATABASE w05rag OWNER amber;"
```

`01_build_index.py` 自动建扩展 + 表 + HNSW 索引：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE chunks (
    id      serial PRIMARY KEY,
    doc_id  text,
    content text,
    embedding vector(1024)
);
CREATE INDEX ON chunks USING hnsw (embedding vector_cosine_ops);
```

### 5.3 递归切分 + overlap（节选自 `01_build_index.py`）

```python
SEPS = ["\n\n", "\n", "。", "！", "？", "；", "，", " "]
CHUNK_SIZE, OVERLAP = 400, 80     # overlap≈块大小 20%，sliding window

def recursive_split(text, size, overlap, seps):
    if len(text) <= size:
        return [text]
    sep = seps[0]
    pieces = _split_with_sep(text, sep)          # 按当前分隔符切，保留 sep 到末尾
    chunks, cur = [], ""
    for p in pieces:
        if len(cur) + len(p) <= size:
            cur += p
        else:
            if cur: chunks.append(cur)
            if len(p) > size and len(seps) > 1:  # 这块仍太大，换更细分隔符递归
                chunks.extend(recursive_split(p, size, overlap, seps[1:]))
            else:
                cur = p
    if cur: chunks.append(cur)
    if overlap > 0 and len(chunks) > 1:          # sliding window overlap
        merged = [chunks[0]]
        for i in range(1, len(chunks)):
            ov = chunks[i-1][-overlap:]
            merged.append(ov + chunks[i])
        chunks = merged
    return chunks
```

切完对每块调百炼 embedding（每批 ≤20 条），写入 `chunks` 表。`02_query.py` 把用户问题也 embedding 后跑余弦检索，支持 `top_k` 与相似度阈值可调。

### 5.4 带过滤条件的混合 SQL（pgvector 核心优势）

向量列和普通列能在**一条 SQL** 里混合过滤——这是相对专用向量库的关键优势：

```sql
SELECT id, content, 1 - (embedding <=> :query_vec) AS similarity
FROM chunks
WHERE doc_id = 'doc1'                      -- 普通列过滤
  AND embedding <=> :query_vec < 0.7       -- 余弦距离阈值（= similarity > 0.3）
ORDER BY embedding <=> :query_vec
LIMIT 5;
```

> ⚠️ **诚实标注**：真正的「向量 + BM25 混合检索（RRF 融合）」是 W06 的内容，本周只做纯向量 + 上述带 `WHERE` 的混合 SQL。

---

## 六、踩坑记录（3 条，均有实证）

### 坑 1：中转站 `/embeddings` 返回 503，差点误判成"账号问题"

- **现象**：`Invoke-RestMethod` 调 `/embeddings` 返回 `HTTP 503` 空 body；同窗口 `/chat/completions` 正常（返回"你好"）。
- **真因**：很多国内中转只代理了 `chat/completions`，embeddings 路由没接，网关层直接挡掉（空 body 的 503 更像网关"此路不通"，不是 OpenAI 真实的带 `retry-after` 的 503）。**判定方法**：chat 正常 + emb 503 空 body = 中转没接 emb 后端，与账号无关。别急着下结论，对照 chat 端点 + 打印响应体才是正确姿势。
- **解法**：转向百炼 `qwen3.7-text-embedding-flash`，OpenAI 兼容端点零改动接入。

### 坑 2：03 演示脚本结论写错——代码跑出来的现象和结论对不上

- **现象**：第一版 `03_bad_case.py` 写"『银行卡退款需3至7个工作日』被劈成两半"，但**实际跑出来这句是完整的**，被字符边界劈开的是它**前面那句**"退款申请提交后，我们将在1至3个工作日内完成审核"（fixed 块结尾"…个工作日内" / 下块开头"完成审核"）。
- **真因**：脚本用的结论文字是我**凭记忆写死**的，没对照实际运行输出。演示代码也必须跑一遍验证，现象和结论要能对上，否则就是假演示。
- **解法**：改成 fixed 硬切（不按语义边界）让句子**真**被劈开，结论文字据实修正，重跑验证通过（见 `_03_result.txt`）。

### 坑 3：PowerShell 5.1 的 `curl` 是别名 + GBK 乱码

- **现象**：PS 5.1 里 `curl` 是 `Invoke-WebRequest` 的别名，语法完全不同；即使走 `Invoke-RestMethod`，API 的 UTF-8 响应被 PS 用 GBK 解码，中文显示成 `ä½ å¥½`（"你好"的乱码）。
- **真因**：PS 5.1 控制台默认编码非 UTF-8。
- **解法**：验证用 `Invoke-RestMethod`（JSON 自动反序列化、中文干净）并显式 `[Console]::OutputEncoding = UTF8`；或真 curl 用 `curl.exe`（带 EXE 后缀绕过别名）。**正式调 embeddings 改用 Python 脚本**（`requests` 默认 UTF-8 正确），根本不依赖 PS 控制台中文显示。

---

## 七、验收清单（对照 CURRICULUM）

| 验收项 | 状态 | 证据 |
|---|---|---|
| 能解释"这条查询为什么召回错了" | ✅ | 03 演示 fixed 硬切劈句→语义不完整→召回错（实证） |
| 能写带过滤条件的混合 SQL | ✅（部分） | 给出"向量列 + `WHERE` 普通列"混合 SQL；纯向量检索已跑通；BM25 混合检索留 W06 |
| 调 top_k 与阈值观察召回变化 | ✅ | 实验 A 三段输出（show-all / top_k=3 / 阈值0.3） |
| 调切分粒度观察召回变化 | ✅ | 实验 B（120/0 vs 400/80）最佳块 0.65→0.73 |

---

## 八、数据 / 实测结果

所有数字来自本机真实运行（Python 3.13，百炼 `qwen3.7-text-embedding-flash`，Docker pgvector:pg17）。

### 实验 A（默认切分 400/80，4 chunks）—— top_k / 阈值机制

`02_query.py "退款多久到账"`：

| 操作 | 结果 | 说明 |
|---|---|---|
| `--show-all`（top_k=20） | #2=0.6482 / #3=0.5118 / #1=0.4552 / #4=0.1877 | #4（数据导出 API）明显噪声，相似度断崖 |
| top_k=3 | 召回 #2/#3/#1，#4 自然被砍 | top_k = 按排名截断 |
| top_k=5 阈值=0.3 | #2(0.6445)/#3(0.5123)/#1(0.4549)，#4 被剔 | 阈值 = 硬门槛，比 top_k 更精准挡噪声 |

> 注：不同次查询重算 embedding，数值有 ±0.01 浮动（百炼微小非确定性），属正常。

### 实验 B（切分 120/0，18 chunks）—— 切分粒度对召回的影响

默认 top_k=5：

| 块 | 相似度 | 内容 |
|---|---|---|
| #5 | 0.7310 | 审核通过后…银行卡退款需3至7个工作日 |
| #4 | 0.6344 | 用户7天内…退款申请1至3个工作日完成审核 |
| #3 | 0.6006 | ## 二、退款政策（标题） |
| #10 | 0.5326 | 发票段 |
| #9 | 0.5141 | 退款政策+年度套餐+发票 |

**关键结论（nuanced，不是简单说"切太小不好"）**：

1. **"切太大→平均后不准"被实证**：默认 chunk[1] 把"账户登录的 80 字 overlap 尾巴 + 整个退款政策段"混在 413 字块里，账户登录稀释了退款语义 → 只有 0.65；切成 120 后答案句单独成块 → 0.73。
2. **但 120/0 不是好配置**：零 overlap 有**劈句风险**（坑 2 / 03 已实证）；18 块存储检索量翻 4.5 倍；文档更长时相关小块在 top_k 竞争中更易被挤出（实验 B 里 #10/#9 发票块已挤进 top5）。
3. **没有一刀切的 chunk size**：聚焦短答案小切分更准，需跨句理解的小切块会丢上下文。**最佳实践 = 适中切分 + 合理 overlap（400/80 稳健默认，但应按文档和查询类型调）**。

### 切分召回错根因演示（03，无需 Key）

fixed 硬切（80 字符、零 overlap）把"退款申请提交后，我们将在1至3个工作日内完成审核"劈成：

```
chunk[2] 结尾：…审核通过后，款项将原路返回至您的支付账户：微信支付通常即时到账，支付宝需 1 至 2 个工作
chunk[3] 开头：日，银行卡退款需 3 至 7 个工作日。若超过上述时限仍未到账…
```

（注：第一版结论误写成"银行卡退款"那句被劈，实际被劈的是它前面那句；已修正。）

分别 embedding 时两块都不含完整语义 → 与"退款到账要几天"的余弦相似度都偏低 → 在 top_k 竞争中输给更完整的块 → **召回错**。修复：用 recursive/structure 切分保住句子边界，或保留 overlap 让边界句在相邻块都完整出现。W05 默认 400/80 的 recursive 切法下该句完整，召回正确，印证"切分是召回质量头号开关"。

---

## 九、这周的取舍

### 做了什么

- 阶段1 四小节全讲透（Embedding / 余弦 / 切分 / 向量库+HNSW），每节停下等反馈、用 PHP/SQL 类比打底。
- 阶段2 实操跑通：Docker pgvector + recursive 切分(400/80) + 百炼 embedding(1024维) + 写入 `vector(1024)` + HNSW 余弦索引 + 余弦检索（`top_k`/阈值可调）。
- 实验 A/B 亲手调参，实证"切分是召回质量头号开关"的 nuanced 结论。
- 03 演示 fixed 硬切劈句→召回错根因（含一次脚本结论 bug 的修正，诚实披露）。

### 放弃了什么 / 留到后面

- **BM25 混合检索（RRF 融合）**：CURRICULUM 验收的"混合 SQL"本周只做到"向量 + `WHERE` 普通列"层面；**向量 + BM25 的混合检索是 W06 主体**，本周不做，正文已如实标注边界。
- **语义切分（semantic splitting）**：最准但最贵（额外调模型判断话题边界），本周未做，W07 进阶 RAG 再碰。
- **真实 18 chunks 库已恢复**：实验 B 把 01 改成 120/0 跑了 18 chunks，收尾前已指导改回 400/80 重跑，恢复 4 chunks 正式库（W06 基于它）。

### endpoint 选型小结

百炼 `qwen3.7-text-embedding-flash`（1024 维、201 语种、flash ¥0.125/百万、带 sparse）——中文 RAG 第一梯队，且和现有"OpenAI 兼容 + 环境变量"机制无缝衔接，W05→W06→毕业项目都能复用同一接入层。中转站 embeddings 不可用已排除。

### 一个方法论提醒

我们联网核对了 2026 年 Embedding 模型（BGE-M3 / Qwen3-Embedding / 百炼 flash）与 pgvector 0.8.x（HNSW 默认、vector 建 HNSW 上限 2000 维、超了用 halfvec/bit）的现状，确认选型未过时。Agent 领域变化快，但"切分 + 余弦 + 向量索引"这套基础结构没变过。

---

## 下一篇

W06 讲 **RAG 完整链路**——把本周的纯向量检索升级成：Query 改写 → 多路召回（向量 + BM25）→ RRF 融合 → Rerank → 拼上下文 → 生成 → 引用。用 30 题测试集对比三种方案（纯向量 / 纯 BM25 / 混合+重排），准确率做成表，并让答案带引用出处。那套"带 `WHERE` 的混合 SQL"会变成真正的"向量 + 关键词"双路召回。

> 本周留下的尾巴：BM25 通路 + RRF 融合（W06）；语义切分（W07）；chunk size 按文档类型自动调优（工程化）。

## 附录：学习对话实录

- [DIALOGUE.md](DIALOGUE.md) —— 提炼版：按主题归类，含「给 AI 的复现指令」，可直接复制给任意 AI 带你走一遍
- [DIALOGUE-QA.md](DIALOGUE-QA.md) —— 逐轮一问一答底稿：保留每一次提问、回答与终端输出

## 附录：延伸阅读

- [pgvector GitHub](https://github.com/pgvector/pgvector) —— HNSW / IVFFlat 索引、运算符族、维度上限
- [阿里云百炼 Embedding 文档](https://help.aliyun.com/zh/model-studio/embeddings) —— `qwen3.7-text-embedding-flash` 维度/批次/价格
- 2026 实践：中文 RAG 首选 BGE-M3 / Qwen3-Embedding / 百炼 flash；pgvector 0.8.x 是 Postgres 侧 RAG 默认扩展

---

## 发布检查

- [x] 代码实际跑过，输出贴进正文（实验 A 三段 + 实验 B + 03 bad case）
- [x] 至少 2 条真实踩坑（实际 3 条：中转 503 误判 / 03 结论 bug / PS curl 别名+GBK 乱码）
- [x] 有数字/表格（实验 A 相似度 0.65/0.51/0.45/0.19；实验 B 0.73/0.63/0.60/0.53/0.51；chunk 4→18）
- [x] 有 PHP / SQL 类比（兴趣特征向量 / 对语义敏感的哈希 vs md5 / 滑动窗口 / MySQL 加 VECTOR 列）
- [x] 标题不标题党，但要有信息量
- [x] 结尾有引导（下一篇 / 仓库链接）
- [x] 本周写了 `DIALOGUE.md`（对话实录 + 可复现的 AI 引导脚本）
- [x] 本周写了 `DIALOGUE-QA.md`（逐轮问答底稿，只收技术相关）
- [x] BM25 混合检索未做一事诚实披露（留 W06），未假装本周完成
- [x] 03 脚本结论 bug 已修正并如实记录，未假装一次写对
