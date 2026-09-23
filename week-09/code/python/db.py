"""W09 财报 Agent - MySQL 连接（运行时，连已存在的 fin_agent 库）。
只读/查询账号思路：生产用 fin_ro 角色仅 GRANT SELECT；MVP 本地 root 空密码。
"""
import os
import pymysql
from pymysql.cursors import DictCursor


def get_conn():
    return pymysql.connect(
        host=os.getenv("FIN_DB_HOST", "127.0.0.1"),
        port=int(os.getenv("FIN_DB_PORT", "3306")),
        user=os.getenv("FIN_DB_USER", "root"),
        password=os.getenv("FIN_DB_PASS", ""),
        database=os.getenv("FIN_DB_NAME", "fin_agent"),
        charset="utf8mb4",
        cursorclass=DictCursor,
    )
