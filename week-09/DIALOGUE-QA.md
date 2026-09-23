# W09 · 逐轮问答底稿（DIALOGUE-QA）

> 逐轮一问一答，不做归纳压缩。每轮给过的命令原文、终端输出均保留。
> 范围：W09 实操期（阶段1 引导 → 阶段2 实操 → 阶段3 反馈 → 阶段4 收尾前的 Laravel 三坑）。
> 元话题（课程走向讨论、产出管理）不收，见 [`DIALOGUE.md`](./DIALOGUE.md) 方法论部分。

---

### 轮 1 · 启动

**amber**：开始 W09 课程。

**老师**：进入阶段1 引导学习。先讲架构边界四小节（双运行时 / 指标语义层 / SSE / NL2SQL 安全），每节配理解检查，讲完停下等反馈。

---

### 轮 2 · 全链路形态确认

**amber**：vue 前端请求后端 php API 接口，接口内请求 python 接口，python 返回结果，php 端 API 接口响应结果，前端拿到结果展示。

**老师**：确认这就是「双运行时」形态——前端(Vue) → Laravel(API) → Python(Agent 核心)。Laravel 只做 HTTP 消费 + SSE 转发 + 页面，Python 做全部智能。铁律：Laravel 不写 Agent 逻辑。

---

### 轮 3 · 指标语义层理解检查

**amber**：
1. raw_name 包含扣非关键字，由 L1 进行精准匹配；
2. 使用否定词保护机制，或者向量结合 BM25 重排。

**老师**：纠正第 2 点——向量 + BM25 + 重排是**检索层**技巧，对「扣非 vs 归母」这种语义相邻块无效（W06 已预言"三道防线救不了语义相似块"）。正确解法是**禁术**：raw_name 含「扣非 / 扣除 / 非经常 / 母公司」修饰词时，强制禁止 L3/L4 模糊匹配，只在精确/规则层匹配。这不是"检索更好"，是"根本不走模糊"。

---

### 轮 4 · 否定词 + 量级校验理解

**amber**：
1. 不触发否定词 guard 时进入 unknown；
2. 应该预警，因为一般情况下扣非应该小于归母净利润。

**老师**：确认量级校验思路（扣非 < 归母是软信号）。但第 1 点要修正——unknown 不是"没触发 guard 就进"，而是"四级匹配全没中"才进。后续你会纠正一个更关键的点：可识别字段不该为演示强行进 unknown。

---

### 轮 5 · unknown 设计哲学纠偏

**amber**：财报是很严谨的东西，数据要求精准，未命中就不混进已经精准识别的数据内，应该单独处理。

**老师**：✅ 采纳。原设计为了演示 L0 机制，把"净利润"强行划 unknown 是错的。改为：unknown 仅收容 legit 无法归类的字段；精准可识别的字段（如净利润）必须进字典，不许混进兜底。这是 W09 设计哲学的关键修正。

---

### 轮 6 · 架构边界确认

**amber**：
1. 架构设计上，agent 这部分功能本来也不应该和 api 项目混合；
2. python 在数据处理和 agent 上开发本身就有生态天然优势。

**老师**：确认双轨决策（不是双轨，是单编排栈）：Python 做编排核心，Laravel 做接入层。你"agent 不与 api 混合"的直觉和"Python 生态优势"的判断都正确，这与 W09 技术路线一致。

---

### 轮 7 · NL2SQL 防线确认

**amber**：第二道防线拦列限定；第三道防线会拦截 `OR 1=1` 这类参数注入，会被转化。

**老师**：确认 NL2SQL 四防线：① 只读账号（fin_ro 角色仅 GRANT SELECT）② 表列白名单 ③ 参数化 + 结构化意图 ④ AST 解析拦截。本期 NL2SQL 问数端点未实装，防线设计保留到 W13 展开。

---

### 轮 8 · 建库命令

**amber**（PowerShell）：
```
PS ...\w09-scratch> python .\init_db.py
```
报错；另问：当前本地数据库没有 fin_agent 库，init_db.py 会自动创建吗？

**老师**：`init_db.py` 用 `CREATE DATABASE IF NOT EXISTS fin_agent` + 建表，会自动建库。报错先贴完整 traceback——多半是 `pymysql` 不支持 `multi` 参数（那是 mysql-connector 的），按分号拆多条语句逐条执行即可。

---

### 轮 9 · 建库成功

