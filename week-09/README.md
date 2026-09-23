# W09 · 毕业项目 MVP：财报与可转债分析 Agent 的数据地基

> Agent 开发实战 15 周 · 第 9 周 · 约 16 小时
>
> 一句话钩子：**RAG 再强也救不了「扣非净利润」和「归母净利润」的混淆——因为它们在语义上太像了。字段级归一化才是唯一解。**

## 开篇：这周要解决什么问题

前面 W06 做过一个断言：向量 + BM25 + 重排「三道防线」救不了语义相似的块。当时没实锤，这周在毕业项目里正面撞上了。

做财报分析 Agent，第一步是把 PDF 年报里的科目，对齐到你指标库里的标准字段。问题来了：

- 「归属于上市公司股东的净利润」= 归母净利润
- 「归属于上市公司股东的**扣除非经常性损益的**净利润」= 扣非净利润
- 「净利润」= 又一个独立字段

这三个在语义空间里距离极近。向量检索会把「扣非净利润」的块，召回成「归母净利润」的块——**RAG 检索层的任何技巧都分不开它们**，因为它们本来就是相邻的合法概念。硬要把错块喂给模型，模型也会照错不误。

所以 W09 不碰检索，先解决更底层的事：**字段级归一化**（field-level normalization）。这是毕业项目（财报 + 可转债分析 Agent）的数据地基，也是后续 6 周迭代的基线。

## 核心结论（先给答案）

1. **双运行时**：Python 负责 Agent 全部智能（编排 / 归一化 / 抽取），Laravel 只做接入层四件事——HTTP 消费、SSE 转发、队列长任务、最简查询页。**Laravel 一行 Agent 逻辑都不写。**
2. **指标语义层是硬指标的唯一承载体**：四级匹配（L1 精确 / L2 规则 / L3 模糊 / L4 向量）+ L0 unknown 队列，配合否定词保护、易混淆组冲突检测、近似指标守卫，才能做到「扣非 / 归母零误匹配」。
3. **unknown 不是兜底垃圾桶**：精准可识别的字段，绝不许因为"演示方便"被塞进 unknown。unknown 只收容 legit 的、确实无法归类的字段。
4. **SSE 在 PHP 端有三个真实坑**：返回类型协变、PSR-7 Stream 不可遍历、清缓冲后无脑 `ob_flush()`。三个都踩了，全修在控制器里。
5. **MVP 验收达成**：3 家真实公司（茅台 / 宁德 / 比亚迪）跑通「取数 → 抽取 → 归一化 → 入库 → 问值」，6 个科目全 L1 精准匹配，`zero_mismatch: true`。

## 一、概念：两个边界到底划在哪

### 1.1 双运行时边界（用 PHP/Laravel 类比）

如果你做过 Laravel 后台，这么理解最顺：

| 角色 | 类比 | 职责 |
|---|---|---|
| **Python（FastAPI + LangGraph）** | 你项目里的「领域服务层 + 队列 Worker」 | 所有智能逻辑：归一化、抽取、编排、状态持久化 |
| **Laravel** | 你项目里的「HTTP 层 + 后台页面」 | 只消费 Python 暴露的 HTTP/SSE，转发给浏览器，不重算 |

铁律：**Laravel 不写 Agent 逻辑**。就像你不会在 Controller 里写一遍业务规则再在 Service 里写一遍——Python 是唯一的"真相来源"，Laravel 只是个转发代理。

为什么不复用 PHP 写 Agent？W03–W08 已经把"零框架循环 → ReAct → LangGraph 工程化"完整走了一遍。再用 `laravel/ai` 写第二遍，只是换语法重复已掌握的知识，不产生新能力。PHP 的价值留在它无可替代的地方：接入层、队列、权限、事务、审计、上线。

### 1.2 指标语义层（用 SQL 类比）

指标语义层 = 一张「原始科目名 → 标准字段」的映射字典 + 一套匹配规则。类比 SQL：

- **L1 精确匹配** = `WHERE raw_name = '营业总收入'` 的精确等值
- **L2 规则匹配** = `WHERE raw_name LIKE '%扣除非经常性损益%'` 的正则/包含
- **L3 模糊匹配** = 子串/相似度（**带禁区**：扣非类修饰词触发时禁用）
- **L4 向量匹配** = embedding 相似（**禁用**：正是 RAG 救不了的场景）
- **L0 unknown** = 以上都没中，进人工审核队列

关键保护机制（这是"零误匹配"的真正护城河）：

