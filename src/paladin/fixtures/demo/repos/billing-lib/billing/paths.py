import os


def safe_join(root, name):
    candidate = os.path.normpath(os.path.join(root, name))
    if not candidate.startswith(os.path.abspath(root) + os.sep):
        raise ValueError("chemin hors racine")
    return candidate
