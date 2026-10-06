from flask import request, send_file

from billing.paths import safe_join

DOWNLOAD_ROOT = "/srv/shop/invoices"


def download_invoice():
    name = request.args.get("file", "")
    target = safe_join(DOWNLOAD_ROOT, name)
    return send_file(target)
