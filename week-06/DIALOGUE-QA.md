# W06 · 学习对话逐轮底稿（DIALOGUE-QA）

> 这是 [DIALOGUE.md](DIALOGUE.md) 的**逐轮一问一答底稿**，未做归纳压缩。
> 保留每一次提问、回答与终端输出。只收技术内容；制定规则 / 调整课表 / 产出管理类元话题不在此列；
> 技术方案决策属技术内容，保留。命令原文照录（路径已脱敏，Key 已打码）。
> 共 20 轮，覆盖六小节概念引导、选语料、建库踩坑、三方案对比、真 cross-encoder 验证。

---

### 第 1 轮 · 触发：开始 W06

**amber**：开始W06课程

**我**：按约定触发阶段1 引导学习。读 `CURRICULUM.md`（W06=RAG 完整链路：Query改写→多路召回→RRF→Rerank→拼上下文→生成→引用）/ `PROGRESS.md` / `week-05` 产出。联网核对 2026 RAG 现状：向量+BM25+RRF+Cross-encoder 是默认生产架构（dense-only Recall@10 0.58–0.65，混合 0.72–0.85）。画全链路总图，进入第1节。

---

### 第 2 轮 · 第1节 纯向量翻车（check-in）

**我**：讲四类失效（专有名词/标识符/罕见术语/否定对比）+ 生产数字。留下两个 check-in：① 用你自己的项目举一个纯向量翻车的真实场景；② 四类失效里哪类在财报/可转债 Agent 最致命？

**amber**：1. 之前项目未应用向量数据库，但上述四个失效场景均能理解。2. 应该是①第一——专有名词，财报中有很多专业术语，很相近，向量差别不大，但实际表示却差很多。

**我**：两点都到位。第②点正好挂钩 W09 验收"扣非/归母零误匹配"。进入第2节。

---

### 第 3 轮 · 第2节 BM25 公式（check-in）

**我**：讲 Okapi BM25 三部件（IDF/k1/b）+ MySQL `MATCH...AGAINST` 同源类比。两个 check-in：① k1 和 b 哪个在你的财报语料更值得调？② 用一句话说清为什么纯向量把扣非/归母当邻居、BM25 不会？

**amber**：1. b更值得调，财报分很多类型，季度报、年报、报告摘要等内容长度不一，调整B值可以更好的平衡分数，内容权重应该相当；2：扣非和归母后面跟着的词一样，会导致他们转换后的向量空间距离相近，而BM25是判断词频、权重等计算分数，扣非和归母是两个不一样的token。

**我**：两题答对。补：b 是长度归一化强度（0=不归一、1=全力归一、默认0.75）；chunk 长短差仍存在，b 比 k1 更该调但 400/80 切分已压住方差，实际收益有限。

---

### 第 4 轮 · 第3节 多路召回（拍板语料）

**我**：讲两路并行各 top20 → 按 chunk id 合并去重候选集（约30~40唯一块）。PHP 类比：并发两条 SQL 各 LIMIT 20，UNION 合并。设计题：建什么语料？A 复用+扩写退款政策 / B 财报可转债风格小语料。

**amber**：用B方案

**我**：确定 B——建 6 篇财报/可转债风格语料（指标定义/赎回回售/转股价下修/年报片段/信用评级担保/票面利率期限），相近词落不同 chunk，结论还能喂 W09。进入第4节。

---

### 第 5 轮 · 第4节 RRF 融合（手算 check-in）

**我**：讲 RRF 公式 `1/(k+rank)`，量纲不同不能直接加分（BM25 18.4 会碾压余弦 0.82）。手算：文档 X 在 Dense #1、BM25 缺席；文档 Y 两路都 #15。谁靠前？想保精确命中调大调小 k？

**amber**：1. x的得分 1/61=0.0163，y的得分=1/75+1/75=0.0266；融合后 y靠前；2. 调小 顶部排名的贡献会被放大；

**我**：两题算对。补机制：k 变小 → #1 与 #15 倍数差距拉大（k=10 时 2.3倍、k=60 时 1.2倍），想让 BM25 精确命中的"扣非净利润"块死死压住语义相近块，调小 k（20~30）。进入第5节。

---

### 第 6 轮 · 第5节 Query 改写（判断+设计题）

**我**：讲三类原句翻车（指代/问句/多意图），多轮里"指代+问句"常同现需串联。两个题：① 多轮财报 Agent 哪类最危害？② 轻量版（A）还是塞 HyDE（B）？

**amber**：1. 第二种 问句式而非关键词式，因为用户提问的真实意图可能被长句稀释，且不一定能正确表示准确的术语关键字。这类危害较大，需要能准确解读出用户意图，不然南辕北辙；2. 选A方案；

**我**：站得住。补：多轮里"它+问句"常同现，轻量改写要解指代+展平关键词串联。HyDE 留 W07。进入第6节。

