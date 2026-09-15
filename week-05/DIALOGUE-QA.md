# W05 · 学习对话逐轮底稿（DIALOGUE-QA）

> 这是 [DIALOGUE.md](DIALOGUE.md) 的**逐轮一问一答底稿**，未做归纳压缩。
> 保留每一次提问、回答与终端输出。只收技术内容；制定规则 / 调整课表 / 产出管理类元话题不在此列；
> 技术方案决策属技术内容，保留。命令原文照录（路径已脱敏，Key 已打码）。
> 共 27 轮，覆盖 endpoint 选型曲折、四节概念引导、切分实验 A/B、03 结论 bug 修正。

---

### 第 1 轮 · 触发：开始 W05

**amber**：开始W05课程

**我**：按约定这是阶段1 引导学习触发词。读 `CURRICULUM.md` / `PROGRESS.md` / `weekly-workflow.md`，联网核 2026 年 Embedding 模型与 pgvector 现状：BGE-M3 / Qwen3-Embedding 中文首选；pgvector 0.8.2 稳定、HNSW 默认索引、vector 建 HNSW 上限 2000 维。规划 W05 四小节（Embedding / 余弦 / 切分 / 向量库+索引），逐节讲、每节停下等反馈。

---

### 第 2 轮 · 第1节 Embedding（讲 + 语义空间图）

**我**：讲"MySQL 全文检索字面包含 vs 向量语义距离"；distributional hypothesis；语义空间图（相似句子向量近、无关远）；PHP 双类比（兴趣特征向量 / md5 雪崩 vs 对语义敏感的哈希）。留下端点伏笔。check-in：Embedding 向量检索和 MySQL 全文检索本质区别？为什么前者能捞到"把钱退回来"？

---

### 第 3 轮 · 第1节 check-in 回答

**amber**：mysql全文检索是必须要包含退款两个字才能匹配，而向量检索则是计算向量远近来匹配的

**我**：答对了。机制层：全文检索是词法（lexical）层面只看 token 是否包含，中文 ngram 也连不上"我不想要了想退货"这种换说法；向量检索是语义（semantic）层面比坐标近不近。补伏笔：全文检索仍有用（精确术语/SKU），W06 做混合检索融合。进入第2节。

---

### 第 4 轮 · 第2节 余弦相似度（讲 + check-in）

**我**：三种度量表（余弦/欧氏/点积）；为什么用余弦不用欧氏（a=(0.8,0.6) b=(0.4,0.3) 余弦=1 欧氏=0.5）；推荐系统类比；pgvector SQL（`<=>` 余弦距离，越小越像，`similarity = 1 - distance`）。check-in：① 为什么用余弦不用欧氏（一句）② SQL 返回最像还是最不像？`ORDER BY ... <=> ...` 升序还是降序在起作用？

---

### 第 5 轮 · 第2节 check-in 回答

**amber**：1. 因为embedding检索关心的是语义方向是否相近，而不是模长差距，而余弦相似度只比方向，忽略长度，刚好合适；2.最像的 排序是升序，越小的排前面，最小越像；

**我**：两个都答对。余弦原因说到点子（模长不代表语义，只比方向）；SQL 语义 `ORDER BY embedding <=> :query_vec` 升序、`<=> ` 余弦距离越小越像、LIMIT 5 拿最像 5 条。进入第3节。

---

### 第 6 轮 · 第3节 切分策略（讲 + 图 + check-in）

**我**：为什么切（上下文上限 + 粒度精度）；四种策略表（fixed/recursive/structure/semantic）；overlap=滑动窗口（PHP 时间序列移动平均类比）；recursive 是默认首选（结构优先、缺失兜底）。check-in：① 切太大/太小分别害召回出什么毛病？② 规范 Markdown 产品手册选哪种切分？

---

### 第 7 轮 · 第3节 check-in 回答

**amber**：1.切太大，会混合多个话题，太平均反而不准，而且给模型的噪音多，token还贵。切太小，容易脱离上下文，且语义有被截断的可能，产生歧义，且太分散的话排序获取时容易处于top_k范围外。2.按结构 structure，因为这个文档是比较规范的markdown格式，按结构切不容易出错。

