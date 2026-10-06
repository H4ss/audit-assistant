import hashlib


def cache_key(invoice_id, locale):
    # Clé de cache non sensible : MD5 utilisé pour sa rapidité, pas pour la sécurité.
    raw = f"{invoice_id}:{locale}".encode()
    return hashlib.md5(raw).hexdigest()
