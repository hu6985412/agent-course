"""W09 query_indicator 工具（确定性查询，MVP 不调 LLM）。

安全边界（呼应 ④ NL2SQL）：
  - 只查 fin_* 表（白名单）
  - 参数化 prepared statement（值不拼 SQL）
  - 生产用 fin_ro 只读账号
  - 这里确定性按 (company_code, year, matched_code) 查，根本不碰 SQL 拼接

后续若接自然语言问值：模型只产出"结构化意图"(公司/年份/科目 code)，
执行层用本函数绑定参数，绝不让模型直拼 SQL 字符串（防 OR 1=1 类结构注入）。
"""
import db


def query_indicator(company_code, year, matched_code):
    """按 公司代码 + 年度 + 标准科目 code 查已归一化落库的值。"""
    conn = db.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.name AS company, c.code, r.year,
                       i.matched_code, i.value, i.unit, i.method, i.confidence
                FROM fin_report_items i
                JOIN fin_reports r ON r.id = i.report_id
                JOIN fin_companies c ON c.id = r.company_id
                WHERE c.code = %s AND r.year = %s AND i.matched_code = %s
                """,
                (company_code, year, matched_code),
            )
            return cur.fetchone()
    finally:
        conn.close()
