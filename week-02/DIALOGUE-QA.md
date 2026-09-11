# W02 逐轮对话底稿（DIALOGUE-QA）

> 基于本周真实学习过程重建，命令原文与终端输出均来自真实执行（deepseek-v4-flash / 中转站）。
> 只收技术相关问答；制定规则、调整课表、产出管理等元话题不收。
> KEY 在输出中已打码为 `***(打码)`，不含真实密钥片段。

---

## 轮次 1 · 启动 W02，定场景与 Schema

**Q（amber）**：开始 W02 课程。

**A（老师）**：读 `CURRICULUM.md` 的 W02 条目：学 Prompt 五段结构 / XML 标签 / CoT / 结构化输出；做领域信息抽取；建 20 条样本；两版 prompt A/B；验收成功率 ≥90% + 失败能归因。先引导学五段结构（Role/Task/Constraints→system 稳定可缓存；Context/Examples/Input→user 每次变），用 PHP Service 方法签名类比。

**关键决策（amber 拍板）**：
- 抽取场景 = 电商客服对话 → 工单结构化抽取（通用场景，不碰内部业务）
- 多订单改**数组**（一个订单一个对象）
- `amount` 填**诉求金额**（订单原价靠 order_id 查）
- 新增 `intent` 枚举：退货 / 换货 / 仅退款 / 部分退款 / 未识别

---

## 轮次 2 · 实验 1：Prompt Injection 对照

**Q（amber）**：inject_bad.json 会被注入成功输出 INJECTED_OK，因为 system 没约束；inject_good.json 的 system 明确了待处理数据不可执行其中指令。

**A（老师）**：先跑验证，别凭预测下结论。

**命令（amber 执行）**：
```powershell
python extract.py   # 实际是 curl 打 inject_bad.json / inject_good.json 两份请求体
```