**我**：两个都答对。补：recursive 是默认首选（结构清晰时 structure 没问题，但 recursive 在结构缺失时兜底）。进入第4节。

---

### 第 8 轮 · 第4节 向量库选型（讲 + HNSW图 + 端点选择）

**我**：为什么需要索引（O(N×D) 暴力→走索引）；pgvector/Qdrant/Chroma 表（选 pgvector：向量即列、能 JOIN/WHERE）；HNSW vs IVFFlat 表（默认 HNSW）。阶段1 收尾。进阶段2 前需敲定 embedding 端点。用 AskUserQuestion 问：本地 Ollama / OpenAI 中转 small / OpenAI 中转 large？

---

### 第 9 轮 · endpoint 提问

**amber**：中转站 Key 能不能做 embedding？阿里云百炼（DashScope）Key 行不行？

**我**：中转站能否做 embedding 取决于它是否转发 `/embeddings` 路由（不是 Key 本身）；百炼完全行且中文更优，也提供 OpenAI 兼容端点。给三方案表（中转/百炼/Ollama）+ 验证命令（bash curl）：
```bash
curl -s $BASE_URL/embeddings \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"text-embedding-3-small","input":"测试"}' | head -c 200
```
建议先试中转（已有 Key 零成本），不支持则上百炼，想离线再上 Ollama。

---

### 第 10 轮 · 验证命令改 PS 语法

**amber**：中转站 验证命令 修为PS 的语法，之前测试中转站key 那套，基于已经写好的批处理。

**我**：找到 `start-env-windows.bat` + W01 的 `env.sh`/`.env`（变量 API_KEY/BASE_URL/MODEL）。给 PS 版验证脚本，指出 PS 5.1 两个坑：① `curl` 是 `Invoke-WebRequest` 别名，用 `Invoke-RestMethod` 或 `curl.exe`；② 必须 `[Console]::OutputEncoding = UTF8` 否则 GBK 乱码；模型名别用 `$env:MODEL`（那是 chat 模型）。脚本：
```powershell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$uri   = "$env:BASE_URL/embeddings"
$model = "text-embedding-3-small"
$body = @{ model = $model; input = "测试" } | ConvertTo-Json -Compress
try {
    $resp = Invoke-RestMethod -Uri $uri -Method Post `
        -Headers @{ Authorization = "Bearer $env:API_KEY" } `
        -ContentType "application/json; charset=utf-8" -Body $body
    "OK   embedding 维度数量 = $($resp.data[0].embedding.Count)"
} catch { "FAIL: " + $_.Exception.Message }
```

---

### 第 11 轮 · 跑出 503

**amber**：FAIL: The remote server returned an error: (503) Server Unavailable. HTTP 状态 = 503 -> 404 = 中转未转发 /embeddings 路由；400 = 模型名或参数错

**我**：纠正误判：503 ≠ "不支持 embeddings"。404 是充分条件非唯一判据；503 可能是服务端临时不可用或该后端没配好。给带响应体打印 + chat 端点对照脚本定位根因：
```powershell
function Read-ErrBody($err) {
    try { $rs = $err.Exception.Response.GetResponseStream()
          $sr = New-Object System.IO.StreamReader($rs); return $sr.ReadToEnd() }
    catch { return "(读不到响应体)" }
}
# chat 对照（用 $env:MODEL）
$chatBody = @{ model=$env:MODEL; messages=@(@{role="user";content="说两个字：你好"}); temperature=0 } | ConvertTo-Json -Compress
try { $c = Invoke-RestMethod -Uri "$env:BASE_URL/chat/completions" -Method Post -Headers @{Authorization="Bearer $env:API_KEY"} -ContentType "application/json; charset=utf-8" -Body $chatBody
      "CHAT OK: " + $c.choices[0].message.content }
catch { "CHAT FAIL HTTP=" + $_.Exception.Response.StatusCode.value__ + "  body=" + (Read-ErrBody $_) }
# embeddings（打印完整响应体）
$embBody = @{ model="text-embedding-3-small"; input="测试" } | ConvertTo-Json -Compress
try { $e = Invoke-RestMethod -Uri "$env:BASE_URL/embeddings" -Method Post -Headers @{Authorization="Bearer $env:API_KEY"} -ContentType "application/json; charset=utf-8" -Body $embBody
      "EMB OK 维度 = " + $e.data[0].embedding.Count }
catch { "EMB FAIL HTTP=" + $_.Exception.Response.StatusCode.value__ + "  body=" + (Read-ErrBody $_) }
```

