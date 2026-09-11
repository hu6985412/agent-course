# -*- coding: utf-8 -*-
"""
W02 · 结构化抽取批跑脚本（requests + Pydantic）

做什么：
  读 cases.json 的 20 条样本 → 调真实 API → json.loads → Pydantic 校验
  → 与期望值逐字段比对 → 输出成功率表 + 失败明细

为什么不用 openai SDK：本周重点是「结构化输出」，不是 HTTP 层（W01 已经把手写
请求拆开看过一遍）。requests 是官方推荐库，协议与 SDK 完全一致。等价 SDK 写法：
    from openai import OpenAI
    OpenAI(api_key=..., base_url=...).chat.completions.create(
        model=..., messages=..., response_format={"type": "json_object"})

配置只从环境变量读（不提供命令行传参，避免进 history 与进程列表）：
    API_KEY / BASE_URL / MODEL

用法：
    python extract.py
    python extract.py --limit 5        只跑前 5 条
    python extract.py --prompt v2      用另一个 prompt 版本（A/B 用）

依赖：pip install requests pydantic
"""

import json
import os
import sys
import time
import argparse
from typing import Optional, List, Literal

try:
    import requests
except ImportError:
    sys.exit("缺少 requests，请先执行：pip install requests")

try:
    from pydantic import BaseModel, ValidationError
except ImportError:
    sys.exit("缺少 pydantic，请先执行：pip install pydantic")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

CASES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cases.json")

# ---------------------------------------------------------------- Pydantic 模型
# 这一层就是「本地校验」：服务端 json_object 只保证能 parse，类型/枚举/range 全靠这里兜住

class Ticket(BaseModel):
    issue_type: Literal["质量问题", "物流问题", "尺码问题", "发票问题", "其他"]
    order_id: Optional[str]
    amount: Optional[float]
    intent: Literal["退货", "换货", "仅退款", "部分退款", "未识别"]
    summary: str

class Extraction(BaseModel):
    tickets: List[Ticket] = []

# ---------------------------------------------------------------- Prompt 版本

OUTPUT_SHAPE = """
{
  "tickets": [
    {
      "issue_type": "质量问题",
      "order_id": "20260812B03",
      "amount": 129,
      "intent": "退货",
      "summary": "一句话概括该订单的客户诉求"
    }
  ]
}
"""

# v1 / v2 共用这一段，只有 V2_EXTRA 是新增的 —— 保证 A/B 只差这一个变量
COMMON_RULES = """- 只输出 JSON 对象本身，不要任何解释文字，不要 markdown 代码围栏
- 一个订单对应 tickets 数组里的一个对象；对话涉及多个订单就输出多个对象
- 完全不涉及售后诉求的对话（如仅有咨询）输出空数组：{"tickets": []}
- 字段未在对话中明确出现时填 null，禁止猜测或推断
- issue_type 只能是：质量问题 / 物流问题 / 尺码问题 / 发票问题 / 其他
- intent 只能是：退货 / 换货 / 仅退款 / 部分退款 / 未识别
- amount 是「客户本次诉求涉及的金额」（元），不是订单原价；原文为「两百多」这类模糊表述时填 null
- 客户中途改变主意时，取最终诉求"""

# v1 缺、v2 补的两条业务规则（v2 与 v3 共用，字符级相同 → 保证两版只差 intent 写法）
#   ① amount 只在有处理诉求时才填（修 #14）
#   ② 纯情绪投诉仍算一个工单（修 #13）
SHARED_EXTRA = """- amount 只在客户明确提出处理诉求时才填；只描述问题、没提要怎么办 → null
- 客户表达不满但无订单号 / 金额 / 具体诉求时，仍输出 1 个 ticket：
  issue_type=其他, intent=未识别, amount=null, order_id=null"""

# v2 的 intent 段：关键词 → 类别的映射表。本质是「用自然语言写的 if-else」。
# 问题：真实用户不会按关键字说话，命中不了就退化成乱猜。
V2_INTENT = """- intent 判别规则（按顺序判断）：
  * 明确说「退货 / 寄回 / 退回去」→ 退货
  * 只说「退款 / 退钱 / 退吧 / 我要退」且未提寄回 → 仅退款
  * 明确说「换一个 / 换货」→ 换货
  * 明确要求只退一部分金额 → 部分退款
  * 判断不了 → 未识别"""