**amber**（PowerShell）：
```
PS ...\w09-scratch> python .\init_db.py
```
正常。

**老师**：✅ 库 + 表 + 字典种子（seed_indicators.py）跑通。5 张表就位。

---

### 轮 10 · 归一化零误匹配验证

**amber**（PowerShell）：
```
PS ...\w09-scratch> python .\normalize.py
```
零误匹配验证输出。

**老师**：✅ 四级匹配 + 否定词保护 + 易混淆组验证通过，茅台样本 `zero_mismatch: true`。

---

### 轮 11 · pipeline_demo 崩溃（Decimal/1e8）

**amber**（PowerShell）：
```
PS ...\w09-scratch> python .\pipeline_demo.py
```
崩溃：`TypeError: unsupported operand type(s) for /: 'Decimal' and 'float'`（值 1e8 触发）。

**老师**：pymysql 返回 `Decimal`，不能直接 `/ float`。改 `float(d["value"])`，FastAPI 端用 `json.dumps(default=str)` 处理 Decimal。已修复。

---

### 轮 12 · 净利润纠偏（再次）

**amber**：这里有一个问题，就是财报是比较精准的东西，净利润是一个单独的关键字段……不应该因为用这个举例子，而强行去把他划分到 unknown 里面去。

**老师**：✅ 同轮 5，落实进设计：字典补 `NET_PROFIT` 的 alias（"净利润（扣非前）"），unknown 不收容可识别字段。

---

### 轮 13 · 稀释每股收益误配（真 bug）

**amber**（PowerShell）：
```
PS ...\w09-scratch> python .\pipeline_demo.py
```
输出暴露：「稀释每股收益」被匹配成了 `BASIC_EPS`。

**老师**：这是**真 bug**，不是演示问题。L3 子串包含过宽，把近似指标互相吸收。修复：
1. 新增 `DILUTED_EPS` 字段；
2. 收紧 `BASIC_EPS` 的 alias（删"每股收益"改"每股收益(基本)"）；
3. 加**近似指标守卫**：L3 不能把"稀释每股收益"吸进"基本每股收益"。

这正是指标语义层"护城河"被真实数据验证。

---

### 轮 14 · 全链路成功

**amber**（长文本）：seed + normalize + pipeline_demo 全成功输出。

**老师**：✅ Python 侧三件套闭环（库 → 字典 → normalize → LangGraph → FastAPI SSE）。

---

### 轮 15 · graph.py DAG + interrupt 跑通

**amber**（PowerShell）：
```
PS ...\w09-scratch> python .\graph.py
```
DAG + interrupt 跑通，挂起后续跑。

**老师**：✅ `classify → extract_node → human_review(interrupt) → normalize_persist → verify` + 同 thread_id 续跑验证通过。复用 W08 的 MemorySaver / interrupt / 结构化状态路由。

---

### 轮 16 · curl 测试（PowerShell 别名坑）

**amber**（PowerShell）：
```
PS C:\Users\amber> curl -N "http://127.0.0.1:8000/agent/query?company_code=600519&year=2025"
```
报 500（实际是 PowerShell 的 `curl` 是 `Invoke-WebRequest` 别名，不是真 curl）。

**老师**：PowerShell 里 `curl` 是 `Invoke-WebRequest` 别名，不支持 `-N`。用 `curl.exe`（真 curl）或加 `-UseBasicParsing`。先确认 Python 端是否真 500。

---

### 轮 17 · Python 端 500 traceback

**amber**（长文本）：python 端 500 traceback：
```
build_input() got unexpected keyword 'auto_approve'
```

**老师**：根因——之前给 `graph.build_input` 加 `auto_approve` 参数的 Edit 没落盘。修复：补 State 字段 + `human_review` 短路（auto_approve 直接 confirmed=True）+ `build_input` 参数，grep 核验落盘。重启 uvicorn 后重试。

---

### 轮 18 · 确认修复

**amber**：修复了吗？

**老师**：已补并 grep 核验 `auto_approve` 落盘。请重启 uvicorn 后用 `curl.exe -N` 验证。

---

### 轮 19 · SSE 5 帧成功

**amber**（PowerShell）：
```
PS C:\Users\amber> curl.exe -N "http://127.0.0.1:8000/agent/query?company_code=600519&year=2025"
```
SSE 5 帧成功输出（classify→extract_node→human_review(confirmed)→normalize_persist→verify(zero_mismatch:true)→done）。

