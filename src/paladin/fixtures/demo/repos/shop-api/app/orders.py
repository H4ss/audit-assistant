from flask import request

from app.db import run_query
from app.logging_utils import audit


def list_orders():
    customer = request.args.get("customer", "")
    status = request.args.get("status", "open")
    audit("list_orders customer=" + customer)
    # Construction de requête par concaténation : la valeur vient de la requête HTTP.
    sql = "SELECT id, total FROM orders WHERE customer = '" + customer + "'"
    sql += " AND status = 'open'" if status == "open" else ""
    return run_query(sql)


def order_detail(order_id):
    sql = "SELECT * FROM orders WHERE id = ?"
    return run_query(sql, (order_id,))
