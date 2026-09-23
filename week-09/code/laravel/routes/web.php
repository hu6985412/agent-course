<?php

use Illuminate\Support\Facades\Route;

Route::get('/', function () {
    return view('welcome');
});

// 财报 Agent 接入层（Laravel 只做转发，大脑在 Python FastAPI）。
// 均为 GET 端点：EventSource 只支持 GET，且 GET 不受 CSRF 中间件拦截。
Route::get('/fin-agent', fn () => view('fin-agent'));
Route::get('/fin-agent/query', [App\Http\Controllers\FinAgentController::class, 'query']);
Route::get('/fin-agent/import', [App\Http\Controllers\FinAgentController::class, 'import']);
