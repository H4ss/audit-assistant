from flask import request


def render_search_page():
    term = request.args.get("q", "")
    # La valeur est renvoyée telle quelle dans le HTML.
    return "<h1>Résultats pour " + term + "</h1>"


def render_help_page():
    title = "Aide"
    return "<h1>" + title + "</h1>"