---

### 第 7 轮 · 第6节 Cross-encoder（check-in）

**我**：讲 bi/cross-encoder 区别表（各自编码 vs 拼接逐字 attention、预存 vs 实时）。成本账：K=20 甜点、+100ms(生产GPU)、Recall 0.85+。两个 check-in：① 用户问"避免内存泄漏"但语料"检测内存泄漏"更近，哪方案排前面？② 光 Hybrid 够不够兜住 W09 零误匹配？

**amber**：1. 第三种方案，cross-encoder 会对query和doc的每个token都相互attention，精度比bi-encoder 高，能识别能识别"避免 vs 检测"这种反义；2. 不够，还需要进行cross-encoder进行重排，提高识别精度；

**我**：Q1 答对。Q2 方向对但还差一层：② Hybrid 解决 token 不同混淆，③ 重排抬精度，但两块都只写"净利润"时 token 完全相同 → BM25/rerank 都分不出，必须字段级归一化兜底（W09 零误匹配靠第④层）。阶段1 收尾，进入阶段2。

---

### 第 8 轮 · 阶段2 建语料 + 沙箱跑 BM25-only

**我**：建 6 篇语料 + 加载器 + 手搓 BM25 + RRF + Dense(Key门控) + Rerank(双模式) + 评测 + 30题测试集。沙箱（无 Key）跑 BM25-only 真实数字。

**终端输出（沙箱）**：
```
===== 方案: BM25-only =====
Recall@10 = 30/30 = 1.000
MRR@10    = 0.983
平均延迟  = 0.2 ms/query
分类型 Recall@10: exact_token 12/12 · semantic 8/8 · question 6/6 · antonym 4/4 = 1.000
===== 判别力探针 =====
Q='扣非净利润': 目标 指标定义#1 #1 | 干扰 指标定义#2 #3 -> ✅ 分离
Q='赎回条款':   目标 赎回与回售条款#1 #1 | 干扰 #2 #2 -> ✅ 分离
Q='下修条款':   目标 转股价与下修#2 #3 | 干扰 #1 #1 -> ❌ 混淆
```

**我**：真实数字到手。探针#3 ❌ 是**真发现**（两块都含"转股价" token，BM25 被带偏），论证"BM25 不是银弹，所以才要 Hybrid+Rerank"。给本机命令：建库→灌库→跑三方案。

---

### 第 9 轮 · 选 A 跑 Hybrid+Rerank

**amber**：从A开始

**我**：确认沙箱无 Key，改用确定性 mock embedding 把 Hybrid 链路跑通（验证 RRF+rerank 代码无 bug）。改 `00_start_pgvector.sh` 为幂等 + `dense.py` PG 连接改环境变量可配。给本机命令清单。

---

### 第 10 轮 · gp17 建库踩坑（role postgres 不存在）

**amber**：PS> docker exec -i gp17 psql -U postgres -c "CREATE DATABASE w06rag OWNER amber;"
psql: error: connection to server on socket ".../.s.PGSQL.5432" failed: FATAL: role "postgres" does not exist

**我**：根因清晰——gp17 容器管理员即 amber，没有 postgres 角色。建库要用 `amber` 不是 `postgres`。改脚本建库用户默认 `amber`，镜像标签对齐 `0.8.6-pg17`。

---

### 第 11 轮 · template1 跳板建库成功

**amber**：命令执行报错。PS> docker exec -i gp17 psql -U amber -c "CREATE DATABASE w06rag OWNER amber;"
psql: error: ... FATAL: database "amber" does not exist

**我**：根因：`psql -U amber` 没指定 `-d`，默认连同名库 `amber`，该库不存在→连接失败，CREATE 没执行。改 `00_start_pgvector.sh` 建用户/建库加 `-d template1` 跳板。给确认命令 `docker exec -i gp17 psql -U amber -d template1 -c "CREATE DATABASE w06rag OWNER amber;"`。

**amber（后续）**：新建成功了，继续实操

**我**：w06rag 建好。交付 PS 清单（bat 加载 Key + 手写 PG_ + 用 managed venv 全路径）。

---

### 第 12 轮 · 执行规范固化（PS + bat，不提供 .sh）

**amber**：后续实操命令都是基于ps去执行，都会调用 start-env-windows.bat 配置基本的APIkey参数；这部分参数固定的加载的。如果后续实操需要用到其他配置，都给出手写命令行手动执行，和安装依赖。后续不要给sh命令代码，都基于ps去给命令，都是基于一套配置来扩展，记录一下。重新给一下基于 start-env-windows.bat 执行以后的命令实操步骤。

**我**：确认 bat 用 `set` + 末尾 `powershell.exe -NoExit` 启 PS 子进程继承 env，本窗口 `$env:API_KEY` 可读。固化进长期记忆「实操执行规范」段：PS + bat 加载 + 其他配置手写 + 依赖手写 pip + 不提供 .sh。给基于 bat 的 PS 步骤（py 版本校验 / 手写 PG_ / 灌库 / eval.py）。

