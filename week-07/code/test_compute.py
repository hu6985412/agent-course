#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""compute_qa.py 纯函数单测：find_metric 打分 + safe_eval 沙箱拦截。"""
import compute_qa as c


def test_find_metric_exact():
    name, val, score = c.find_metric("营业收入_2026H1")
    assert score == 100 and val == 509100.0


def test_find_metric_alias():
    name, val, score = c.find_metric("营收")
    assert name == "营业收入_2026H1" and val == 509100.0


def test_find_metric_substring_lower():
    # 子串匹配得分应低于精确匹配
    _, _, s_exact = c.find_metric("营业收入_2026H1")
    assert s_exact == 100


def test_safe_eval_blocks_call():
    try:
        c.safe_eval("__import__('os')", {})
        raise AssertionError("应拦截 __import__")
    except (ValueError, SyntaxError):
        pass


def test_safe_eval_blocks_unknown_name():
    try:
        c.safe_eval("a+b", {})
        raise AssertionError("应拦截未定义变量")
    except ValueError:
        pass


def test_safe_eval_blocks_attr():
    try:
        c.safe_eval("METRICS.values", {"METRICS": {}})
        raise AssertionError("应拦截属性访问")
    except ValueError:
        pass


def test_run_growth():
    r = c.run("营业收入", "(营业收入_2026H1-营业收入_2025H1)/营业收入_2025H1*100", "营业收入_同比")
    assert abs(r - 1.82) < 1e-6


if __name__ == "__main__":
    test_find_metric_exact()
    test_find_metric_alias()
    test_find_metric_substring_lower()
    test_safe_eval_blocks_call()
    test_safe_eval_blocks_unknown_name()
    test_safe_eval_blocks_attr()
    test_run_growth()
    print("test_compute.py 全部通过 ✅")
