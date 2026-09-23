# W09 Laravel 13 调用端 —— 部署步骤

独立最小 Laravel 13 项目，只做 Python 财报 Agent 的调用端（SSE 转发 + 最简查询页）。
**Laravel 不写任何 Agent 逻辑**（不调 LLM、不做归一化、不碰财务库），符合 W09 服务化边界铁律。
Laravel 13 的 AI SDK 增强我们**不碰**——Agent 大脑只在 Python。

## 1. 新建项目（amber 本机）
```powershell
cd D:\WorkBuddyWorkspace\agent_workspace
composer create-project laravel/laravel fin-agent "13.*"
cd fin-agent
# Guzzle 是 Laravel 默认依赖，一般已装；确认：
composer show guzzlehttp/guzzle
```

## 2. 把本目录的代码复制进项目
- `app/Services/FinAgentClient.php`                 -> `fin-agent/app/Services/FinAgentClient.php`
- `app/Http/Controllers/FinAgentController.php`      -> `fin-agent/app/Http/Controllers/FinAgentController.php`
- `resources/views/fin-agent.blade.php`             -> `fin-agent/resources/views/fin-agent.blade.php`

## 3. 路由
`routes/api.php`（SSE 转发端点，无 CSRF/session，适合长连接）：
```php
use App\Http\Controllers\FinAgentController;

Route::get('/fin-agent/query',  [FinAgentController::class, 'query']);
Route::get('/fin-agent/import', [FinAgentController::class, 'import']);
```

`routes/web.php`（最简查询页）：
```php
Route::get('/fin-agent', fn () => view('fin-agent'));
```

## 4. .env 配置（指向 Python 服务）
```dotenv
FIN_AGENT_BASE_URL=http://127.0.0.1:8000
```
Python FastAPI 跑在 8000，Laravel 跑在 8001，避免端口冲突。

## 5. 运行（两个终端）
终端 A —— Python 大脑（已在跑的别重复起）：
```powershell
cd D:\WorkBuddyWorkspace\agent_workspace\w09-scratch
python -m uvicorn api:app --port 8000
```
终端 B —— Laravel 调用端：
```powershell
cd D:\WorkBuddyWorkspace\agent_workspace\fin-agent
php artisan serve --port 8001
```

## 6. 验证
浏览器开 `http://127.0.0.1:8001/fin-agent`，输入 600519 / 2025，点「查询」。
应看到逐帧流式渲染：classify → extract_node → human_review(confirmed:true) → normalize_persist → verify(zero_mismatch:true) → done。
这和直接 `curl.exe -N http://127.0.0.1:8000/agent/query?...` 的输出一致，只是多了一层 Laravel 转发。

## 已知后续（MVP 暂未做）
- 队列长任务：`/agent/import` 的批量导入应走 Laravel Queue 异步（前端轮询 thread_id 状态，生产升级 Reverb 推送）。当前 MVP 先走同步 SSE 转发验证链路。
- persist 去重：Python 侧 fin_report_items 直插未去重，重复 year 会插重复行（W09 Python 侧待办）。