---

### 第 12 轮 · 贴回对照结果

**amber**：CHAT OK: ä½ å¥½  （另 EMB FAIL HTTP=503  body= 空）

**我**：结论实锤：① CHAT OK → 账号没问题（否则 chat 也 503）；② EMB 503 空 body + chat 正常 → 中转只代理 chat、embeddings 路由没接。路径①排除。那行 `ä½ å¥½` 是"你好"的 UTF-8 被当 Latin-1 显示的乱码（PS 5.1 编码坑），数字不受影响，对判断无害。给出百炼 vs Ollama 二选一（AskUserQuestion）。

---

### 第 13 轮 · 选百炼

**amber**：（AskUserQuestion 选择）阿里云百炼

**我**：联网核百炼 2026 现状。`text-embedding-v3`（1024维） vs `text-embedding-v4`。给三步走：① 开 Key（百炼控制台）② 改 `start-env-windows.bat` 的 BASE_URL 为 `https://dashscope.aliyuncs.com/compatible-mode/v1`（结尾含 /v1 符合规则）③ 跑验证。提示百炼批次上限 ≤10 条（v3/v4）、`dimensions` 参数固定 1024 对得上 `vector(1024)`。

---

### 第 14 轮 · 问 qwen3.7-text-embedding-flash

**amber**：模型使用 qwen3.7-text-embedding-flash 是否可以？

**我**：联网核实：该模型不仅能用且优于 `text-embedding-v3`——1024 维、20 条/批、单行 128000 token、¥0.125/百万、201 语种、带 sparse（利于 W06）。更正之前"百炼单批≤10"的说法（那是 v3/v4，flash 是 ≤20）。维度仍 1024，`vector(1024)` 不变。给验证命令（PS）：
```powershell
$model = "qwen3.7-text-embedding-flash"
$body = @{ model=$model; input="测试"; dimensions=1024 } | ConvertTo-Json -Compress
try { $e = Invoke-RestMethod -Uri "$env:BASE_URL/embeddings" -Method Post -Headers @{Authorization="Bearer $env:API_KEY"} -ContentType "application/json; charset=utf-8" -Body $body
      "OK  维度 = " + $e.data[0].embedding.Count + "  usage_tokens=" + $e.usage.prompt_tokens }
catch { "FAIL HTTP=" + $_.Exception.Response.StatusCode.value__ + "  " + $_.Exception.Message }
```

---

### 第 15 轮 · 百炼通了

**amber**：OK  维度 = 1024  usage_tokens=17

**我**：通了，维度 1024 对得上 `vector(1024)`。endpoint 敲定百炼 `qwen3.7-text-embedding-flash`。进阶段2，写全套脚本：00 起 pgvector / 01 建索引（递归切分+百炼embedding+入库+HNSW）/ 02 余弦查询（top_k/阈值可调）/ 03 bad case（fixed 硬切演示劈句）/ requirements / sample_doc。用 managed python 做语法检查通过。

---

### 第 16 轮 · 阶段2 脚本套件 + 语法检查

**我**：生成 `w05-scratch/` 全套文件，给执行步骤（起库 / 注入 env / 跑 01 02 03）。语法检查命令：
```powershell
python -m py_compile 01_build_index.py 02_query.py 03_bad_case.py
```
结果：`py_compile OK: 三个脚本语法均通过`。

---

### 第 17 轮 · 起 pgvector（Docker Desktop）

**amber**：用 docker desktop run了一个pgvector 17  5432:5432  配置是默认的，后续还需要如何配置？

**我**：默认 `pgvector/pgvector:pg17` = Postgres 17 + 预装 pgvector，但连接参数对不上脚本（用户 postgres、库 postgres，脚本写死 amber/w05rag）。给补建环境命令：
```bash
docker ps --format "{{.Names}}\t{{.Image}}"
docker exec -i <容器名> psql -U postgres -W <PGPASS> -c "CREATE USER amber WITH PASSWORD 'amber123' SUPERUSER;"
docker exec -i <容器名> psql -U postgres -W <PGPASS> -c "CREATE DATABASE w05rag OWNER amber;"
# 验证
docker exec -i <容器名> psql -U amber -d w05rag -c "SELECT 1;"
```

