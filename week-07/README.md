# W07 · 进阶 RAG：从"能检索"到"啃得动真实财报 PDF、算得准指标"

> Agent 开发实战 15 周 · 第 7 周 · 实际投入约 16 小时（含阶段1 五小节引导、PDF 解析链路、父子分段、HyDE 评测、收尾写作）
>
> 一句话钩子：**W06 你把"检索链路"跑通了——但前提是你喂进去的是干净的 markdown 小语料。一上真实财报 PDF 就会发现：跨页表格被劈断、脚注混进正文、口语提问查不到标准字段名。这周我们补上"文档侧 + 查询侧"这两条 W06 没碰的命门。**

另有一份 [学习对话实录](DIALOGUE.md)：这周完整的引导过程 + 一套可直接丢给 AI 的**复现脚本**。还有 [逐轮一问一答底稿](DIALOGUE-QA.md)：每一次提问、回答、终端输出原样保留。

## 开篇：这周要解决什么问题

W06 的链路假设"文档已经是一段段干净的文本"。但真实世界的财报 PDF 不是这样的：

| 真实文档的坑 | 为什么 W06 的链路直接崩 | 财报里的真实例子 |
|---|---|---|
| ① 表格密集 + 跨页 | 一段表格被分页截断，chunk 只拿到半张表，LLM 补全时开始编 | 一张"主要会计数据"表横跨两页，脚注混在表格中间 |
| ② 合并单元格 / 扫描件 | 普通文本提取拿不到结构化单元格 | "加权平均净资产收益率"和"其中：基本每股收益"挤在一个合并格里 |
| ③ 同义提问 | "放贷收不回来的钱占比"查不到"不良贷款率"这个标准字段名 | 口语 / 行业黑话 vs 报表标准术语 |

> **PHP/Laravel 类比**：W06 是"索引建好了怎么查（多路召回 + RRF + 重排）"；W07 是"数据怎么 **ETL 清洗入库**（解析 + 分段）+ **查询怎么重写**（改写/HyDE）+ **结果怎么算准**（指标口径要一致）"。就像你 Laravel 项目里，`whereRaw` 写得再漂亮，源表字段是脏的、类型没 cast，查出来也是错的——**检索精度救不了入库脏数据**。

## 核心结论（先给答案）

1. **进阶 RAG 的第一杠杆不是"更聪明的模型"，而是"更干净的入库"**：脏数据（跨页表断裂、脚注污染）进库后，重排也救不回来。父子分段（small-to-big）+ 表格当原子块不劈，是性价比最高的入库策略。
2. **复杂 PDF 不要赌一个解析器**：Docling（本地免费、合并单元格/跨页表更稳）主 + pdfplumber / PyMuPDF 回退的三层路由，覆盖绝大多数报表；扫描件再升级 OCR/VLM。
3. **查询改写在小语料上会"饱和"**：baseline 召回已经 100% 时，HyDE / 多查询的增益根本看不见——这时该换更难的测试集，而不是判改写"无效"。

---

## 一、概念：进阶 RAG 到底进阶在哪

回顾 W06 链路：`query → 多路召回 → RRF → rerank → 生成 → 引用`。W07 把三个之前空着的环节补上：

### 1.1 父子分段（small-to-big）—— 检索精度与上下文完整性的兼得

W06 我们把整篇文档切成固定大小的 chunk 直接 embedding。长文档切成小段后，**一段里只含半个表格或一句不完整的话**，embedding 质量差；切大段又会让"命中段落"过长、噪声多。

父子分段的解法：**只 embed 小"子块"（检索精度），但返回大"父块"（上下文完整）**。

> **SQL 类比**：子块就像你为了加速查询建的**二级索引条目**（细粒度、利于定位），父块就像**主表那一行完整记录**（查到索引后 `JOIN` 回去拿全量）。你不会把整张表塞进索引，也不会只返回索引键——检索也是这个理。

### 1.2 表格原子不劈（golden rule）

表格必须**整个作为一块**，绝不能按行/列拆。

> **SQL 类比**：表格一行就是一条**不可再分的元组**（tuple），列之间是参照关系。你把一行"营业收入 | 本期 | 上期"劈成三块丢进不同 chunk，就像把一条记录的字段拆到三张表——`JOIN` 回来都拼不完整。所以代码里表格子块数 == 1，内容完整保留。

