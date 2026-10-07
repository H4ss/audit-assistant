-- P6 : jeu de référence, règles et lots.

-- Finding du jeu de référence : sa décision n'est jamais montrée à l'agent (mesure des régressions).
ALTER TABLE finding ADD COLUMN is_reference INTEGER NOT NULL DEFAULT 0;

-- Règle : verdict et commentaire proposés quand ses conditions sont réunies (jamais appliqués seuls).
ALTER TABLE rule ADD COLUMN verdict TEXT;
ALTER TABLE rule ADD COLUMN comment TEXT;
ALTER TABLE rule ADD COLUMN source_decision_id TEXT;
ALTER TABLE rule ADD COLUMN created_by TEXT;
ALTER TABLE rule ADD COLUMN revoked_by TEXT;
ALTER TABLE rule ADD COLUMN revoke_reason TEXT;

ALTER TABLE batch ADD COLUMN campaign_id TEXT;
ALTER TABLE batch ADD COLUMN undo_report_json TEXT;
