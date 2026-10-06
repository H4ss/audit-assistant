import html

from flask import request


def render_profile():
    nickname = request.args.get("nickname", "")
    safe = html.escape(nickname, quote=True)
    return "<p>Bonjour " + safe + "</p>"