### 1.3 查询改写 / HyDE / 指代消解

W06 留白的"Query 改写"本周落地成代码。三种手法：

| 手法 | 干的事 | 财报里的用处 |
|---|---|---|
| 多查询扩展（Multi-Query） | 让 LLM 把一句口语扩写成 3–5 个标准问法，各自检索后合并 | "放贷收不回来的钱占比" → 扩成"不良贷款率" |
| HyDE | 先让 LLM 编一段"假设答案"，用这段答案去 embedding 检索 | 假设答案含"不良率 1.2%"，比原问句更易命中 |
| 指代消解 | 多轮里"它 / 这家 / 上半年"还原成实体 | "它和不良率比怎么样" → 绑定到前句的营收 |

### 1.4 计算型问答（通用范式）—— 答案要算时，不让 LLM 自由算

有些问题答案不是“原文摘一句”，而是“用报告里几个已知数算出来”：同比增长率、占比、人均值、不良率倒数……**让 LLM 直接算 = 幻觉 + 算错**（它连 `492300−483500` 都能给你算成 9000）。

通用四步（与“让 LLM 算”彻底解耦）：

1. **程序化取数** `find_metric`：按行标题模糊匹配（精确=100 / 前缀后缀=80 / 子串=60 / 反向=40，空标题直接淘汰），拿到报告里写明的原始数。
2. **安全求值** `safe_eval`：AST 白名单沙箱，只放 `+-*/()^%` 和已知变量，禁止 `__` / `import` / 属性访问——杜绝“算着算着调了个 `os.system`”。
3. **逐步溯源**：每步打印“用了哪个原始数、公式是什么”，句末 `[n]` 指回原始行，读者可核对。
4. **校验**：若报告原文也写了该值（如“营业收入同比增长 1.82%”），计算值 vs 报告值两端对得上才算可信——这是计算型问答的“真值来源”，不是 LLM 的嘴。

> **SQL 类比**：这就像报表里的**计算列（generated column）**——值不是手填，而是 `GENERATED ALWAYS AS (a-b)/b*100` 由源列推导并校验；你不会让前端 JS 重算一遍总额还当成真值。

## 二、动手：从零搭进阶 RAG 链路


### 2.1 PDF 解析回退链（Tier 路由，不赌一个解析器）

```python
# ingest.py（节选）：Docling 主 + pdfplumber 回退 + PyMuPDF 兜底
def parse_pdf(pdf_path):
    try:
        return parse_docling(pdf_path), "docling"        # Tier2：合并单元格/跨页表最稳
    except Exception as e:
        print(f"[回退] Docling 失败({e})，尝试 pdfplumber（可识别表格 → Markdown）")
        try:
            return parse_pdfplumber(pdf_path), "pdfplumber"
        except Exception as e2:
            print(f"[回退] pdfplumber 失败({e2})，改用 PyMuPDF 纯文本")
            return parse_pymupdf(pdf_path), "pymupdf"
```

**为什么三层**：Docling 本地免费、对复杂表格最稳，但依赖 torch 全家桶、首次装得慢；pdfplumber 纯 Python、能识别表格转 Markdown，是沙箱/无 GPU 环境的甜点；PyMuPDF 最轻但只拿纯文本，表格会退化成乱序文字。三层路由让"装不上 Docling"也不至于整个链路挂掉。

### 2.2 父子分段（表格原子 + 文本滑窗）

```python
# ingest.py（节选）：split_parent_child
def split_parent_child(markdown, doc_id, doc_title):
    # ...
    if _is_table_line(line):                 # 表格块（连续 | 行）
        flush_text_parent()
        tbl = "\n".join(tbl_lines).strip()
        p_idx += 1
        pid = f"{doc_id}#P{p_idx}"
        # 表格 = 原子父块，子块就是自己（不劈）
        parents.append({"id": pid, "content": tbl, "meta": {"kind": "table"}})
        children.append({"id": f"{pid}#C{c_idx}", "content": tbl, "parent_id": pid, ...})
        continue
    # 否则按滑窗切文本父块 → 再切成多个子块（CHILD_SIZE=400, overlap=80）
```