# v3 的 intent 段：判据（rubric）+ few-shot。
# 区别不在「写了什么关键词」，而在「教它怎么权衡」：
#   - 关键词版：命中词 → 类别（机械映射，命中不了就瞎猜）
#   - 判据版  ：列出可观察信号 + 冲突时的取舍原则，让模型自己综合上下文
#   - 示例版  ：用 3 个不在测试集里的真实例子传递「权衡的过程」和「为什么」
V3_INTENT = """- intent 不要靠关键词匹配，要综合整段对话推断「客户希望这件东西最后怎么处理」。

<intent_guide>
以下信号供参考，可能同时出现、也可能全部缺失——出现即加分，不出现不扣分：

  退货的信号：提到寄回 / 寄回去 / 上门取件 / 强调「这东西我不要了」
  换货的信号：想要一个替代品 / 换同款不同规格（尺码、颜色、型号）/ 东西没坏只是不合适
  仅退款的信号：只谈钱怎么退 / 强调麻烦、不想寄、懒得折腾 / 东西已使用、已洗涤、已拆封
  部分退款的信号：明确只要回其中一部分金额，东西自己留着

信号冲突时按这个顺序取舍：
  1. 以对话最后一轮的诉求为准（客户会改主意）
  2. 商品已使用 / 已洗涤 / 已拆封 → 优先仅退款（退回也无法二次销售）
  3. 客户强调流程麻烦 → 优先仅退款（他要的是快点结束，不是把东西送回去）
  4. 客户强调东西有问题、要退回去 → 退货

只有当完全没有任何处理诉求（比如只是查询、只是抱怨、或把决定权推给客服）时才填「未识别」。
「退货」和「仅退款」之间拿不准时，选更符合客户实际处境的那个，不要填未识别。
</intent_guide>

<examples>
例 1（信号不足，按处境推断）
<example_dialogue>
[客户] 买的 T 恤洗了一次领口就变形了，89 块钱，我要退。订单 20260501Z01。
[客服] 好的。
</example_dialogue>
输出：{"tickets":[{"issue_type":"质量问题","order_id":"20260501Z01","amount":89,"intent":"仅退款","summary":"T 恤洗一次后领口变形，89 元，客户要求退款"}]}
为什么：只说「退」，没提寄回也没提只退钱。但已洗涤穿着 → 退回也无法二次销售，商家通常直接退款，且客户没表达寄回意愿 → 仅退款。

例 2（信号冲突，取最后一轮）
<example_dialogue>
[客户] 这个充电宝充不进电，我要退货！
[客服] 好的，请寄回。
[客户] 等等，我这边寄快递不方便，能不能直接退钱？订单 20260502Z02。
</example_dialogue>
输出：{"tickets":[{"issue_type":"质量问题","order_id":"20260502Z02","amount":null,"intent":"仅退款","summary":"充电宝无法充电，客户因寄件不便改为要求直接退款"}]}
为什么：先说「退货」后改口说「寄快递不方便、直接退钱」→ 以最后一轮为准，判仅退款。

例 3（确实没有诉求信号）
<example_dialogue>
[客户] 你们这个东西不行，得给我处理一下。
[客服] 请问您希望怎么处理呢？
[客户] 你看着办吧。
</example_dialogue>
输出：{"tickets":[{"issue_type":"其他","order_id":null,"amount":null,"intent":"未识别","summary":"客户对商品不满但未提出具体处理方式"}]}
为什么：客户把决定权推给客服，全程没有任何方向信号 → 未识别，转人工追问，不要替他猜。
</examples>"""

# v4 = v3 去掉 <examples> 段（用来验证「示例到底有没有用、白花了多少 token」）
# 单变量保证：v3 与 v4 只差这一个 examples 段，其余字符级相同
V4_INTENT = V3_INTENT.split("<examples>")[0].rstrip() + "\n"

PROMPT_TMPL = """你是电商客服工单结构化抽取引擎，输出 JSON。

<constraints>
%s
</constraints>

<output_schema>
%s
</output_schema>"""

