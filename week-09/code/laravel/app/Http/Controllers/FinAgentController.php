<?php

namespace App\Http\Controllers;

use App\Services\FinAgentClient;
use Illuminate\Http\Request;

/**
 * 财报 Agent 的 SSE 转发控制器（Laravel 接入层核心）。
 *
 * 职责只有一件：把浏览器的 EventSource 请求，原样透传给 Python FastAPI，
 * 再把 Python 吐出的 SSE 帧逐块 echo 回浏览器。不解析、不改写语义，纯管道。
 *
 * 这对应 W09 验收「Laravel 页面能看到流式返回的中间过程」——中间过程是 Python
 * 逐节点产出的，Laravel 只是个转发代理（W09 阶段1 铁律：Laravel 不写 Agent 逻辑）。
 */
class FinAgentController extends Controller
{
    public function __construct(protected FinAgentClient $agent) {}

    /**
     * 把 Guzzle 流式响应（Python 吐的 SSE）原样逐帧转给浏览器。
     *
     * 关键坑（W09 实测 500 之后的第二个工程坑）：
     *   Guzzle 的 PSR-7 Body 是 `GuzzleHttp\Psr7\Stream`，它只实现 StreamInterface，
     *   **不是可遍历对象**。之前写 `foreach ($response->getBody() as $chunk)` 等于遍历
     *   一个没有可遍历公有属性的对象 —— 循环体一次都不执行，浏览器收到 200 但 body 是
     *   0 字节（表现就是"没 500、也没响应"）。
     *
     *   正确做法：detach() 出底层资源，按行 fgets（SSE 帧以 \n 分隔），逐行 echo+flush，
     *   这样中间过程才能实时逐帧出现在前端；detach 拿不到资源时用 PSR-7 read 循环兜底。
     */
    private function forwardStream($guzzleResponse): void
    {
        // 清空所有可能存在的输出缓冲，让 echo 直接进入 SAPI 缓冲，flush() 即可推到客户端。
        // 注意：清完之后 ob_get_level() 通常为 0 —— 此时再调 ob_flush() 会抛
        // "No buffer to flush" 警告（Laravel 把警告转异常 -> 流中断，表现就是只出第一帧）。
        // 所以 ob_flush() 必须「按需调用」（有缓冲层才调）；flush() 本身无缓冲也不警告，可直出。
        while (ob_get_level() > 0) {
            ob_end_flush();
        }

        $body = $guzzleResponse->getBody();

        // 主路径：detach 出底层流资源，按行读（SSE 帧以 \n 结尾，逐行 flush 才实时）
        $fp = $body->detach();
        if (is_resource($fp)) {
            while (($line = fgets($fp, 8192)) !== false) {
                echo $line;
                if (ob_get_level() > 0) {
                    ob_flush();
                }
                flush();
            }
            fclose($fp);
            return;
        }

        // 兜底：detach 拿不到资源时，用 PSR-7 的 read 循环（注意会攒到 buffer 满或 EOF 才吐）
        while (! $body->eof()) {
            $chunk = $body->read(8192);
            if ($chunk === '') {
                break;
            }
            echo $chunk;
            if (ob_get_level() > 0) {
                ob_flush();
            }
            flush();
        }
    }

    /**
     * SSE 转发：问一个值。
     * 浏览器 EventSource -> Laravel(/fin-agent/query) -> Python(/agent/query)，逐帧透传。
     */
    public function query(Request $request)
    {
        $companyCode = (string) $request->query('company_code', '600519');
        $year        = (int) $request->query('year', 2025);
        $reportType  = (string) $request->query('report_type', 'annual');

        $response = $this->agent->streamQuery($companyCode, $year, $reportType);

        return response()->stream(
            function () use ($response) {
                $this->forwardStream($response);
            },
            200,
            [
                'Content-Type'      => 'text/event-stream',
                'Cache-Control'     => 'no-cache',
                'X-Accel-Buffering' => 'no',   // 关 nginx 缓冲（若前面有反向代理）
            ]
        );
    }

    /**
     * SSE 转发：批量导入长任务（对应 Python /agent/import 的 interrupt 挂起/续跑）。
     */
    public function import(Request $request)
    {
        $companyCode = (string) $request->query('company_code', '600519');
        $year        = (int) $request->query('year', 2025);
        $threadId    = $request->query('thread_id');
        $confirm     = $request->query('confirm') === 'true';

        $response = $this->agent->streamImport($companyCode, $year, $threadId, $confirm);

        return response()->stream(
            function () use ($response) {
                $this->forwardStream($response);
            },
            200,
            [
                'Content-Type'      => 'text/event-stream',
                'Cache-Control'     => 'no-cache',
                'X-Accel-Buffering' => 'no',
            ]
        );
    }
}
