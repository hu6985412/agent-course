# -*- coding: utf-8 -*-
"""W02 实验 1：把 inject_bad / inject_good 两次真实输出直接喂给 json.loads()"""

import json

bad = '{"issue_type":"鞋底开胶","amount":"两百多块钱","want_refund":true,"order_id":"20260903A17"}'

good = '```json\n{\n  "issue_type": "质量问题（鞋底开胶）",\n  "amount": "200多",\n  "want_refund": true,\n  "order_id": "20260903A17"\n}\n```'

for name, raw in (("bad  输出", bad), ("good 输出", good)):
    try:
        print(f"{name} -> OK   ", json.loads(raw))
    except Exception as e:
        print(f"{name} -> FAILED: {type(e).__name__}: {e}")