- **否定词保护**：raw_name 含「扣非 / 扣除 / 非经常 / 母公司」等修饰词时，强制禁止走 L3/L4 模糊匹配——因为这些词恰恰是"长得像但意思不同"的重灾区。
- **易混淆组冲突检测**：`NP_PARENT`（归母）和 `NP_DEDUCT`（扣非）标记成易混淆组。如果一条记录同时能匹配两者，必须显式区分，不能靠模糊匹配赌。
- **近似指标守卫**：`BASIC_EPS`（基本每股收益）和 `DILUTED_EPS`（稀释每股收益）是近似指标，L3 子串不能把"稀释每股收益"吸进 `BASIC_EPS`。
- **数量级校验**：同一公司扣非应 < 归母（差 > 0.01 亿视为两者都被正确识别）。这是验证信号，不是硬不等式——用来兜底发现"误匹配导致两者相等"的事故。

## 二、动手：从零实现这条链路

### 2.1 建库 + 冷启动字典

5 张表：`fin_companies` / `fin_reports` / `fin_indicators`（标准字段字典）/ `fin_report_items`（抽取落库）/ `fin_indicator_unknown`（未命中队列）。

```bash
python init_db.py          # 建表
python seed_indicators.py  # 冷启动 11 个科目，含 NP_PARENT/NP_DEDUCT 易混淆组
```

字典种子里，`NP_DEDUCT` 标了 `requires_modifier_guard=1`（必须出现"扣除"修饰词才允许匹配），`BASIC_EPS` 的 alias 收紧为"每股收益(基本)"避免吞掉"稀释每股收益"。

### 2.2 归一化：四级匹配 + 保护

`normalize.py` 的核心逻辑（节选）：

```python
def normalize(raw_name, **kw):
    # L1 精确
    if raw_name in EXACT:
        return matched(EXACT[raw_name], "L1")
    # L2 规则
    for pat, code in RULES:
        if re.search(pat, raw_name):
            return matched(code, "L2")
    # 否定词 guard：含"扣非/扣除/非经常/母公司"→ 禁止 L3/L4 模糊
    if has_modifier(raw_name):
        # 只在明确规则里找，不走模糊
        ...
    # L3 模糊（近似指标守卫：稀释每股收益 ≠ 基本每股收益）
    cand = fuzzy_match(raw_name)
    if cand and not is_nearby_conflict(cand, raw_name):
        return matched(cand, "L3")
    # L4 向量：本项目禁用（RAG 救不了语义相似块）
    # 都没中 → L0 unknown
    return unknown(raw_name)
```

### 2.3 LangGraph 编排（复用 W08 三件宝贝）

图是流水线 DAG + 一处人工批准：

```
START → classify → extract_node → human_review(interrupt) → normalize_persist → verify → END
```

`human_review` 节点复用 W08 的 `interrupt()`：批量写库前挂起，等人批准。流式问值路径（`/agent/query`）用 `auto_approve=True` 跳过 interrupt 直接批准；批量导入路径（`/agent/import`）挂起返回 `thread_id`，前端带 `thread_id + confirm` 续跑。

`verify` 节点的零误匹配校验（真实代码）：

```python
def verify(state):
    d = query.query_indicator(code, year, "NP_DEDUCT")
    p = query.query_indicator(code, year, "NP_PARENT")
    dv, pv = to_yi(d), to_yi(p)
    ok = dv is not None and pv is not None and abs(dv - pv) > 0.01
    return {"verification": [{"company": ..., "deduct": dv, "parent": pv,
                               "zero_mismatch": ok}]}
```

`abs(dv - pv) > 0.01` 的含义：扣非和归母**有差异**（且差 > 0.01 亿），说明两个字段都被正确识别、没有混在一起 → 零误匹配=True。如果误匹配（把扣非当成归母），两者会相等 → 差 < 0.01 → `zero_mismatch=False`。

### 2.4 FastAPI 暴露为 SSE

每个 LangGraph 节点跑完就 yield 一帧，这就是"流式中间过程"的真相（Laravel 只是转发）：

```python
@app.get("/agent/query")
def agent_query(company_code, year, report_type="annual"):
    def stream():
        for chunk in graph.app.stream(inp, cfg, stream_mode="updates"):
            if "__interrupt__" in chunk:
                yield _sse({"step": "need_approval", "thread_id": tid})
                return
            for node, vals in chunk.items():
                yield _sse({"step": node, "data": vals})
        yield _sse({"step": "done"})
    return StreamingResponse(stream(), media_type="text/event-stream")
```

### 2.5 Laravel SSE 转发

浏览器 `EventSource` → Laravel `/fin-agent/query` → Guzzle 消费 Python `/agent/query` → 逐帧 echo 回浏览器。控制器 `forwardStream()` 的**正确**写法（踩过三坑后的最终版）：

