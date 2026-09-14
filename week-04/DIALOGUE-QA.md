# W04 · 学习对话逐轮底稿（DIALOGUE-QA）

> 这是 W04 的**逐轮一问一答底稿**，未做归纳压缩。
> 只收技术相关问答；制定规则、调整课表、产出管理这类元话题不收。
> 完整提炼版见 [DIALOGUE.md](DIALOGUE.md)。
>
> 说明：文中 `<本地 agent_runtime schema 文件>` 指代学习者本地预置的一份 SQL 建库脚本，
> 原始路径不写入公开仓库（红线约束）。

---

### 第 1 轮 · 触发

**amber**：开始W04课程

**我**：按约定走「阶段1 引导学习」：先读课表 W04 条目和上次进度，逐小节讲、每节停下等反馈。读 `agent-course-weekly-workflow.md` / `CURRICULUM.md` / `week-03-learning-log.md`。宣布进入第 1 节：ReAct（W03 的 while 循环本质就是 Action→Observation→Action，已经是 ReAct 了，本周只是显式结构化 Thought/Action/Observation）。

---

### 第 2 轮 · 第 1 节 ReAct + 反馈

**我**：讲 W03 循环 = ReAct 三段（Thought=assistant content / Action=tool_calls / Observation=tool 消息）。强调 ReAct 不是新框架，是"提示+循环"范式。类比 Controller 多步业务编排。问：用一句 PHP/Laravel 的话概括，ReAct 循环和 controller 里写死的 5 步 if-else 业务流程最大区别是什么。

**amber**：react 循环 模型自己判断安排下一步做什么，拿到结果后再干什么，而 controller内则是固定流程，只能根据预设的参数判断该执行什么；

**我**：接住，补精度——工具集合（能调哪些 Service）是固定的，但"下一步调哪个、传什么参、调完怎么走"是模型运行时根据 Observation 现编的。区别是"开发者预设流程 vs 模型运行时编排"。进入第 2 节。

---

### 第 3 轮 · 第 2 节 记忆三层 + 反馈

**我**：讲痛点（messages 每轮变长→撑爆窗口/更贵/噪声）与记忆三层：①历史（全留，未必每轮发）②摘要压缩（过程推理压成叙事）③外部存储（事实数据用时再取）。分水岭：摘要压"过程推理"，外部存储存"事实数据"。问：一个订单详情接口返回 3k token，ReAct 循环跑了 12 轮，该用摘要压缩还是外部存储，为什么。

**amber**：外部存储，这部分数据属于查询出来的详情数据，不应该放进会话，只需要在需要用的时候，使用即可，也不适合当摘要压缩，会失真，会变为脏数据。

**我**：完全正确，"失真/脏数据"精准。补边界钉死：②摘要压过程推理（压了不出事），③外部存储存事实数据（压了会改值变脏）。那 3k token 走外部存储，对话只留"已查 NO2026… 状态=shipped"。进入第 3 节。

---

### 第 4 轮 · 第 3 节 防护四件套 + 反馈

**我**：讲在 W03 `MAX_STEPS` 基础上补全四件：①步骤上限（Laravel 队列 tries 类比）②超时（Guzzle timeout 类比）③token 预算（接口限流类比）④重复调用检测（Stripe Idempotency-Key / Laravel 队列 unique 类比）。问：重复调用检测里怎么定义"重复"——同一个工具名就算，还是必须工具名+参数都一样，分别带来什么误杀/漏杀。

**amber**：工具名+参数 一样才算重复， 如果单工具名，不同参数的查询就都会被误杀

**我**：对，点出只按工具名会杀掉"查订单A→查订单B→查订单C"正常推进。补一级：纯"工具名+参数"漏杀"换参数打转"（A失败B失败C失败），所以生产叠二级熔断（同工具连续失败N次也拦）。本周造死循环是"同一失败调用反复重放"（参数相同），标准定义直接命中。进入第 4 节。

---

### 第 5 轮 · 第 4 节 审计落库 + 实操全景，问两件事