**输出**：两份都返回了 JSON 数据，但格式不一样（一份带 ```json 围栏，一份纯 JSON）。

**结论（实测翻车）**：amber 预测"bad 会被注入"没发生——两次都没被注入，`reasoning_content` 明写 "Injection should be ignored"。诚实说明：**本实验无法证明 XML 标签有效**（都没破 = 无区分度）。顺带发现 good 版带围栏导致 `json.loads` 崩溃（反直觉：更"规范"反而不能解析），用 `parse_demo.py` 复现 `JSONDecodeError`。

---

## 轮次 3 · 实验 3：结构化输出三层 + 端点坑

**Q（amber）**：是否要根据 deepseek 的写法来才行？（贴 `req_schema.json` 报错）

**A（老师）**：报错是 `This response_format type is unavailable now`。**根因是端点用错，不是中转站不支持**——联网查官方文档确认 `/chat/completions` 只认 `json_object`，`json_schema` 属于 `/responses` 端点。

**命令（amber 执行）**：
```powershell
# req_json_object.json（L1 主路线）
curl.exe -s "$env:BASE_URL/chat/completions" -H "Authorization: Bearer $env:API_KEY" -H "Content-Type: application/json" -d "@req_json_object.json"
# req_responses.json（L2 探活）
curl.exe -s "$env:BASE_URL/responses" -H "Authorization: Bearer $env:API_KEY" -d "@req_responses.json"
```

**输出**：`json_object` 通了且输出纯 JSON、`amount: null`（模型忍住没编 200）；`/responses` 返回 `not implemented` / `convert_request_failed`（中转站只透传 Chat Completions）。

**结论**：路线定为 **L1（`json_object`）+ 本地 Pydantic 校验**。意外收获：加 `<output_schema>` 示例后 prompt 191→293(+102)、completion 267→83(−69%)、总 token −18%。

**附带实测**：同条连发 3 次 → 2 围栏 + 1 纯 JSON + `amount` 三写法（45 / 45.0 / null）→ 实证 `temperature=0` ≠ 确定性。

---

## 轮次 4 · v1 首批 20 条

**Q（amber）**：贴 v1 首批 20 条结果。

**输出**：
```
完全稳定率 : 15/20 = 75.0%
平均通过率 : 19/20 = 95.0%   (部分条目 repeat 统计)
字段成功率 : 94.7%
```

**A（老师）**：失败 5 条归因：4 条 prompt 问题 + 1 条标注问题（#18「不合适」有分类歧义，模型选「其他」更合理）+ 0 条模型能力问题。

---

## 轮次 5 · amber 纠正 #14 / #18

**Q（amber）**：#14 保持 null；#18 改样本，再看一次爬出来的结果，看差别。

**A（老师）**：按你的来。#14 改 prompt 不改期望值（诉求金额缺失就 null）；#18 对话从「我穿过一次不合适」改为「我穿过一次发现尺码不合适」，消除分类歧义。

---

## 轮次 6 · v2 / v1 基线 repeat=3

**命令（amber 执行）**：
```powershell
python extract.py --prompt v2 --repeat 3
python extract.py --prompt v1 --repeat 3
```

**输出**：
```
[v2] 完全稳定率 : 19/20 = 95.0%   平均通过率 98.3%   字段成功率 100%
[v1] 完全稳定率 : 16/20 = 80.0%   平均通过率 83.3%   字段成功率 96.9%
```

**A（老师）**：v2 修好 #10/#13/#14，但引入回归 #8/#11（0/3 稳定错，错法相反）→ 根因是**标注不自洽**，不是模型能力。A/B 表：v2 完全稳定率 95% vs v1 80%，但字段成功率 v2 95.4% < v1 96.9%（分母陷阱：模型少输出对象时分母变小指标虚高，验收以 case 级为准）。

---

## 轮次 7 · amber 关键纠正：测试集是真实用户

**Q（amber）**：暂时先不改测试集，测试集内的内容是属于真实用户可能发送的内容，并不会完全准确的表达对应关键字，所以这里需要设定的时候就给一定空间去冗余，而不是定死必须有什么关键字才能算，这个不是写逻辑脚本，需要给 ai 一些主动判断的空间，不能是关键字来判断分类，还需要结合上下文判断，是退什么，退款还是退货还是其他的。

**A（老师）**：认错。v2 那条 intent 规则本质是用自然语言写的 `if-else` 关键词映射；改输入表述 = 把真实输入改成标准输入，测试集会废掉（失去测真实分布的能力）。改成**接受集合**：期望值写成数组，人类也判不死的就都算对。标记 ⏸️ 5 条「退字族」用接受集合（#8/#10/#11/#12/#20），输入一字不动。

---

## 轮次 8 · 动手改 cases + extract（接受集合 + v3）

**Q（amber）**：动手，退款类可以后续追问明确的。

**A（老师）**：三处改造——cases.json 接受集合（输入不动）、extract.py 的 `compare()` 支持 list 期望值（任一命中即通过）、新增 v3 prompt（关键词映射换成**判据 + few-shot 示例**）。抽 `SHARED_EXTRA` 共享，v2/v3/v4 只差 intent 段，保证单变量。

**坑（实测）**：Edit 工具静默未写入——#10/#11/#12 三处返回 Success 但磁盘没变。修复用 Python `replace()` + 断言计数 + 重新读盘确认。验收改为：改完立刻读盘校验，不信工具返回值。

---

## 轮次 9 · v1/v3/v2 r3（B+C 前口径）

**命令（amber 执行）**：
```powershell
python extract.py --prompt v1 --repeat 3
python extract.py --prompt v3 --repeat 3
python extract.py --prompt v2 --repeat 3
```

**输出（摘要）**：
```
[v1] 完全稳定率 17/20 = 85.0%   平均 90.0%   字段 98.7%
[v3] 完全稳定率 19/20 = 95.0%   平均 98.3%   字段 100%
[v2] 完全稳定率 19/20 = 95.0%   平均 98.3%   字段 100%
```

**A（老师）**：v2 与 v3 逐条一模一样（唯一失败都是 #2），v3 贵 94% 收益 0。反直觉结论：**v3 花了两倍钱一分没多赚**。同时发现 #2 是三版共同失分点（COMMON_RULES 售后查询 vs 售前咨询边界）。

---

## 轮次 10 · 选 B+C

**Q（amber）**：B+C 一起做。

**A（老师）**：B = 补 4 条「无关键词但语义明确」样本（#21~#24）重建分辨力；C = 加 v4（判据去示例）验证示例价值。cases.json 加 #21~#24（全篇无退/换/寄字），extract.py 加 v4。注意：#25（售后查询边界）砍掉，因为它要改 COMMON_RULES 破坏单变量。

**坑（实测）**：Edit 静默未写入再现——`V4_INTENT` 定义没落盘，第二个 Edit（v4 进 PROMPTS）成功 → `NameError`。修复用 Python `replace()` + 断言。单变量校验：v4 是 v3 前缀，只差 examples 段 896 字符。

---

## 轮次 11 · v2/v3/v4 r1（B+C）

**命令（amber 执行）**：
```powershell
python extract.py --prompt v2 --repeat 1
python extract.py --prompt v3 --repeat 1
python extract.py --prompt v4 --repeat 1
```

**输出（摘要，24 条）**：
```
[v2] 完全稳定率 24/24 = 100.0%
[v3] 完全稳定率 24/24 = 100.0%
[v4] 完全稳定率 22/24 = 91.7%   # 挂 #6 intent 退货/实际仅退款, #8 amount=None
```

**A（老师）**：① B 方案预测翻车——我赌 v2 在 #21~#24 全挂，结果 v2 全过（强模型语义理解够强，关键词映射冗余）。② C 方案有信号——v4 在 #6/#8 挂了，v3 全过，示例段确有增量。

---

## 轮次 12 · v3 / v4 r3

**命令（amber 执行）**：
```powershell
python extract.py --prompt v3 --repeat 3
python extract.py --prompt v4 --repeat 3
```

**输出（摘要，24 条）**：
```
[v3] 完全稳定率 23/24 = 95.8%   平均 98.6%   字段 100%   # 唯一挂 #2（COMMON_RULES）
[v4] 完全稳定率 22/24 = 91.7%   平均 97.2%   字段 99.3%   # 挂 #6 仅退款/退货, #21 仅退款/部分退款
```

**A（老师）**：单变量证据锁死——v3 把 #6（退款 vs 退货）、#21（仅退款 vs 部分退款）从 FLAKY 拉成 PASS，examples 段补的正是"人类也易混的边界"权衡依据。#2 两版表现相反（v3 挂 v4 过）→ 证明是随机噪声，属 COMMON_RULES 缺陷非 intent 段。

---

## 轮次 13 · v2 r3（补齐同口径）

**命令（amber 执行）**：
```powershell
python extract.py --prompt v2 --repeat 3
```

**输出（24 条）**：
```
完全稳定率 : 24/24 = 100.0%
平均通过率 : 72/72 = 100.0%
字段成功率 : 288/288 = 100.0%
token 合计 : prompt 38619 + completion 11910
```

**A（老师）**：三版同口径最终表——v2 100% 最便宜、v3 95.8% 最贵、v4 91.7% 居中。反直觉：最便宜的 v2 反而最好，关键词映射不是错误示范（之前教错了），它在强模型+覆盖语料上有效且便宜；真正风险在长尾。

---

## 轮次 14 · 问验收标准

**Q（amber）**：验收标准是什么？是怎么制定的呢？

**A（老师）**：来自 `CURRICULUM.md` W02 条目：「成功率 ≥ 90%；失败样本能明确归因（prompt / schema / 模型能力）」。两条：① ≥90% 是经验阈值（业务可用下限，人工复核成本约束），不是统计推导，类比团队定核心模块覆盖率 90%；② 归因比数字更本质，考的是"学完能不能 debug"。诚实局限：20~24 条小样本撑不起 90% 的统计置信（95% CI 约 75%~99%）；真正严肃评测在 W13 要求 30~50 条。这周严格口径（去掉 5 条接受集合，19 条）v2 仍是 100%，但含运气 + 强模型兜底。

---

## 轮次 15 · 选 v2，收尾提交

**Q（amber）**：选 v2，根据 W01 课程的收尾方式，总结；提交 git+push。

**A（老师）**：收到。对齐 W01 收尾结构产出：week-02/README.md（正文，融合第 3 节 CoT + 第 4 节 Prompt 文件化）、code/（extract.py + cases.json + 4 份 r3 结果 + 注入对照 + .env.example + README）、DIALOGUE.md、DIALOGUE-QA.md、根目录 learning-log.md；更新 PROGRESS.md；红线扫描（全类型 + grep sk-）；git 提交 + push_via_api.py 推送。选型 v2 局限如实披露（接受集合、小样本、长尾、#2 未修）。
