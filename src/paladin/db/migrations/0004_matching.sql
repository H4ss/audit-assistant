-- P5 : rapprochement inter-outils — empreintes pour détecter un changement et ne pas reproposer un rejet.
ALTER TABLE finding_relation ADD COLUMN fingerprint_a TEXT;
ALTER TABLE finding_relation ADD COLUMN fingerprint_b TEXT;
ALTER TABLE finding_relation ADD COLUMN score INTEGER NOT NULL DEFAULT 0;
CREATE INDEX ix_relation_a ON finding_relation (finding_a_id, state);
CREATE INDEX ix_relation_b ON finding_relation (finding_b_id, state);
CREATE INDEX ix_comparison_tools ON comparison_run (campaign_id, tool_a_id, tool_b_id);