**我**：讲建两张表 runs(主表)+steps(明细) 1:N，把 ReAct 三段和防护状态落库，回放用 `SELECT * FROM steps WHERE run_id=?`。给出 W04 实操六步全景。确认两件事：①业务场景用订单→物流→退款 OK 吗还是换财报；②本地有 MySQL 吗还是先用 SQLite。

---

### 第 6 轮 · amber 抛出本地预置库 + 配置

**amber**：本地数据库 已经配置了一套 `<本地 agent_runtime schema 文件>`，本地数据库连接用这套配置 DB_CONNECTION=mysql / DB_HOST=127.0.0.1 / DB_PORT=3306 / DB_USERNAME=root / DB_PASSWORD=（空）；修改下课程，用这套数据库配置是否能达到效果，或者看那些有缺失字段需要补充？

**我**：先连库验证（用 managed Python + pymysql，root 空密码本地登录正常，11 张表齐全，`runs`/`steps` 空）。做覆盖度核对：这套库是 W04 需求超集，且提前铺好 W05 RAG / W13 评测 / W02 提示词版本化表。指出缺口：①`messages` 缺 `kind`+`metadata`（摘要压缩标记）②`runs.agent_id` NOT NULL 需先 seed agents 一行。可选增强：`steps.guardrail/dedup_key`、`runs.ended_reason`。

---

### 第 7 轮 · 覆盖度结论 + 待拍板

**我**：结论——这套配置完全能达到 W04 效果，且是超集。唯一真缺口是 Layer2 摘要压缩缺 `messages.kind` 标记（不补也能跑但回放会混），另外 `runs.agent_id` 非空、跑首个 run 前得先 seed agents。已把 CURRICULUM.md 的 W04 加「数据模型」行对齐。用 AskUserQuestion 让他拍板：①是否让我跑 ALTER 补 messages.kind（+可选增强）②业务场景用哪个。

---

### 第 8 轮 · amber 决策

**amber**（AskUserQuestion 选择）：选「必须项+可选增强全补」+ 场景保持「订单→物流→退款」。

**我**：执行 ALTER 补字段并 seed agents 行。命令（managed Python + pymysql，幂等保护）：

```python
# 必须项：摘要压缩标记
ALTER TABLE messages ADD COLUMN kind VARCHAR(16) NULL COMMENT 'normal/summary/system' AFTER role
ALTER TABLE messages ADD COLUMN metadata JSON NULL COMMENT '扩展信息' AFTER content
# 可选增强：审计自解释
ALTER TABLE steps ADD COLUMN guardrail VARCHAR(32) NULL AFTER status
ALTER TABLE steps ADD COLUMN dedup_key VARCHAR(128) NULL AFTER guardrail
ALTER TABLE runs ADD COLUMN ended_reason VARCHAR(32) NULL AFTER status
# seed agents（runs.agent_id NOT NULL）
INSERT INTO agents (name, slug, model, status, created_at, updated_at)
VALUES ('退款运维Agent','refund-agent','deepseek-v4-flash',1,NOW(),NOW())
```

全部落库成功，验证通过。进阶段2 实操，读 W03 的 `agent.py`，写升级版 `w04-scratch/agent.py`。

---

### 第 9 轮 · 写代码 + mock 验证 + 让本机跑真实

**我**：写 `w04-scratch/agent.py`（ReAct 三段记录 + 四件套 + agent_runtime 落库 + 退款场景）。修复两个内部 bug：①`messages.conversation_id` NOT NULL → 每 run 建 conversations 行；②摘要压缩会摘掉已执行工具对 → mock 改用独立 `done_tools` 状态。mock 三场景跑通（正常退款 done / 死循环 `--deadloop` guarded / 不可退 done）。让他本机跑真实模式：

```
双击 start-env-windows.bat        # 仓库外那份，已填 Key，注入 API_KEY/BASE_URL/MODEL
cd 到 w04-scratch 目录
python agent.py                   # 真实 LLM 跑 ReAct + 落库
python agent.py --order NO20260911002   # 测不可退分支
W04_DEADLOOP=1 python agent.py    # 测死循环防护
```

