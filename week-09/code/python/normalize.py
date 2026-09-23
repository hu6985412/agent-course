"""W09 指标语义层核心：normalize(raw_name) -> 四级匹配 + 否定词保护 + 易混淆组检测。

MVP 实现：
  L1 精确命中（基于 L2 归一后的别名）
  L2 规则归一（全半角/空白/系统性改写/尾部单位注释）
  L3 模糊匹配（编辑距离；仅非受保护字段启用）
  L4 向量匹配（MVP 禁用，需 embedding 服务；对受保护字段永不启用）
  L0 未匹配队列（进 fin_indicator_unknown，绝不静默错配）

铁律：raw 含修饰词（扣非/扣除/非经常/母公司/归母/少数股东）-> 禁止 L3/L4，
      只允许 L1/L2 精确；无精确命中即进 unknown。
"""
import os
import re
import sys
import json
import difflib

import db

# 否定词保护：raw 含这些修饰词 -> 禁止 L3/L4 宽松匹配，只允许 L1/L2 精确
MODIFIER_TOKENS = ["扣非", "扣除", "非经常", "母公司", "归母", "少数股东"]

# L3 模糊阈值 & 同组冲突分差
FUZZY_THRESHOLD = 0.85
GROUP_CONFLICT_MARGIN = 0.10  # 同组两候选分差 <= 此值 -> 冲突

_cache = None


def load_indicators():
    global _cache
    if _cache is not None:
        return _cache
    conn = db.get_conn()
    rows = []
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT code,name,aliases,confusing_group,requires_modifier_guard "
                "FROM fin_indicators"
            )
            for r in cur.fetchall():
                aliases = r["aliases"]
                if isinstance(aliases, str):
                    aliases = json.loads(aliases)
                rows.append(
                    {
                        "code": r["code"],
                        "name": r["name"],
                        "aliases": aliases,
                        "confusing_group": r["confusing_group"],
                        "guard": bool(r["requires_modifier_guard"]),
                    }
                )
    finally:
        conn.close()
    _cache = rows
    return rows


def l2_normalize(s):
    s = s.strip()
    s = s.replace("（", "(").replace("）", ")")  # 全角->半角括号
    s = "".join(ch for ch in s if not ch.isspace())  # 去空白
    s = s.replace("归属于", "归属")  # 系统性改写：归属于 -> 归属
    s = re.sub(r"[（(](元|%|万元)[)）]\s*$", "", s)  # 去除尾部单位注释
    return s


def has_modifier(raw):
    return any(tok in raw for tok in MODIFIER_TOKENS)


def normalize(raw_name, report_id=None, page=None):
    inds = load_indicators()
    norm = l2_normalize(raw_name)
    guarded = has_modifier(raw_name)

    # ---------- L1 精确命中（基于 L2 归一后的别名）----------
    for ind in inds:
        for alias in ind["aliases"]:
            if l2_normalize(alias) == norm:
                return _decide(ind, "L1", 1.0, guarded, raw_name,
                               reason="L1 精确命中")

    # ---------- 受保护字段：禁止 L3/L4，无精确命中即进 unknown ----------
    if guarded:
        return _unknown(raw_name, reason="受否定词保护(含修饰词)，无精确 alias，禁止宽松匹配")

    # ---------- L3 模糊匹配（仅非受保护字段）----------
    candidates = []
    for ind in inds:
        for alias in ind["aliases"]:
            na = l2_normalize(alias)
            if not na:
                continue
            if na == norm:
                score = 1.0
            elif na in norm or norm in na:
                score = 0.95  # 包含关系给高分但不满
            else:
                score = difflib.SequenceMatcher(None, norm, na).ratio()
            if score >= FUZZY_THRESHOLD:
                candidates.append((ind, score))

    if not candidates:
        return _unknown(raw_name, reason="L3 无候选 >= 阈值")

    # 易混淆组冲突检测：同组多命中且分差很小 -> 进 unknown
    candidates.sort(key=lambda x: -x[1])
    top = candidates[0]
    same_group = [
        c
        for c in candidates
        if c[0]["confusing_group"]
        and c[0]["confusing_group"] == top[0]["confusing_group"]
    ]
    if len(same_group) >= 2 and (same_group[0][1] - same_group[1][1]) <= GROUP_CONFLICT_MARGIN:
        return _unknown(raw_name, reason="易混淆组冲突(同组多命中)")

    # 近似指标守卫：若 raw 完整包含另一个【非 top】指标的精确 alias（len>=4），
    # 说明 raw 实际指向那个更具体的已收录指标 -> 歧义，进 unknown（不猜）。
    # 这是 L3 的第二道护栏：防"稀释每股收益"被"每股收益"子串吸进 BASIC_EPS 这类跨指标误吸收。
    for ind in inds:
        if ind is top[0]:
            continue
        for alias in ind["aliases"]:
            a = l2_normalize(alias)
            if a and a != norm and a in norm and len(a) >= 4:
                return _unknown(raw_name, reason="近似指标守卫：raw 含另一指标专有别名，疑似指向更具体指标")

    ind, score = top
    return _decide(ind, "L3", score, guarded, raw_name, reason="L3 模糊命中")


def _decide(ind, method, score, guarded, raw_name, reason):
    return {
        "status": "matched",
        "matched_code": ind["code"],
        "name": ind["name"],
        "method": method,
        "confidence": round(score, 4),
        "guarded": guarded,
        "raw_name": raw_name,
        "reason": reason,
    }


def _unknown(raw_name, reason):
    return {
        "status": "unknown",
        "matched_code": None,
        "raw_name": raw_name,
        "reason": reason,
    }


def persist(report_id, raw_name, value, unit, page, decision):
    """把归一化结果落库：命中 -> fin_report_items；未命中 -> fin_indicator_unknown。"""
    conn = db.get_conn()
    try:
        with conn.cursor() as cur:
            if decision["status"] == "matched":
                cur.execute(
                    "INSERT INTO fin_report_items "
                    "(report_id,raw_name,matched_code,value,unit,page,confidence,method) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        report_id,
                        raw_name,
                        decision["matched_code"],
                        value,
                        unit,
                        page,
                        decision["confidence"],
                        decision["method"],
                    ),
                )
            else:
                cur.execute(
                    "INSERT INTO fin_indicator_unknown (raw_name,report_id,page,reason) "
                    "VALUES (%s,%s,%s,%s)",
                    (raw_name, report_id, page, decision["reason"]),
                )
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    tests = [
        "归属于母公司股东的扣除非经常性损益的净利润",  # 核心：L1 -> NP_DEDUCT（零误匹配证明）
        "扣非归母净利润",                              # guarded L1 -> NP_DEDUCT
        "归母净利润",                                # guarded L1 -> NP_PARENT（未被错配为扣非）
        "净利润",                                   # L1 -> NET_PROFIT（独立可区分字段，不进 unknown）
        "净利润（扣非前）",                          # L1 -> NET_PROFIT（上轮补的 alias，印证纠偏）
        "稀释每股收益",                              # L1 -> DILUTED_EPS（本轮回填，防误配 BASIC_EPS）
        "基本每股收益",                             # L1 -> BASIC_EPS
        "扣非后的归母净利润",                        # guarded 无精确 alias -> unknown(否定词保护)
        "归属于上市公司股东净利润",                   # 缺字歧义 -> unknown(易混淆组)
        "乱七八糟的科目",                            # 无命中 -> unknown(L0)
    ]
    for t in tests:
        print(f"{t}\n   -> {normalize(t)}\n")