---

### 第 13 轮 · bat PYTHON_HOME 空 → import jieba 失败

**amber**：PS> python --version → Python 3.13.14
PS> python -c "import jieba, numpy; print('jieba+numpy ok')"
ModuleNotFoundError: No module named 'jieba'
PS> pip install jieba → ... SSLError(SSLEOFError...) ... Could not fetch URL https://pypi.org/simple/jieba/

**我**：根因：bat 的 `PYTHON_HOME` 第57行空，bat 启的 PS 走系统 3.13.14（无 jieba）；本机 pip 连 pypi.org SSL EOF 装不上。解法：沙箱用 managed venv 的 pip 代装 jieba+numpy+openai+psycopg2（装的是本机文件）。bat 的 `PYTHON_HOME` 改为 `envs\default\Scripts`。

---

### 第 14 轮 · 沙箱代装依赖进 venv

**我**：沙箱跑 `pip install openai psycopg2-binary sentence-transformers`（装本机文件）。验证 venv 可 `import jieba,numpy,openai,psycopg2,sentence_transformers`。amber 本机零网络装包即跑通。

**终端（沙箱）**：`sentence-transformers OK 6.0.1`（torch-2.14.0 / transformers-5.17.0 同装）

---

### 第 15 轮 · 灌库 + 三方案跑通（真输出）

**amber**：PS> python -c "from corpus import load_chunks; import dense; dense.build_index(load_chunks('corpus'))"
已写入 9 个 chunk 到 w06rag.chunks
PS> python eval.py
（三方案输出，见正文第五节表：BM25 Recall1.000/MRR0.983/0.2ms；Hybrid Recall1.000/MRR1.000/289.2ms；Hybrid+Rerank(fallback) Recall1.000/MRR0.983/184.3ms；探针#1#2 三路✅、#3 三路❌）

**我**：**第一处诚实修正**：我之前两次预测"探针#3 Hybrid 翻盘"被打脸——[BM25]❌、[Hybrid]❌（目标#3 干扰#1），两块都讲"转股价"，Dense 也分不清。结论："混合检索补词法盲区、补不了语义盲区，第④层字段级归一化才是唯一解"，直接坐实 W09 伏笔。小语料 Recall 全 1.000 是天花板，真实区分力在 MRR 与探针。

---

### 第 16 轮 · 选 A 验证真 cross-encoder

**amber**：A

**我**：读 `rerank.py` 确认 cross 实现，优化两处：① 真 cross-encoder 模型改**模块级单例缓存**（原每调 rerank 重载一次、30题卡5分钟）；② 探针扩成**三列** [BM25]/[Hybrid]/[Rerank]（仅真重排可用时显第三列）。沙箱代装 sentence-transformers（torch 124MB 约30分钟）。

---

### 第 17 轮 · 装包完成 + 跑真 cross-encoder

**我**：venv 验证 `import sentence_transformers` 成功。给最终命令（`$env:HF_ENDPOINT="https://hf-mirror.com"` 加速首下 2.2GB 权重 + `$env:RERANKER="cross"` + `python eval.py`）。

**amber（跑完）**：（真 cross-encoder 输出，见正文第五节）
```
===== 方案: Hybrid+Rerank =====
Recall@10 = 30/30 = 1.000
MRR@10    = 0.983
平均延迟  = 22996.9 ms/query
===== 判别力探针 =====
Q='下修条款': [BM25] 目标#3 干扰#1 ❌ || [Hybrid] 目标#3 干扰#1 ❌ || [Rerank] 目标#2 干扰#1 ❌
```

**我**：**第二处诚实修正 + 成本账**：
1. 真 cross-encoder 仍 ❌，只把目标从 #3→#2 部分缓解——三道防线（BM25/Dense/真cross）全救不了语义相似块，字段级归一化唯一解。
2. CPU 实测 **22996.9ms/query（≈23秒）**，比我第6节引的 GPU 基线 +100ms 慢 ~230 倍。
3. 真重排 MRR 0.983 = fallback，**低于** Hybrid(RRF) 1.000——9 块小语料上 rerank 噪声>信号，重排价值在大语料才显著。

---

### 第 18 轮 · 收尾启动

**amber**：跑完

**我**：加载 `course-week-finalize` 八步流水线。解读三个诚实发现（探针#3未翻盘/CPU 23s vs GPU 100ms/真重排MRR反降），开始收尾：复制代码→写 README→DIALOGUE→DIALOGUE-QA→learning-log→PROGRESS→红线扫描。不自动 commit/push。

---

> 注：W06 完整 20 轮里，元话题（如"进度怎么记""要不要发知乎"）已按规则剔除；技术环境配置（bat/PS/gp17 建库）属可复现必要信息，保留。