PROMPTS = {
    "v1": PROMPT_TMPL % (COMMON_RULES, OUTPUT_SHAPE),
    # 段序：通用规则 → 共有补充规则 → intent 段（含示例，放最后最靠近输入）
    # v2 与 v3 只有 intent 段不同，其余字符级相同
    "v2": PROMPT_TMPL % (COMMON_RULES + "\n" + SHARED_EXTRA + "\n" + V2_INTENT, OUTPUT_SHAPE),
    "v3": PROMPT_TMPL % (COMMON_RULES + "\n" + SHARED_EXTRA + "\n" + V3_INTENT, OUTPUT_SHAPE),
    "v4": PROMPT_TMPL % (COMMON_RULES + "\n" + SHARED_EXTRA + "\n" + V4_INTENT, OUTPUT_SHAPE),
}

# ---------------------------------------------------------------- 调用

def call_llm(system_prompt: str, dialogue: str, model: str) -> tuple:
    """返回 (是否成功, 原始内容或错误信息, usage字典)"""
    url = os.environ["BASE_URL"].rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": "Bearer " + os.environ["API_KEY"],
        "Content-Type": "application/json; charset=utf-8",
    }
    body = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "<dialogue>\n%s\n</dialogue>" % dialogue},
        ],
        # L1：只保证能 parse，不保证业务 schema —— 所以下面必须本地校验
        "response_format": {"type": "json_object"},
    }
    try:
        r = requests.post(url, headers=headers, json=body, timeout=60)
    except Exception as e:
        return False, "HTTP 异常: %s" % e, {}
    if r.status_code != 200:
        return False, "HTTP %s: %s" % (r.status_code, r.text[:300]), {}
    data = r.json()
    content = data["choices"][0]["message"]["content"]
    return True, content, data.get("usage", {})

# ---------------------------------------------------------------- 比对

FIELDS = ["issue_type", "order_id", "amount", "intent"]


def field_eq(ev, av, field) -> bool:
    """单值比对。amount 用容差比较，其余用相等。"""
    if field == "amount":
        return (ev is None and av is None) or (
            ev is not None and av is not None and abs(float(ev) - float(av)) < 0.01)
    return ev == av


def fmt(v) -> str:
    """期望值是 list 时表示「接受集合」，打印成 退货|仅退款 更易读。"""
    return "|".join(v) if isinstance(v, list) else repr(v)


def compare(expect: dict, actual: dict) -> tuple:
    """返回 (字段错误列表, total, ok)。

    期望值写成数组时表示「接受集合」：例如 intent 写 ["退货","仅退款"]，
    表示这个 case 人类自己也判不死，模型给出其中任意一个都算对。
    这不是放水，是把「标注歧义」显式写进测试集，避免用假精确的答案惩罚模型。
    """
    errors = []
    exp_list = expect.get("tickets", [])
    act_list = actual.get("tickets", [])

    if len(exp_list) != len(act_list):
        errors.append("tickets 数量 期望 %d / 实际 %d" % (len(exp_list), len(act_list)))

    total = ok = 0
    for i in range(max(len(exp_list), len(act_list))):
        e = exp_list[i] if i < len(exp_list) else None
        a = act_list[i] if i < len(act_list) else None
        if e is None or a is None:
            continue
        for f in FIELDS:
            total += 1
            ev, av = e.get(f), a.get(f)
            if isinstance(ev, list):
                same = any(field_eq(v, av, f) for v in ev)
            else:
                same = field_eq(ev, av, f)
            if same:
                ok += 1
            else:
                errors.append("ticket%d.%s 期望 %s / 实际 %r" % (i, f, fmt(ev), av))
        # summary 只查非空
        if not (a.get("summary") or "").strip():
            errors.append("ticket%d.summary 为空" % i)
    return errors, total, ok


def count_accept_sets(cases) -> int:
    """统计有多少条样本用了接受集合 —— 汇报指标时必须披露，否则数字是虚的。"""
    n = 0
    for c in cases:
        for t in c.get("expect", {}).get("tickets", []):
            if any(isinstance(t.get(f), list) for f in FIELDS):
                n += 1
                break
    return n

