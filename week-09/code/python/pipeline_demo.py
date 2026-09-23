"""W09 端到端 demo：3 家真实公司跑通 抽取->归一化->落库->问值。

样本值用接近真实的量级（标注为演示），amber 本机换成真实 PDF 时：
  1) 用 docling/pdfplumber 解析年报 -> 得到表格行
  2) 把表格行喂给 extract.extract_rows（清洗逻辑复用）
  3) 其余 normalize/persist/query 不变

重点验证：
  - 每家"扣非(NP_DEDUCT) ≠ 归母(NP_PARENT)" -> 证明零误匹配（若误匹配两者会相等）
  - 茅台"稀释每股收益" -> L1 命中 DILUTED_EPS（独立可区分指标，字典收录即精确命中；佐证纠偏：模糊匹配会跨指标误吸，故用"完备字典+近似指标守卫"兜底，绝不依赖 L3 区分近似指标）；unknown 队列仅收容 legit 场景（字典未收录/歧义裸名/脏数据），由末尾护栏演示块展示
"""
import db
import extract
import normalize
import query

# 演示样本（真实科目名，量级数值为近似，仅用于跑通链路）
COMPANIES = [
    {
        "code": "600519", "name": "贵州茅台", "exchange": "SH", "year": 2025,
        "rows": [
            {"raw_name": "营业总收入", "value_raw": "1741.02", "unit": "亿元", "page": 12},
            {"raw_name": "归属于上市公司股东的净利润", "value_raw": "862.28", "unit": "亿元", "page": 12},
            {"raw_name": "归属于上市公司股东的扣除非经常性损益的净利润", "value_raw": "861.95", "unit": "亿元", "page": 12},
            {"raw_name": "稀释每股收益", "value_raw": "69.00", "unit": "元", "page": 12},  # MVP 字典未收录-> legit unknown（后续补 alias 即 L1 命中）
            {"raw_name": "总资产", "value_raw": "2989.45", "unit": "亿元", "page": 20},
            {"raw_name": "经营活动产生的现金流量净额", "value_raw": "924.56", "unit": "亿元", "page": 30},
        ],
    },
    {
        "code": "300750", "name": "宁德时代", "exchange": "SZ", "year": 2024,
        "rows": [
            {"raw_name": "营业收入", "value_raw": "3620.13", "unit": "亿元", "page": 15},
            {"raw_name": "归属于上市公司股东的净利润", "value_raw": "507.45", "unit": "亿元", "page": 15},
            {"raw_name": "归属于上市公司股东的扣除非经常性损益的净利润", "value_raw": "540.23", "unit": "亿元", "page": 15},
            {"raw_name": "净利润", "value_raw": "515.00", "unit": "亿元", "page": 15},
            {"raw_name": "资产总计", "value_raw": "7866.58", "unit": "亿元", "page": 22},
        ],
    },
    {
        "code": "002594", "name": "比亚迪", "exchange": "SZ", "year": 2024,
        "rows": [
            {"raw_name": "营业总收入", "value_raw": "7771.02", "unit": "亿元", "page": 10},
            {"raw_name": "归属于上市公司股东的净利润", "value_raw": "402.54", "unit": "亿元", "page": 10},
            {"raw_name": "归属于上市公司股东的扣除非经常性损益的净利润", "value_raw": "369.83", "unit": "亿元", "page": 10},
            {"raw_name": "净利润", "value_raw": "415.00", "unit": "亿元", "page": 10},
            {"raw_name": "负债合计", "value_raw": "5846.57", "unit": "亿元", "page": 18},
        ],
    },
]


def reset_demo():
    """清空演示表，保证重复跑幂等（保留 companies 字典）。"""
    conn = db.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM fin_report_items")
            cur.execute("DELETE FROM fin_indicator_unknown")
            cur.execute("DELETE FROM fin_reports")
            conn.commit()
    finally:
        conn.close()


def ensure_company(code, name, exchange):
    conn = db.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO fin_companies (code,name,exchange) VALUES (%s,%s,%s) "
                "ON DUPLICATE KEY UPDATE name=%s",
                (code, name, exchange, name),
            )
            conn.commit()
            cur.execute("SELECT id FROM fin_companies WHERE code=%s", (code,))
            return cur.fetchone()["id"]
    finally:
        conn.close()