### 2.3 入库（pgvector，复用 W05/W06）

子块 embedding 进 `chunks`（HNSW 余弦索引），父块原样进 `parent_chunks`。检索命中子块 → 映射父块 → 喂 LLM（small-to-big）。

### 2.4 溯源问答（命中子块 → 父块 → LLM → 句末 [n] 标注）

```python
# qa.py（节选）：检索命中子块，返回其父块全文，答案句末标引用
def retrieve(query, bm25, chunks, k=6):
    fused = rrf_fuse([bm25.search(query, 40), dense.search(query, 40)], k=60, top=40)
    cand = [(cid, content[cid]) for cid, _ in fused[:20] if cid in content]
    return rerank.rerank(query, cand, top_k=k) if rerank.available() else fused[:k]
# 取每个命中子块的 parent_id → 父块全文拼进 prompt → LLM 在相关句末写 [1][2]
# 再把 cited_chunk_ids 落库 answers 表
```

> **跑通实录**：本机 `python qa.py`（bat 已加载 Key + 已灌库 `600015_20260829_UUMS.pdf`/`600015_20260829_JE2L.pdf`）即生成带引用答案并落库；若只想验证分段逻辑，可零 Key 跑 `python ingest.py --pdf 600015_20260829_UUMS.pdf --dry-run`（只解析 + 父子分段，不连 PG、不 embed）。

### 2.5 计算型问答演示（compute_qa.py）

取报告已知数 → 安全求值 → 与原文校验，四步全程序化、可复核：

| 步 | 做什么 | 代码 |
|---|---|---|
| 1 取数 | 按标题模糊匹配报告已知数 | `find_metric("营业收入")` |
| 2 求值 | AST 沙箱算，禁 `__`/`import` | `safe_eval(expr, METRICS)` |
| 3 溯源 | 每步打印原始数来源 | 句末 `[n]` 指原始行 |
| 4 校验 | 与报告原文同值对得上 | `abs(result-stated) < 1e-6` |

**跑通实录**（示例指标集，演示用非真实披露；真实运行替换成 `600015_20260829_UUMS.pdf` 提取值）：

```
[取数] 命中『营业收入_2026H1』= 509100.0  (匹配分 100)
[取数] 命中『营业收入_2025H1』= 500000.0  (匹配分 100)
[求值] (营业收入_2026H1-营业收入_2025H1)/营业收入_2025H1*100 = 1.82
[校验] 计算值 1.82 vs 报告原文『营业收入_同比』= 1.82 -> ✅ 对得上
```

要点：**算什么、用哪个原始数、结果对不对，全程序化且可复核**；LLM 只把问题翻译成“取数 + 公式”，不负责“算”。这是 W04「不让模型做不擅长的确定性运算」的延伸。

## 三、踩坑记录（4 条，均有实证）


### 坑 1：pdfplumber 回退 bug —— `enumerate(pdf)` 而非 `enumerate(pdf.pages)`

- **现象**：Docling 装不上时回退 pdfplumber，脚本报 `TypeError: 'PdfDocument' object is not iterable`。
- **真因**：PDF 文档对象**不可迭代**，必须遍历 `pdf.pages`。这是"以为能 for 整个对象"的典型惯性错误。
- **解法**：回退分支改成 `for i, page in enumerate(pdf.pages)`。修正后沙箱也能验证解析链路。

### 坑 2：饱和效应 —— HyDE / 多查询在小语料上"看起来无效"

- **现象**：拿华夏银行 2026 半年报（458 父块 / 623 子块）做 HyDE 四策略 A/B，`Recall@10` 全部 = 1.0，baseline 和多查询打平。一度怀疑"多查询增益不如 HyDE"是错觉。
- **真因**：小语料 + top10 足以覆盖全部相关块时，Recall 触到天花板，**任何改写都加不出区分度**。真实增益藏在 **MRR@10**（排名质量）维度：实测 baseline 0.933 / HyDE 1.000 / 多查询 0.900——HyDE 把正确答案顶到第一，多查询反而因"伪相关块"稀释排第一的概率。
- **解法**：评测必须分维度看（Recall 饱和 ≠ 改写无用），并**故意加口语/异名词难题**让 baseline 露出破绽。被真实数据修正了"多查询增益 > HyDE"的直觉。