---

### 第 10 轮 · amber 第一跑报错 400

**amber**（贴 Traceback）：真实模式第 4 轮崩溃 `urllib.error.HTTPError: HTTP 400: Messages with role 'tool' must be a response to a preceding message with 'tool_calls'`。前 3 轮正常（查订单、查物流、判定、执行退款），第 4 轮最终回答前炸。

**我**：定位根因——旧 `maybe_compress` 按 tool 索引切分，第 3 轮末把 `assistant(tool_calls)` 删了却留下它的 tool 响应，制造悬空 tool 响应。前 3 轮没报错因压缩在第 3 轮末才首次触发。修复：①`maybe_compress` 按"完整工具交互块"为单元整块保留/压缩；②`KEEP_RECENT` 3→2；③新增 `validate_messages` 防御校验 + 发请求前拦截（带诊断）；④修 `validate_messages` 自身误报（一个 assistant 多个 tool 响应连续排列合法）。

---

### 第 11 轮 · 修复验证

**我**：写临时单元测试覆盖"他报错同款 3 块场景 + 4 块场景 + 不压缩场景 + 旧逻辑复刻"，新逻辑 validate 零问题、旧逻辑确认悬空。mock 整体重跑 5 轮 `status=done`。清理调试脏 run，让他重跑真实模式。

---

### 第 12 轮 · amber 重跑成功 + ④ 真实未触发

**amber**（贴真实输出）：三个场景全 done——
- `python agent.py` → run9 正常退款（4 轮，tokens≈363，第3轮压缩 8→6）
- `python agent.py --order NO20260911002` → run10 不可退款（3 轮，tokens≈318）
- `$env:W04_DEADLOOP=1; python agent.py` → run11 物流故障（6 轮，tokens≈407，物流两次500后模型自愈跳判定）

并说："正常了"

**我**：查库确认落库可回放。但指出关键发现：run11 里模型只重试 1 次物流就跳去 decide_refund，**死循环防护④ 在真实模式没触发**（因为真实模型自愈，没产生死循环），④ 的实证仍在 mock run5（`guarded/repeat`）。这反而验证了"真实模型优雅降级"比"被兜底拦下"更优。清理 mock 调试残留（run4/6/8），保留 run5（④证据）+run9/10/11（真实三场景）。进阶段4 汇总产出。

---

### 第 13 轮 · 进阶段 4

**我**：加载 `course-week-finalize` skill 走八步流水线。先读上下文（PROGRESS / 模板 / W03 成品结构），建任务清单，开始复制代码 + 写正文 + 写对话实录。本回合进入收尾生产。

---

## 关键技术决策记录（不丢）

1. **数据库选型**：用 amber 本地预置的 `agent_runtime` 库（MySQL 8.0，root 空密码），而非 SQLite。理由：库已是 W04 需求超集，且提前铺好 W05+/W13 表，一次性建好运行时底座。
2. **补字段**：必须项 `messages.kind/metadata` + 可选增强 `steps.guardrail/dedup_key`、`runs.ended_reason`，全部 ALTER 幂等执行。
3. **seed agents**：`runs.agent_id` NOT NULL，跑首个 run 前插 `slug=refund-agent` 一行。
4. **业务场景**：保持「订单→物流→退款」通用电商场景，不挂钩毕业项目（前期周次约定）。
5. **压缩单元**：以"assistant(tool_calls) + 其全部 tool 响应"为不可分割单元，解决 OpenAI 协议悬空问题。
6. **重复检测 key**：工具名 + 规范化参数，连续 >3 次拦截；标准定义命中"同失败调用重放"，漏杀"换参数打转"靠二级熔断补（本期未实现，已注明）。
7. **④ 验收披露**：mock 实证 guarded/repeat，真实模式未触发（模型自愈）如实写进正文，不假装真实拦下。