# ---------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--prompt", default="v1", choices=sorted(PROMPTS))
    ap.add_argument("--sleep", type=float, default=1.0, help="请求间隔秒，防限流")
    ap.add_argument("--repeat", type=int, default=1, help="每条样本重复跑几次，用于压随机噪声")
    ap.add_argument("--show", action="store_true", help="只打印 prompt 全文后退出")
    args = ap.parse_args()

    if args.show:
        print(PROMPTS[args.prompt])
        return

    for k in ("API_KEY", "BASE_URL"):
        if not os.environ.get(k):
            sys.exit("环境变量 %s 未设置（先双击 start-env-windows.bat）" % k)
    model = os.environ.get("MODEL", "deepseek-v4-flash")
    print("配置来源：环境变量 | BASE_URL=%s | MODEL=%s | KEY=%s***"
          % (os.environ["BASE_URL"], model, os.environ["API_KEY"][:4]))

    cases = json.load(open(CASES_FILE, encoding="utf-8"))
    if args.limit:
        cases = cases[:args.limit]
    prompt = PROMPTS[args.prompt]

    print("\nprompt 版本：%s | 样本数：%d | 其中 %d 条使用了「接受集合」期望值\n"
          % (args.prompt, len(cases), count_accept_sets(cases)))
    print("%-4s %-6s %-6s %s" % ("id", "结果", "通过", "明细"))
    print("-" * 88)

    total_f = ok_f = 0
    passed_cases = 0
    total_runs = 0
    stable_cases = 0
    usage_sum = {"prompt_tokens": 0, "completion_tokens": 0}
    failures = []

    for c in cases:
        reps_pass = 0
        rep_errors = []
        for rep in range(args.repeat):
            ok, content, usage = call_llm(prompt, c["dialogue"], model)
            if not ok:
                rep_errors.append("[%d] %s" % (rep, content))
            else:
                usage_sum["prompt_tokens"] += usage.get("prompt_tokens", 0)
                usage_sum["completion_tokens"] += usage.get("completion_tokens", 0)
                parsed = None
                try:
                    parsed = Extraction(**json.loads(content)).model_dump()
                except Exception as e:
                    rep_errors.append("[%d] %s" % (rep, str(e).replace("\n", " ")[:160]))
                if parsed is not None:
                    errors, t, o = compare(c["expect"], parsed)
                    total_f += t
                    ok_f += o
                    if errors:
                        rep_errors.append("[%d] %s" % (rep, "; ".join(errors)))
                    else:
                        reps_pass += 1
            if rep < args.repeat - 1:
                time.sleep(args.sleep)

        total_runs += args.repeat
        passed_cases += reps_pass
        if reps_pass == args.repeat:
            stable_cases += 1
        status = "PASS" if reps_pass == args.repeat else ("FLAKY" if reps_pass else "FAIL")
        print("%-4d %-6s %-6s %s" % (c["id"], status, "%d/%d" % (reps_pass, args.repeat),
                                     " | ".join(rep_errors[:2])))
        if rep_errors:
            failures.append((c["id"], rep_errors))

    print("-" * 88)
    ran = len(cases)
    print("\n===== 结果（prompt %s, repeat=%d）=====" % (args.prompt, args.repeat))
    print("完全稳定率 : %d/%d = %.1f%%   (同一条 %d 次全部通过才算数，最能反映上线风险)"
          % (stable_cases, ran, 100.0 * stable_cases / ran, args.repeat))
    print("平均通过率 : %d/%d = %.1f%%   (单次调用的期望成功率)"
          % (passed_cases, total_runs, 100.0 * passed_cases / total_runs))
    if total_f:
        print("字段成功率 : %d/%d = %.1f%%" % (ok_f, total_f, 100.0 * ok_f / total_f))
    print("token 合计 : prompt %d + completion %d"
          % (usage_sum["prompt_tokens"], usage_sum["completion_tokens"]))

    if failures:
        print("\n===== 失败明细 =====")
        for cid, errs in failures:
            print("#%d" % cid)
            for e in errs:
                print("   - %s" % e)

    out = "results_%s_r%d.json" % (args.prompt, args.repeat)
    json.dump({"prompt": args.prompt, "repeat": args.repeat,
               "accept_set_cases": count_accept_sets(cases),
               "stable": stable_cases, "passed_runs": passed_cases,
               "total_runs": total_runs, "total_cases": ran,
               "field_ok": ok_f, "field_total": total_f,
               "usage": usage_sum,
               "failures": [{"id": i, "errors": e} for i, e in failures]},
              open(out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("\n明细已写入 %s" % out)

if __name__ == "__main__":
    main()
