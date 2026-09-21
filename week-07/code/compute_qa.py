#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
W07 阶段2 · 计算型问答（通用范式）
======================================================================
有些问题答案不是"原文摘一句"，而是"用报告里几个已知数算出来"
（同比增长率、占比、人均值……）。让 LLM 直接算 = 幻觉 + 算错。

通用四步（与"让 LLM 算"彻底解耦）：
  1) 程序化取数  find_metric：按行标题模糊匹配（打分，排除空标题）
  2) 安全求值    safe_eval ：AST 白名单沙箱，只放 +-*/()^% 和已知变量，
                            禁止 __ / import / 调用
  3) 逐步溯源    每步打印"用了哪个原始数、公式是什么"，句末 [n] 指原始行
  4) 校验        若报告也写了该值，计算值 vs 报告值两端对得上才算可信

本脚本自带一份「示例指标集」(METRICS)，可直接零依赖运行演示四步。
真实运行：把 METRICS 替换成从 600015_20260829_UUMS.pdf 提取的指标
（同样 {变量名: 数值} 结构，变量名用合法标识符即可）。

运行：
  python compute_qa.py                                  # 默认：营业收入同比增长率
  python compute_qa.py --formula "(净利润_2026H1)/总资产_2026H1末*100"   # 算占比类
"""
import os
import sys
import argparse
import ast


# ---------------- 示例指标集（演示用，非真实披露）----------------
# 真实运行请替换为从华夏银行 2026 半年报提取的数字（同样的 {合法标识符: 数值} 结构）。
# 变量名必须是合法 Python 标识符（字母/数字/下划线，可含中文）。
METRICS = {
    "营业收入_2026H1": 509100.0,
    "营业收入_2025H1": 500000.0,
    "营业收入_同比": 1.82,            # 报告原文写明的同比（演示校验用）
    "净利润_2026H1": 119800.0,
    "总资产_2026H1末": 4578000.0,
}

# 口语 / 简称 -> 规范变量名（find_metric 也按变量名本身打分）
ALIASES = {
    "营业收入": "营业收入_2026H1",
    "营收": "营业收入_2026H1",
    "上年同期营业收入": "营业收入_2025H1",
    "去年同期营收": "营业收入_2025H1",
    "净利润": "净利润_2026H1",
    "总资产": "总资产_2026H1末",
    "同比增长率": "营业收入_同比",
}


# ---------------- 1) 程序化取数：模糊匹配行标题 ----------------
def _match_score(name, query):
    n, q = name.lower(), query.lower()
    if not n or not q:
        return 0
    if n == q:
        return 100
    if n.startswith(q) or n.endswith(q):
        return 80
    if q in n:
        return 60
    if n in q:
        return 40
    return 0


def find_metric(query):
    """全局打分最优匹配；空标题/空查询直接淘汰，避免子串误撞。"""
    best_key, best_score = None, 0
    pool = {**METRICS, **ALIASES}
    for name in pool:
        s = _match_score(name, query)
        if s > best_score:
            best_key, best_score = name, s
    if best_score == 0:
        raise KeyError(f"指标库未匹配到『{query}』")
    # 若命中别名，解析回规范变量名与数值
    key = ALIASES.get(best_key, best_key)
    return key, METRICS[key], best_score


# ---------------- 2) 安全求值：AST 白名单沙箱 ----------------
_ALLOWED = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name, ast.Load,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod,
    ast.USub, ast.UAdd, ast.Tuple, ast.List,
)


def safe_eval(expr, env):
    tree = ast.parse(expr, mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED):
            raise ValueError(f"禁止的表达式节点：{type(node).__name__}")
        if isinstance(node, ast.Name) and node.id not in env:
            raise ValueError(f"未定义的变量：{node.id}")
    return eval(compile(tree, "<calc>", "eval"), {"__builtins__": {}}, env)


# ---------------- 3)+4) 计算 + 逐步溯源 + 校验 ----------------
def run(metric_query, expr, stated_query=None):
    name, val, score = find_metric(metric_query)
    print(f"[取数] 命中『{name}』= {val}  (匹配分 {score})")
    result = safe_eval(expr, METRICS)
    print(f"[求值] {expr} = {round(result, 4)}")
    print("[溯源] 变量来源（句末 [n] 指原始指标行）：")
    for i, k in enumerate(sorted(METRICS), 1):
        print(f"       [{i}] {k} = {METRICS[k]}")
    if stated_query:
        sname, sval, _ = find_metric(stated_query)
        ok = abs(result - sval) < 1e-6
        print(f"[校验] 计算值 {round(result, 4)} vs 报告原文『{sname}』= {sval} -> "
              f"{'✅ 对得上' if ok else '❌ 偏差 ' + str(abs(result - sval))}")
        if not ok:
            raise AssertionError("计算值与报告原文不符，请核查取数或公式")
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--metric", default="营业收入", help="取数查询（交给 find_metric 模糊匹配）")
    ap.add_argument("--formula",
                    default="(营业收入_2026H1-营业收入_2025H1)/营业收入_2025H1*100",
                    help="安全求值表达式（变量名须是 METRICS 的键）")
    ap.add_argument("--stated", default="营业收入_同比",
                    help="报告原文也写明的同值，用于校验；留空则不校验")
    args = ap.parse_args()
    print("=== 计算型问答（通用范式）演示 ===")
    run(args.metric, args.formula, args.stated or None)


if __name__ == "__main__":
    main()