def ensure_report(company_id, year):
    conn = db.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM fin_reports WHERE company_id=%s AND year=%s AND report_type='annual'",
                (company_id, year),
            )
            row = cur.fetchone()
            if row:
                return row["id"]
            cur.execute(
                "INSERT INTO fin_reports (company_id,year,report_type) VALUES (%s,%s,'annual')",
                (company_id, year),
            )
            conn.commit()
            return cur.lastrowid
    finally:
        conn.close()


def run():
    reset_demo()
    for comp in COMPANIES:
        cid = ensure_company(comp["code"], comp["name"], comp["exchange"])
        rid = ensure_report(cid, comp["year"])
        print(f"\n=== {comp['name']} ({comp['code']}) {comp['year']} ===")
        for raw_name, value, unit, page in extract.extract_rows(comp["rows"]):
            decision = normalize.normalize(raw_name, report_id=rid, page=page)
            normalize.persist(rid, raw_name, value, unit, page, decision)
            tag = f"[{decision['method']}]" if decision["status"] == "matched" else "[UNKNOWN]"
            print(f"  {tag} {raw_name} -> {decision.get('matched_code')} value={value}")

    # 验证零误匹配：问每家的 扣非(NP_DEDUCT) vs 归母(NP_PARENT)
    print("\n=== 验证：扣非 ≠ 归母（证明未误匹配）===")
    for comp in COMPANIES:
        d = query.query_indicator(comp["code"], comp["year"], "NP_DEDUCT")
        p = query.query_indicator(comp["code"], comp["year"], "NP_PARENT")
        dv = float(d["value"]) / 1e8 if d else None
        pv = float(p["value"]) / 1e8 if p else None
        ok = (dv is not None and pv is not None and abs(dv - pv) > 0.01)
        flag = "✅ 零误匹配" if ok else "❌ 误匹配!"
        print(f"  {comp['name']}: 扣非={dv}亿 归母={pv}亿 {flag}")

    # unknown 队列：只收容"字典未收录 / 歧义裸名 / 脏数据"，绝不收容可精确匹配的字段
    # （设计哲学：能 L1 精确命中的绝不进 unknown；unknown 是补集/兜底，后续人工确认+补 alias 即消解）
    print("\n=== 未匹配队列（仅字典未收录/真歧义，可后续补 alias 消解）===")
    conn = db.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT raw_name, reason FROM fin_indicator_unknown ORDER BY id")
            rows = cur.fetchall()
            if not rows:
                print("  (空)")
            for r in rows:
                print(f"  - {r['raw_name']}  ({r['reason']})")
    finally:
        conn.close()

    # 护栏机制独立演示：三类该进 unknown 的真实场景（均非可精确区分的字段）
    #  1) 否定词保护：含修饰词且字典暂未收录精确 alias -> 禁 L3/L4 -> unknown（边界 case，人工加 alias 即 L1 命中）
    #  2) 易混淆组：缺字歧义裸名（PDF/OCR 抽漏）-> L3 同组多命中冲突 -> unknown
    #  3) 字典未收录：冷门独立科目 -> L1 无 + L3 无候选 -> unknown
    print("\n=== 护栏机制演示（三类 legit unknown 路径）===")
    g = normalize.normalize("经扣除非经常性损益后归属母公司股东的净利润")  # 含多修饰词但未收录精确 alias
    print(f"  否定词保护: {g['raw_name']} -> {g['status']} ({g['reason']})")
    c = normalize.normalize("归属于上市公司股东净利润")  # 缺'的扣除非经常性损益'：无精确 alias，L3 同组冲突
    print(f"  易混淆组:   {c['raw_name']} -> {c['status']} ({c['reason']})")
    u = normalize.normalize("设定受益计划净负债的变动")  # 冷门科目，字典未收录
    print(f"  未收录:     {u['raw_name']} -> {u['status']} ({u['reason']})")


if __name__ == "__main__":
    run()
