<?php

namespace App\Services;

use GuzzleHttp\Client;

/**
 * Python 财报 Agent 服务的 HTTP 客户端（Laravel 调用端唯一对外出口）。
 *
 * 这是「服务化边界」里 Laravel 侧的核心：只负责把请求打到 Python FastAPI，
 * 并把 SSE 流交出去。这里不写任何 Agent 逻辑（不调 LLM、不做归一化、不碰财务库）。
 *
 * Python 服务地址从 config('services.fin_agent.base_url') 读，回退到 .env 的
 * FIN_AGENT_BASE_URL（默认 http://127.0.0.1:8000）。
 */
class FinAgentClient
{
    protected Client $client;

    public function __construct()
    {
        $base = config('services.fin_agent.base_url', env('FIN_AGENT_BASE_URL', 'http://127.0.0.1:8000'));
        $this->client = new Client([
            'base_uri' => rtrim($base, '/'),
            'timeout' => 120,      // 批量导入 300 家远超默认 60s，worker 也需 --timeout=120
            'stream'  => true,     // 关键：Guzzle 流式消费 Python SSE，逐块转发
        ]);
    }

    /**
     * 流式问值：返回 Guzzle 流式响应，由控制器逐块 echo 给浏览器。
     * 对应 Python /agent/query（auto_approve=True，逐节点吐帧）。
     * EventSource 只支持 GET，所以走 query 参数。
     */
    public function streamQuery(string $companyCode, int $year, string $reportType = 'annual')
    {
        return $this->client->get('/agent/query', [
            'query'  => [
                'company_code' => $companyCode,
                'year'         => $year,
                'report_type'  => $reportType,
            ],
            'stream' => true,
        ]);
    }

    /**
     * 批量导入长任务：对应 Python /agent/import。
     * 首次（无 threadId）：auto_approve=False -> 跑到 human_review 挂起 -> 返回 thread_id。
     * 续跑（带 threadId + confirm）：Command(resume) 从挂起点继续 -> 落库 -> verify。
     */
    public function streamImport(
        string $companyCode,
        int $year,
        ?string $threadId = null,
        bool $confirm = false,
        string $reportType = 'annual'
    ) {
        if ($threadId) {
            $query = [
                'thread_id' => $threadId,
                'confirm'   => $confirm ? 'true' : 'false',
            ];
        } else {
            $query = [
                'company_code' => $companyCode,
                'year'         => $year,
                'report_type'  => $reportType,
            ];
        }

        return $this->client->get('/agent/import', [
            'query'  => $query,
            'stream' => true,
        ]);
    }
}
