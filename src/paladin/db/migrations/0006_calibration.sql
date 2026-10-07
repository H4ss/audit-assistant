-- P8 : calibration de l'agent sur des analyses manuelles.

-- Job « à l'aveugle » : analyse d'un finding du jeu de référence déjà décidé, sans jamais toucher la décision.
ALTER TABLE job ADD COLUMN blind INTEGER NOT NULL DEFAULT 0;
-- Version des conventions d'équipe effectivement montrée à l'agent (fixée à la lecture du contexte).
ALTER TABLE job ADD COLUMN conventions_version INTEGER;
-- Durée mesurée : première réclamation → proposition enregistrée.
ALTER TABLE job ADD COLUMN started_at TEXT;
ALTER TABLE job ADD COLUMN finished_at TEXT;

ALTER TABLE analysis ADD COLUMN is_blind INTEGER NOT NULL DEFAULT 0;
ALTER TABLE analysis ADD COLUMN conventions_version INTEGER;

-- Conventions d'analyse de l'équipe : texte versionné, injecté dans le contexte de l'agent. Jamais modifié en place.
CREATE TABLE team_conventions (
    version         INTEGER PRIMARY KEY,
    text            TEXT NOT NULL,
    note            TEXT NOT NULL DEFAULT '',
    author          TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

-- Décisions montrées à l'agent comme précédents : un finding exposé ne peut plus servir de référence non biaisée.
CREATE TABLE agent_exposure (
    finding_id      TEXT NOT NULL REFERENCES finding(id),
    job_id          TEXT NOT NULL REFERENCES job(id),
    created_at      TEXT NOT NULL,
    PRIMARY KEY (finding_id, job_id)
);

-- Lecture validée d'un classeur d'analyses manuelles, réutilisée pour tout classeur aux mêmes en-têtes.
CREATE TABLE manual_workbook_profile (
    signature       TEXT PRIMARY KEY,
    mapping_json    TEXT NOT NULL,
    value_map_json  TEXT NOT NULL DEFAULT '{}',
    updated_at      TEXT NOT NULL
);