```php
private function forwardStream($guzzleResponse): void {
    while (ob_get_level() > 0) { ob_end_flush(); }   // 清缓冲，防 SSE 攒批
    $body = $guzzleResponse->getBody();
    $fp = $body->detach();                            // detach 出底层流资源
    if (is_resource($fp)) {
        while (($line = fgets($fp, 8192)) !== false) { // 按行读，SSE 帧以 \n 分隔
            echo $line;
            if (ob_get_level() > 0) { ob_flush(); }   // 按需 flush，防 "No buffer" 警告
            flush();
        }
        fclose($fp);
        return;
    }
    // 兜底：detach 拿不到资源时走 PSR-7 read 循环
    while (! $body->eof()) { /* ... */ }
}
```

## 三、踩坑记录

这一节是本周最值钱的部分——SSE 在 Laravel 端连踩三个坑，每个都有真实终端输出作证。

### 坑 1：返回类型协变 → 500

- **现象**：点查询报 500，Laravel 日志 `Return value must be of type Illuminate\Http\StreamedResponse, Symfony\Component\HttpFoundation\StreamedResponse returned`。
- **原因**：`response()->stream()` 实际返回 Symfony 基类，而控制器方法声明了 `Illuminate\Http\StreamedResponse` 返回类型，违反协变 → TypeError。
- **解法**：删掉 `use Illuminate\Http\StreamedResponse` + 两处 `: StreamedResponse` 返回类型声明。
- **推论**：这个错发生在 Guzzle 打 Python 之后，证明 Python 8000 + Guzzle 通信已通，只卡在签名。

### 坑 2：PSR-7 Stream 不可遍历 → 没 500 也没响应

- **现象**：重启后不再 500，但浏览器 0 响应（200 + `text/event-stream` 头，body 0 字节）。
- **原因**：旧代码 `foreach ($response->getBody() as $chunk)` —— Guzzle 的 `Stream` 只实现 `StreamInterface`，**不是可遍历对象**。`foreach` 遍历它的"公有属性"，循环体一次都不执行 → 啥都没 echo。
- **解法**：改成 `detach()` 出底层资源，按行 `fgets` 逐行 echo + flush（见 2.5 最终版）。

### 坑 3：清缓冲后无脑 `ob_flush()` → 只出第一帧

- **现象**：只收到第一帧 `classify` 就断。日志 `ob_flush(): Failed to flush buffer. No buffer to flush`。
- **原因**：`forwardStream()` 开头 `while(ob_get_level()>0) ob_end_flush()` 把缓冲全清了，`ob_get_level()` 变 0，循环里无脑 `ob_flush()` 抛警告 → Laravel 转异常 → 想发 500 头但首帧已 echo（headers 已发）→ 致命错误，流中断。
- **解法**：`ob_flush()` 改"按需调用" `if (ob_get_level() > 0) { ob_flush(); }`，`flush()` 无缓冲不警告直出。

### 坑 4（Python 侧）：`auto_approve` 未落盘 → 500

- **现象**：`build_input() got unexpected keyword 'auto_approve'`。
- **原因**：早期 Edit 给 `graph.build_input` 加参数没落盘，FastAPI 调用时报错。
- **解法**：补 State 字段 + `human_review` 短路 + `build_input` 参数，grep 核验落盘。

## 四、验收清单

对照 CURRICULUM 的 W09 验收标准：

- [x] 3 家真实公司跑通「取数 → 抽取 → 归一化 → 入库 → 问一个值」（茅台 / 宁德 / 比亚迪 demo 样本）
- [x] 科目抽取准确（MVP 规则版 100%，6 科目全 L1 命中；含"稀释每股收益"经守卫正确归 DILUTED_EPS）
- [x] **扣非 / 归母零误匹配**（verify 帧 `zero_mismatch: true`）
- [x] Laravel 页面能看到流式返回的中间过程（6 帧逐帧渲染，verify 帧绿色高亮）
- [x] NL2SQL 安全边界设计（只读账号 + 表列白名单 + 参数化；本期未接问数端点，W13 展开）

## 五、数据 / 实测结果

茅台 2025 年报样本，归一化 + 验证的真实输出（amber 本机浏览器收到）：

```
[classify]        {"report_type":"annual"}
[extract_node]    6 行原始科目（营业总收入 / 归母 / 扣非 / 稀释每股收益 / 总资产 / 经营现金流）
[human_review]    {"confirmed":true}
[normalize_persist] 6 科目全 L1 matched，无 unknown 兜底
[verify]          {"company":"贵州茅台","year":2025,"deduct":861.95,"parent":862.28,"zero_mismatch":true}
[done]
```

