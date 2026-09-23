# W09 代码运行说明

毕业项目 MVP：**财报与可转债分析 Agent 的数据地基**。代码分两部分，对应「双运行时」边界：

- `python/` —— Agent 编排核心（Python + LangGraph）。建库、字段字典、抽取、归一化、LangGraph 图、FastAPI SSE。
- `laravel/` —— 业务接入层（Laravel 12）。只做 HTTP/SSE 转发 + 最简查询页，**不写任何 Agent 逻辑**（W09 铁律）。

---

## 1. Python 侧（Agent 核心）

### 依赖
```bash
pip install fastapi uvicorn langgraph pymysql pydantic
```

### 数据库
本地 MySQL 8.0，默认 `127.0.0.1:3306`，库名 `fin_agent`（root 空密码，仅本地 MVP 用）。
配置从 `python/.env.example` 读取，复制为 `python/.env` 后按需修改：

```
FIN_DB_HOST=127.0.0.1
FIN_DB_PORT=3306
FIN_DB_USER=root
FIN_DB_PASS=
FIN_DB_NAME=fin_agent
```

### 跑通步骤
```bash
cd python
cp .env.example .env
python init_db.py          # 建 5 张表（fin_companies / fin_reports / fin_indicators / fin_report_items / fin_indicator_unknown）
python seed_indicators.py  # 冷启动字段字典（11 个科目，含「扣非 / 归母」易混淆组）
python normalize.py        # 验证四级匹配 + 零误匹配（拿茅台样本跑）
python graph.py            # 验证 LangGraph DAG + interrupt 挂起 / 续跑
uvicorn api:app --port 8000   # 起 FastAPI SSE 服务
```

### 验证 SSE（另开终端）
```bash
curl -N "http://127.0.0.1:8000/agent/query?company_code=600519&year=2025"
```
应逐帧收到 `classify → extract_node → human_review → normalize_persist → verify → done`，
`verify` 帧 `zero_mismatch: true`（扣非 861.95 亿 / 归母 862.28 亿，两者都被正确识别、没有混在一起）。

---

## 2. Laravel 侧（接入层）

### 依赖与配置
```bash
cd laravel
composer install
cp .env.example .env
php artisan key:generate   # 生成 APP_KEY（Laravel 必需，与 Agent 无关）
```
`.env.example` 仅一个占位变量（**无 Key**）：
```
FIN_AGENT_BASE_URL=http://127.0.0.1:8000
```

### 起服务
```bash
php artisan serve --port 8001
```
浏览器打开 `http://127.0.0.1:8001/fin-agent` —— 点「查询」应看到与 Python 端一致的逐帧流式中间过程
（`verify` 帧 `zero_mismatch: true` 会绿色高亮）。

> 注意：`php artisan serve` **不热加载**。改了控制器必须重启才能生效（W09 踩过三次 SSE 坑，全在 `app/Http/Controllers/FinAgentController.php`）。

---

## 3. MVP 已知限制（如实标注，非 bug）

- **样本硬编码**：`api.py` 的 `SAMPLES` 是茅台 / 宁德 / 比亚迪 的 demo 科目，`year` / `company_code` 参数暂未真实筛选数据源。接 docling 解析真实 PDF 后替换 `SAMPLES` 即可生效。
- **persist 未幂等**：`normalize.persist` 直插，重复跑同一年会插入重复行。生产需 `ON DUPLICATE KEY`。
- **可转债未做**：W09 只做财报数据地基，可转债分析在 W11（多 Agent）/ W15（毕业完整版）展开。
- **队列未接**：`/agent/import` 长任务 MVP 为同步 SSE 转发，未接 Laravel Queue / Horizon（W15 生产化时补）。