**老师**：✅ Python 侧 SSE 验证通过，`auto_approve` 短路生效，零误匹配验证通过，流式中间过程真相成立。

---

### 轮 20 · Laravel 项目就绪

**amber**：已经安装新建好项目 fin-agent 了，你来操作 2、3、4 步骤（复制文件 / 加路由 / 配 .env）。

**老师**：收到。项目地址 `D:\WorkBuddyWorkspace\agent_workspace\fin-agent`（Laravel 12）。我代写 3 文件 + 路由 + .env，你只管起服务验证。

---

### 轮 21 · 项目地址确认

**amber**：`D:\WorkBuddyWorkspace\agent_workspace\fin-agent` 这个是项目地址。

**老师**：确认，Glob 索引延迟但文件真实存在（Controller.php 可 Read 证实）。

---

### 轮 22 · 读取 Controller 确认

**amber**：`@"...\app\Http\Controllers\Controller.php"` 这个文件你能否读取到？

**老师**：能 Read（Controller.php 是 Laravel 基类，FinAgentController 继承它）。确认项目结构正常。

---

### 轮 23 · Laravel 点击查询 500

**amber**：点击查询按钮后 500，8001 有收到请求但前端是 500，如何排查？

**老师**：读 `laravel.log` 定位。日志显示：
```
App\Http\Controllers\FinAgentController::query(): Return value must be of type
Illuminate\Http\StreamedResponse, Symfony\Component\HttpFoundation\StreamedResponse returned
```
根因：`response()->stream()` 返回 Symfony 基类，方法声明 Illuminate 子类返回类型违反协变 → TypeError。修复：删 `use Illuminate\Http\StreamedResponse` + 两处 `: StreamedResponse` 声明。重启 `php artisan serve` 后重试。

---

### 轮 24 · 只出第一帧（ob_flush 警告）

**amber**（贴 laravel.log）：
```
ob_flush(): Failed to flush buffer. No buffer to flush
...
Cannot modify header information - headers already sent
```

**老师**：第二坑。根因：`forwardStream()` 开头 `while(ob_get_level()>0) ob_end_flush()` 清完缓冲后 `ob_get_level()==0`，循环里无脑 `ob_flush()` 抛警告 → Laravel 转异常 → 想发 500 头但首帧已 echo（headers 已发）→ 致命错误，流中断。修复：`ob_flush()` 改"按需调用" `if (ob_get_level() > 0) { ob_flush(); }`，`flush()` 无缓冲直出。CLI 复现验证：清缓冲后 ob_get_level=0，未保护写法触发警告、保护写法零警告。

---

### 轮 25 · 全链路通了（验收达成）

**amber**（浏览器输出）：
```
[classify] {"report_type":"annual"}
[extract_node] {"rows":[["营业总收入",174102000000,"元",12],["归属于上市公司股东的净利润",86228000000,"元",12],["归属于上市公司股东的扣除非经常性损益的净利润",86195000000,"元",12],["稀释每股收益",69,"元",12],["总资产",298945000000,"元",20],["经营活动产生的现金流量净额",92456000000,"元",30]]}
[human_review] {"confirmed":true}
[normalize_persist] {"report_id":7,"decisions":[{"raw_name":"营业总收入","code":"OPER_REV","status":"matched","method":"L1"},{"raw_name":"归属于上市公司股东的净利润","code":"NP_PARENT",...},{"raw_name":"...扣除非经常性损益的净利润","code":"NP_DEDUCT",...},{"raw_name":"稀释每股收益","code":"DILUTED_EPS",...},{"raw_name":"总资产","code":"TOTAL_ASSETS",...},{"raw_name":"经营活动产生的现金流量净额","code":"OP_CASHFLOW",...}]}
[verify] {"verification":[{"company":"贵州茅台","year":2025,"deduct":861.95,"parent":862.28,"zero_mismatch":true}]}
[done]
```

**老师**：✅ 全链路通。6 帧完整，6 科目全 L1 命中（含 DILUTED_EPS 正确归位，无 unknown 兜底），`zero_mismatch: true`。W09 阶段2 实操闭环，硬指标"扣非/归母零误匹配"达成。进入阶段4 汇总产出。

---

> 注：W09 后续「课程走向」讨论（amber 问后续周是否基于本框架完善）属产出管理元话题，按模板不收此处，详见 [`DIALOGUE.md`](./DIALOGUE.md) 方法论与 [`week-09-learning-log.md`](../../week-09-learning-log.md)。