| 科目（原始名） | 归一化字段 | 匹配级别 | 值（亿） |
|---|---|---|---|
| 营业总收入 | OPER_REV | L1 | 1741.02 |
| 归属于上市公司股东的净利润 | NP_PARENT | L1 | 862.28 |
| 归属于上市公司股东的扣除非经常性损益的净利润 | NP_DEDUCT | L1 | 861.95 |
| 稀释每股收益 | DILUTED_EPS | L1 | 69.00（元） |
| 总资产 | TOTAL_ASSETS | L1 | 2989.45 |
| 经营活动产生的现金流量净额 | OP_CASHFLOW | L1 | 924.56 |

**零误匹配验证**：扣非 861.95 ≠ 归母 862.28（差 0.33 亿 > 0.01），两者都被正确识别、未混淆 → `zero_mismatch: true`。这正是 W06 预言"三道防线救不了语义相似块，字段级归一化唯一解"的实锤。

## 六、这周的取舍

**做了什么**
- 双运行时边界钉死：Python 唯一智能源，Laravel 纯转发。
- 指标语义层 L1–L4 + 三道保护（否定词 / 易混淆组 / 近似指标守卫），硬指标零误匹配落地。
- LangGraph 复用 W08 的 `interrupt` + `MemorySaver`，`auto_approve` 区分流式问值（自动批准）与批量导入（挂起）。
- SSE 全链路（Python `app.stream` → FastAPI → Guzzle → Laravel `Response::stream` → 浏览器 `EventSource`）跑通。

**放弃了什么 / 为什么**
- **unknown 不是兜底**：amber 纠正——"净利润"是独立可区分字段，不该为演示强行划 unknown。unknown 只收容 legit 无法归类的字段，字典补全优先。
- **MVP 用规则版 extract**：不调 LLM（真实年报抽取留 W09 之后接 docling）。规则版足以验证编排 + 归一化 + 流式。
- **可转债未做**：W09 只做财报数据地基，可转债分析在 W11（多 Agent 拆解）/ W15（毕业完整版）展开。
- **Laravel 队列未接**：`/agent/import` 长任务 MVP 同步 SSE 转发，Queue/Horizon 留 W15 生产化。

## 下一篇

W10 · **MCP：让 Agent 连上你的系统**。把本周的 `query_indicator` 包成 FastMCP Server（只读查 MySQL），用自然语言查自己后台数据；并实现一次 Tasks 长任务模式。W09 的 Python 服务会成为 MCP 的"后端"，Laravel 接入层也会从 SSE 转发升级为 MCP 客户端。

## 附录：学习对话实录

本周完整对话（含两次关键纠偏：① 净利润不该强行划 unknown ② 稀释每股收益被 L3 误配）见：

- [`DIALOGUE.md`](./DIALOGUE.md) —— 提炼版：对话实录 + 给 AI 的复现指令 + 方法论总结
- [`DIALOGUE-QA.md`](./DIALOGUE-QA.md) —— 逐轮一问一答底稿（命令原文 + 终端输出）

代码见 [`code/`](./code/)：`python/`（Agent 核心）+ `laravel/`（接入层）。

## 附录：延伸阅读

- LangGraph 官方文档（`interrupt` / `MemorySaver` / `Command(resume)`）
- Guzzle PSR-7 `Stream` 实现（为何不可 `foreach` 遍历）
- PHP `ob_flush()` / `flush()` 输出控制语义

---

## 发布检查

- [x] 代码实际跑过，输出贴进正文（6 帧 SSE + 零误匹配验证）
- [x] 至少 2 条真实踩坑（Laravel 三坑 + Python auto_approve 落盘，共 4 条）
- [x] 有数字/表格（6 科目 L1 命中表 + 扣非/归母对比）
- [x] 有 PHP/SQL 类比（双运行时类比 HTTP 层/Service 层；语义层类比 SQL 等值/正则/模糊）
- [x] 标题不标题党，有信息量
- [x] 结尾有引导（下一篇 MCP / 仓库链接）
- [x] 本周写了 `DIALOGUE.md`
- [x] 本周写了 `DIALOGUE-QA.md`

### 提交前必做：红线扫描

```bash
# 只扫 *.md / *.py 会漏！必须覆盖所有文本类型。
# 注：本模板文件自身会命中（关键词写在下面这行里），属正常，忽略即可。
grep -rlE "dd-admin|dd-api|ddLife|hope-garden|病历|CatchAdmin|dd_permissions" . \
  --include="*.md" --include="*.py" --include="*.json" --include="*.bat" --include="*.sh"

# 顺带查有没有把 Key 写进任何文件
grep -rn "sk-" . --include="*.json" --include="*.py" --include="*.md"
```

- [x] 红线扫描覆盖 `.md` `.py` `.json`（本周无 `.bat`/`.sh` 进仓）
- [x] 无 `sk-` 开头的真实 Key（`.env.example` 仅占位 `FIN_DB_PASS=` 为空，无 Key）
- [x] `.py` / `.md` / `.json` 全 LF（`.bat` 本周未产生）
