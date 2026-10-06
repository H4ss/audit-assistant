-- P1 : multi-entrées (profils d'entrée), classification interne, suivi d'export.

-- Classification interne inférée (jamais exportée comme donnée source).
ALTER TABLE finding ADD COLUMN family TEXT;
ALTER TABLE finding ADD COLUMN family_basis TEXT;
ALTER TABLE finding ADD COLUMN analysis_route TEXT;
-- Champs en désaccord entre sources du même outil (Excel vs MD), à résoudre.
ALTER TABLE finding ADD COLUMN divergent_fields_json TEXT NOT NULL DEFAULT '[]';
-- Dernière décision effectivement écrite dans l'Excel (détection d'export périmé).
ALTER TABLE finding ADD COLUMN exported_decision_id TEXT;
ALTER TABLE finding ADD COLUMN exported_run_id TEXT;

-- Profil d'entrée : mapping champs source -> clés internes, proposé puis validé
-- une fois, réutilisé pour toute source de même signature.
CREATE TABLE input_profile (
    id              TEXT PRIMARY KEY,
    campaign_id     TEXT REFERENCES campaign(id),
    name            TEXT NOT NULL,
    source_kind     TEXT NOT NULL,          -- excel | csv | md | sarif | fortify
    signature       TEXT NOT NULL,          -- empreinte des en-têtes / champs détectés
    version         INTEGER NOT NULL,
    mapping_json    TEXT NOT NULL,
    status          TEXT NOT NULL,          -- proposed | validated | superseded | rejected
    proposed_by     TEXT NOT NULL,          -- heuristic | agent:<modèle> | human
    validated_at    TEXT,
    created_at      TEXT NOT NULL,
    UNIQUE (campaign_id, name, version)
);
CREATE INDEX ix_input_profile_sig ON input_profile (signature, status);

-- Classeur cible enregistré : empreinte connue pour détecter une modification externe.
CREATE TABLE target_workbook (
    id              TEXT PRIMARY KEY,
    campaign_id     TEXT NOT NULL REFERENCES campaign(id),
    path            TEXT NOT NULL,
    known_sha256    TEXT,
    updated_at      TEXT NOT NULL,
    UNIQUE (campaign_id, path)
);
