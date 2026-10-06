import sqlite3

_CONN = None


def get_conn():
    global _CONN
    if _CONN is None:
        _CONN = sqlite3.connect("shop.db")
    return _CONN


def run_query(sql, params=()):
    cur = get_conn().cursor()
    cur.execute(sql, params)
    return cur.fetchall()