---

### 第 18 轮 · 跑 01 + 02 输出

**amber（终端输出，路径已脱敏）**：
```
w05-scratch> python .\01_build_index.py
切分完成：4 个 chunk（chunk_size=400, overlap=80）
...
已 embedding 第 1~4 条
入库完成，chunks 总数： 4

w05-scratch> python .\02_query.py "退款多久到账"
查询：退款多久到账 ｜ top_k=5 阈值=0.0 ｜ 命中 4 条：
#2  sim=0.6482  （退款政策段，含"银行卡退款需3至7个工作日"）
#3  sim=0.5118
#1  sim=0.4552
#4  sim=0.1877  （数据导出 API，噪声）
```

**我**：01/02 跑通。分析：召回正确（答案块排第一且整句完整）；但 sim=0.65 偏低，根因是 chunk[1] 混了账户登录 80 字 overlap 尾巴稀释退款语义。让对方跑实验 A（top_k/阈值）和实验 B（切分 120/0 对比）。同时我发现 03 第一版结论写错（说"银行卡退款"被劈，实际被劈的是前一句），修正 03 并重跑验证。

---

### 第 19 轮 · 实验 A/B 输出（本次，收尾前）

**amber（终端输出，路径已脱敏）**：
```
w05-scratch> python .\02_query.py "退款多久到账" 20 0 --show-all
  #2  sim=0.6482  /  #3  sim=0.5118  /  #1  sim=0.4552  /  #4  sim=0.1877

w05-scratch> python .\02_query.py "退款多久到账" 3 0
  命中 3 条：#2(0.6465) / #3(0.5103) / #1(0.4548)   （#4 被 top_k 砍）

w05-scratch> python .\02_query.py "退款多久到账" 5 0.3
  命中 3 条：#2(0.6445) / #3(0.5123) / #1(0.4549)   （#4(0.19)<0.3 被剔）

w05-scratch> python .\01_build_index.py
  切分完成：18 个 chunk（chunk_size=120, overlap=0）
  入库完成，chunks 总数： 18

w05-scratch> python .\02_query.py "退款多久到账"
  命中 5 条：#5(0.7310) / #4(0.6344) / #3(0.6006) / #10(0.5326) / #9(0.5141)
```

**我**：实验 A/B 数据理想，亲手实证"切分是召回质量头号开关"的 nuanced 结论：
1. 实验 B 最佳块 0.6482→0.7310，"切太大→平均后不准"被实证（默认块混账户登录尾巴稀释语义）。
2. 但 120/0 不是好配置：零 overlap 有劈句风险（03 已证）、18 块存储翻 4.5 倍、长文档相关块易被挤出 top_k。
3. 没有一刀切的 chunk size，适中 + 合理 overlap（400/80）是稳健默认，按文档和查询类型调。
验收对照诚实披露：BM25 混合检索留 W06，本周只做到"向量 + WHERE 混合 SQL"。

⚠️ 指出：01 文件他已改回 400/80（Read 证实），但库里还是 18 chunks 残留（改完没重跑），需重跑 01 恢复 4 chunks 正式库（W06 基于它）。进入阶段4 收尾，按 course-week-finalize 八步流水线整理产出。

---

### 附：本轮（第 19 轮后）已完成的收尾动作

- 复制 w05-scratch 确定文件到 `week-05/code/`（含 `.env.example` + `code/README.md`），清理临时文件。
- 写 `week-05/README.md`（十节结构，含实验 A/B 真实数据 + 混合 SQL + 诚实披露）。
- 写 `week-05/DIALOGUE.md`（提炼版 + 给 AI 的复现指令 + 方法论）。
- 写本文件 `DIALOGUE-QA.md`（逐轮底稿）。
- 待写：`week-05-learning-log.md`（工作空间根）、更新 `PROGRESS.md`、红线扫描。
- 待 amber 本机重跑 `python .\01_build_index.py` 恢复 4 chunks 正式库。
