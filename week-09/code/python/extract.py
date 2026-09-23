"""W09 extract 工具（规则版 MVP）。

真实年报 PDF 经 docling/pdfplumber 解析后得到"表格行"，
本模块负责把原始行清洗成标准元组 (raw_name, value_元, unit, page)：
  - raw_name 保留原文（归一化交给 normalize.L2，不在此改，留审计痕迹）
  - value 去掉千分位/空白，按单位换算到"元"
  - 单位统一归一成"元"落库

正统做法（amber 本机）：用 docling 解析 PDF -> 得到 tables -> 每行喂给本模块。
手搓目的：先不依赖 LLM/PDF 库打通"抽->归一->落库"全链路，验证护栏。
"""
import re

_UNIT_MULT = {"元": 1.0, "万元": 1e4, "亿元": 1e8}


def parse_value(text, declared_unit="元"):
    """把带噪声的数值文本解析成以"元"为单位的 float；无法解析返回 None。"""
    s = str(text).replace(",", "").replace(" ", "").replace("\u00a0", "")
    unit = declared_unit
    # 文本自带单位优先于声明单位
    for suffix, mult in (("亿元", 1e8), ("万元", 1e4), ("元", 1)):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            unit = suffix
            break
    s = s.strip()
    if s in ("", "-", "--", "—", "N/A", "不适用", "无"):
        return None
    try:
        num = float(s)
    except ValueError:
        return None
    return num * _UNIT_MULT.get(unit, 1.0)


def extract_rows(raw_rows):
    """raw_rows: list[{raw_name, value_raw, unit, page}]
    返回 list[(raw_name, value_元_or_None, unit, page)]。"""
    out = []
    for r in raw_rows:
        raw_name = (r.get("raw_name") or "").strip()
        if not raw_name:
            continue
        value = parse_value(r.get("value_raw", ""), r.get("unit", "元"))
        out.append((raw_name, value, "元", r.get("page")))
    return out


if __name__ == "__main__":
    sample = [
        {"raw_name": "营业总收入", "value_raw": "1,741.02", "unit": "亿元", "page": 12},
        {"raw_name": "归属于上市公司股东的净利润", "value_raw": "862.28", "unit": "亿元", "page": 12},
        {"raw_name": "净利润（扣非前）", "value_raw": "870.00", "unit": "亿元", "page": 12},
    ]
    for name, val, unit, page in extract_rows(sample):
        print(f"{name} -> value={val} {unit} (page={page})")