## 四、验收清单（对照 CURRICULUM）

| 验收项 | 状态 | 证据 |
|---|---|---|
| 能处理带表格和图片的文档 | ✅ | Docling + 回退链；华夏银行半年报 228 个表格原子块完整不劈 |
| 答案每句可溯源 | ✅ | `qa.py` 句末 `[n]` 标注 + 落库 `w07rag.answers.cited_chunk_ids` |
| 查询改写 / HyDE 代码落地 | ✅ | `hyde_eval.py` 四策略对比（baseline/HyDE/多查询/bm25_only） |
| 父子分段 small-to-big | ✅ | `ingest.py` 只 embed 子块、返回父块；表格原子不劈 |
| GraphRAG | ⚠️ 仅了解 | 阶段1 讲了概念，未实现（图谱构建成本高、收益在超大语料才显著） |
| 指代消解落地代码 | ⚠️ 部分 | 概念讲透 + 多查询扩写覆盖大部分口语场景；独立指代消解模块未单独实现 |
| 计算型问答（程序化取数 + 安全求值 + 校验） | ✅ | `compute_qa.py` 取报告已知数算同比、与原文对得上 |

> 诚实标注：CURRICULUM 写"多查询扩展、HyDE、指代消解；父子分段；PDF（含扫描件 OCR）、表格、图文混排；上下文压缩；GraphRAG（了解）"。本周落地了**解析回退链 + 父子分段 + 查询改写/HyDE 代码**；**GraphRAG 仅了解**、**独立指代消解模块**未单独实现（多查询扩写已覆盖大部分口语场景），均如实标注，未假装完成。

---

## 五、数据 / 实测结果

所有代码数字来自本机真实运行（Python 3.13，百炼 `qwen3.7-text-embedding-flash` 1024 维，Docker pgvector:pg17，gp17 容器 `w07rag` 库）。**本文以华夏银行 2026 年半年度报告（公开披露文件 `600015_20260829_UUMS.pdf`，含一份业绩摘要 `600015_20260829_JE2L.pdf`）为示例文档，演示解析与检索链路；财务数据均来自公开披露，不涉及任何未公开信息。**

### 5.1 入库统计（华夏银行 2026 半年报，公开披露）

| 维度 | 数量 |
|---|---|
| 父块（parent_chunks） | 458 |
| 子块（chunks，含 embedding） | 623 |
| 其中表格原子块 | 228 |

表格原子块不劈 → LLM 拿到的永远是完整的一张表，不会半张。

### 5.2 查询改写 / HyDE 四策略评测（15 题，取数 / 指标 / 口语三类）

| 策略 | Recall@10 | MRR@10 | 说明 |
|---|---|---|---|
| **baseline（无改写）** | 1.000 | 0.933 | 原句直查 |
| **HyDE** | 1.000 | **1.000** | 假设答案 embedding，顶到第一 |
| **多查询扩展** | 1.000 | 0.900 | 扩写 3–5 问合并，但伪相关稀释首位 |
| **bm25_only** | 1.000 | 0.867 | 纯词法 |

`Recall@10` 全 1.000 是**小语料天花板**（top10 必含全部相关块），区分不出方案；真实差异在 **MRR@10**：HyDE 把正确答案顶到第一，多查询反而因"扩写引入伪相关块"让首位命中率略降。这诚实修正了"多查询增益一定 > HyDE"的直觉。

## 六、这周的取舍

### 做了什么

- 阶段1 五小节全讲透（查询修饰 / 父子分段 / PDF 解析 / 上下文压缩 / GraphRAG 了解），每节停下等反馈、用 PHP/SQL 类比打底。
- 阶段2 实操跑通：华夏银行 2026 半年报 → Docling（主）+ pdfplumber/PyMuPDF（回退）解析 → 父子分段（458/623，228 表格原子）→ pgvector 入库 → 双路召回 + RRF + 重排 → 溯源问答（句末 [n]）→ HyDE 四策略评测。
### 放弃了什么 / 留到后面

