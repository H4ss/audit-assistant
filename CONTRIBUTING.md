# Norme de code

Vérifier avant chaque commit (la CI bloque sinon) :

```bash
.venv/bin/python -m pip install -r requirements-dev.lock
.venv/bin/ruff check .          # lint (pycodestyle, pyflakes, bugbear, bandit, imports, pathlib, nommage)
.venv/bin/ruff format .         # formatage (lignes de 120)
.venv/bin/python -m pytest -q   # tests
```

Règles du dépôt :

- **Python 3.12+**, annotations de type sur les fonctions publiques, `from __future__ import annotations`.
- **Code en anglais, textes et messages utilisateur en français.** Tout message d'erreur dit quoi faire ensuite (`→ action`).
- **Une exception `# noqa` porte toujours sa justification** sur la même ligne.
- **SQL** : valeurs toujours liées par paramètres `?`. Aucune donnée externe n'est interpolée dans une requête.
- **Contrats** (`contracts.py`), **migrations** (`db/migrations/`) et **verrous** (`requirements*.lock`) : une migration publiée n'est jamais modifiée, on en ajoute une nouvelle.
- **Données** : aucune donnée métier, aucun secret ni classeur réel dans le dépôt. Les fixtures sont synthétiques.
- **Tests** : chaque comportement exigé par la spécification (§15) a un test nommé d'après le scénario. Les tests d'intégration réelle sont marqués `real` et exclus de la CI.
- **Commits** : petits et thématiques (`feat(...)`, `fix(...)`, `test(...)`, `docs:`, `style:`, `chore:`). Une branche `palier/N-...` par palier, mergée sur `main` après validation.
