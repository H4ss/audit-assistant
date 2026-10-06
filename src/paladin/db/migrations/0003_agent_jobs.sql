-- P3 : jobs d'agent réels (bail jeton, consommation, coût) et présence de l'agent.

-- Jeton de bail : seul le détenteur courant peut soumettre (un agent repris après crash est rejeté).
ALTER TABLE job ADD COLUMN lease_token TEXT;
-- Consommation déclarée par le client (tokens, coût en USD si disponible) et modèle résolu.
ALTER TABLE job ADD COLUMN usage_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE job ADD COLUMN cost_usd REAL;
ALTER TABLE job ADD COLUMN model_requested TEXT;
ALTER TABLE job ADD COLUMN model_resolved TEXT;
ALTER TABLE job ADD COLUMN validation_errors INTEGER NOT NULL DEFAULT 0;

-- Présence d'un agent : dernière activité par travailleur.
CREATE TABLE agent_presence (
    worker          TEXT PRIMARY KEY,
    campaign_id     TEXT,
    last_seen_at    TEXT NOT NULL,
    last_action     TEXT NOT NULL
);