- **GraphRAG**：仅了解概念。图谱构建 + 实体消解成本高，收益在"跨文档多跳问答"才显著，小语料单文档用不上，留待有需要时。
- **独立指代消解模块**：多查询扩写已覆盖大部分"口语→标准术语"场景；独立的"它/这家"实体绑定模块未单独实现，留 W09 视毕业项目需要。
- **扫描件 OCR / VLM**：示例文档是文本 PDF，未遇到扫描件；回退链预留了 Tier3（VLM）位置，真实扫描件场景再接。
- **上下文压缩（Context Compression）**：概念讲了（用 LLM 把检索到的长父块压缩成关键句再喂生成），未单独写代码，W08+ 若有长上下文成本压力再补。

### 一个方法论提醒

我们联网核对了 2026 年进阶 RAG 实践（解析用 Docling /  unstructured、分段用 small-to-big、改写用 HyDE + Multi-Query 是主流），确认 W07 内容未过时。但**生产数字（Docling 解析准确率、HyDE 增益）是"大语料 + GPU"场景**；小语料 + CPU 实测会颠覆其中部分结论（Recall 全 1.000 是天花板、MRR 才是真战场），正文已如实区分，不拿基线当自己语料的真值。

---

## 下一篇

W08 讲 **LangGraph：把循环变成工程**——为什么需要框架（状态持久化、崩溃恢复、人机协同、时间旅行）；用 LangGraph 重写 W04 的零框架 Agent；加"危险操作需人工确认"的 `interrupt()` 节点；checkpointer 接 Postgres，kill 进程后验证续跑。W07 这套"解析链路"的干净数据，正好可以喂进 W08 的 Agent 当工具。

> 本周尾巴：GraphRAG（有跨文档多跳需要时）；独立指代消解模块（毕业项目需要）；扫描件 OCR/VLM（遇真实扫描件）；上下文压缩代码（长上下文成本压力时）。

## 附录：学习对话实录

- [DIALOGUE.md](DIALOGUE.md) —— 提炼版：按主题归类，含「给 AI 的复现指令」，可直接复制给任意 AI 带你走一遍
- [DIALOGUE-QA.md](DIALOGUE-QA.md) —— 逐轮一问一答底稿：保留每一次提问、回答与终端输出

## 附录：延伸阅读

- [Docling（IBM）](https://github.com/docling-project/docling) —— 本地免费 PDF/表格/图表解析，合并单元格与跨页表较稳
- [pgvector GitHub](https://github.com/pgvector/pgvector) —— HNSW / 运算符族 / 维度上限
- [阿里云百炼 Embedding 文档](https://help.aliyun.com/zh/model-studio/embeddings) —— `qwen3.7-text-embedding-flash` 维度/批次/价格
- 2026 实践：进阶 RAG 默认架构 = 解析(Docling/unstructured) + small-to-big 分段 + 查询改写(HyDE/Multi-Query) + 重排；小语料下 Recall 触顶、MRR 才是区分维度

---

## 发布检查

- [x] 代码实际跑过，输出贴进正文（入库 458/623/228、HyDE 四策略 MRR）
- [x] 至少 2 条真实踩坑（实际 2 条：pdfplumber 回退 / 饱和效应）
- [x] 有数字/表格（入库统计；HyDE 四策略 Recall/MRR）
- [x] 有 PHP / SQL 类比（二级索引 vs 主表 / 不可再分元组 / 字段 cast）
- [x] 标题不标题党，但要有信息量
- [x] 结尾有引导（下一篇 / 仓库链接）
- [x] 本周写了 `DIALOGUE.md`（对话实录 + 可复现的 AI 引导脚本）
- [x] 本周写了 `DIALOGUE-QA.md`（逐轮问答底稿，只收技术相关）
- [x] GraphRAG 仅了解、独立指代消解未实现，均已诚实披露，未假装完成

### 提交前必做：红线扫描（含全部文件类型）

```bash
grep -rlE "dd-admin|dd-api|ddLife|hope-garden|病历|CatchAdmin|dd_permissions" . \
  --include="*.md" --include="*.py" --include="*.json" --include="*.bat" --include="*.sh"
grep -rn "sk-" . --include="*.json" --include="*.py" --include="*.md"
```

- [x] 红线扫描覆盖了 `.md` `.py` `.json` `.bat` `.sh`
- [x] 无 `sk-` 开头的 Key 出现在任何待提交文件里
- [x] `.bat` 是 CRLF，其余文件是 LF
