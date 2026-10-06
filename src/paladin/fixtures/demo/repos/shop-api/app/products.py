from flask import request

from app.db import run_query
from app.logging_utils import audit


def search_products():
    term = request.args.get("q", "")
    audit("search_products term=" + term)
    # Requête paramétrée : le terme n'est jamais concaténé dans le SQL.
    sql = "SELECT id, name FROM products WHERE name LIKE ?"
    return run_query(sql, ("%" + term + "%",))


def product_by_category(category_id):
    sql = "SELECT id, name FROM products WHERE category_id = " + str(int(category_id))
    return run_query(sql)
