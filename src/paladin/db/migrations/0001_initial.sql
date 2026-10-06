-- Paladin — schéma initial.
-- Conventions :
--   * identifiants internes TEXT (uuid4 hex) ; jamais un numéro de ligne Excel ;
--   * horodatages TEXT ISO-8601 UTC ;
--   * colonnes *_json : JSON sérialisé ;
--   * historique append-only pour décisions, analyses et événements de lien.

CREATE TABLE campaign (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    config_json   TEXT NOT NULL DEFAULT '{}',
    is_demo       INTEGER NOT NULL DEFAULT 0,
    revision      INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

-- Outil source d'une campagne (Fortify, ToolB...). `label` est le libellé
-- canonique utilisé dans `Found in <label>`.
CREATE TABLE tool (
    id            TEXT PRIMARY KEY,
    campaign_id   TEXT NOT NULL REFERENCES campaign(id),
    label         TEXT NOT NULL,
    kind          TEXT NOT NULL,            -- fortify | excel_md | md | excel
    sheet_name    TEXT,                     -- onglet cible, NULL si pas encore de schéma
    created_at    TEXT NOT NULL,
    UNIQUE (campaign_id, label)
);

-- Fichier ou capture brute reçue (provenance).
CREATE TABLE source_file (
    id            TEXT PRIMARY KEY,
    campaign_id   TEXT NOT NULL REFERENCES campaign(id),
    tool_id       TEXT REFERENCES tool(id),
    role          TEXT NOT NULL,            -- SourceRole
    original_path TEXT NOT NULL,
    stored_path   TEXT NOT NULL,            -- copie dans l'espace de campagne
    sha256        TEXT NOT NULL,
    size_bytes    INTEGER NOT NULL,
    received_at   TEXT NOT NULL
);
CREATE INDEX ix_source_file_hash ON source_file (campaign_id, sha256);

CREATE TABLE import_run (
    id              TEXT PRIMARY KEY,
    campaign_id     TEXT NOT NULL REFERENCES campaign(id),
    tool_id         TEXT NOT NULL REFERENCES tool(id),
    source_kind     TEXT NOT NULL,          -- fortify_api | fortify_fixture | md | excel
    source_file_id  TEXT REFERENCES source_file(id),
    profile         TEXT,                   -- profil MD déclaré, mapping Excel...
    scope_json      TEXT NOT NULL DEFAULT '{}',  -- application, version (nom + id réel), filtres
    expected_total  INTEGER,                -- total annoncé par la source si disponible
    imported_total  INTEGER NOT NULL DEFAULT 0,
    completeness    TEXT NOT NULL DEFAULT 'unknown',  -- Completeness
    status          TEXT NOT NULL,          -- running | done | failed | partial
    report_json     TEXT NOT NULL DEFAULT '{}',       -- sections non reconnues, anomalies...
    started_at      TEXT NOT NULL,
    finished_at     TEXT
);

CREATE TABLE finding (
    id                  TEXT PRIMARY KEY,
    campaign_id         TEXT NOT NULL REFERENCES campaign(id),
    tool_id             TEXT NOT NULL REFERENCES tool(id),
    scope_key           TEXT NOT NULL,      -- outil|application|version : contexte de l'identifiant source
    source_id           TEXT NOT NULL,      -- identifiant natif ou empreinte
    source_id_kind      TEXT NOT NULL,      -- SourceIdKind
    fingerprint         TEXT NOT NULL,      -- empreinte de contenu (détection de changement)
    application_name    TEXT,
    version_name        TEXT,
    version_source_id   TEXT,
    category            TEXT,
    fortify_category    TEXT,
    primary_rule_id     TEXT,
    analyzer_type       TEXT,
    primary_location    TEXT,
    line_number         INTEGER,
    full_filename       TEXT,
    normalized_path     TEXT,               -- chemin normalisé pour comparaison (jamais exporté)
    function_name       TEXT,
    criticality_raw     TEXT,
    cwe_ids_json        TEXT NOT NULL DEFAULT '[]',
    source_comments     TEXT,
    details_json        TEXT NOT NULL DEFAULT '{}',   -- description, recommandation, trace, extra
    repo_id             TEXT,
    commit_sha          TEXT,
    revision            INTEGER NOT NULL DEFAULT 1,   -- version attendue pour toute écriture
    processing_state    TEXT NOT NULL DEFAULT 'imported',
    review_state        TEXT NOT NULL DEFAULT 'to_review',
    export_state        TEXT NOT NULL DEFAULT 'not_exported',
    current_decision_id TEXT,                         -- dernier DecisionEvent effectif
    discussion_required INTEGER NOT NULL DEFAULT 0,
    discussion_reason   TEXT,
    discussion_state    TEXT,                         -- open | discussed | closed
    first_import_id     TEXT REFERENCES import_run(id),
    last_import_id      TEXT REFERENCES import_run(id),
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    UNIQUE (campaign_id, tool_id, scope_key, source_id)
);
CREATE INDEX ix_finding_queue ON finding (campaign_id, review_state, processing_state);
CREATE INDEX ix_finding_rule ON finding (campaign_id, primary_rule_id);
CREATE INDEX ix_finding_path ON finding (campaign_id, normalized_path);

-- Collisions d'empreinte : exposées, jamais fusionnées silencieusement.
CREATE TABLE fingerprint_collision (
    id              TEXT PRIMARY KEY,
    campaign_id     TEXT NOT NULL REFERENCES campaign(id),
    finding_id      TEXT NOT NULL REFERENCES finding(id),
    import_run_id   TEXT NOT NULL REFERENCES import_run(id),
    locator         TEXT NOT NULL,
    payload_json    TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'open',   -- open | resolved_same | resolved_distinct
    created_at      TEXT NOT NULL
);

-- Enregistrement brut de chaque source (ligne Excel, section MD, issue Fortify).
CREATE TABLE source_record (
    id              TEXT PRIMARY KEY,
    import_run_id   TEXT NOT NULL REFERENCES import_run(id),
    source_file_id  TEXT REFERENCES source_file(id),
    finding_id      TEXT REFERENCES finding(id),
    role            TEXT NOT NULL,          -- SourceRole
    locator         TEXT NOT NULL,          -- onglet!ligne:clé, section MD + offsets, page API...
    record_hash     TEXT NOT NULL,
    payload_json    TEXT NOT NULL,
    match_state     TEXT,                   -- MatchState (intra-outil)
    match_detail    TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX ix_source_record_finding ON source_record (finding_id);

-- Provenance par champ ; plusieurs valeurs concurrentes possibles (Excel vs MD).
CREATE TABLE field_value (
    id              TEXT PRIMARY KEY,
    finding_id      TEXT NOT NULL REFERENCES finding(id),
    field           TEXT NOT NULL,
    value_json      TEXT NOT NULL,
    source_record_id TEXT NOT NULL REFERENCES source_record(id),
    selected        INTEGER NOT NULL DEFAULT 0,      -- valeur retenue
    selection_reason TEXT,                          -- priorité validée, résolution manuelle...
    created_at      TEXT NOT NULL
);
CREATE INDEX ix_field_value_finding ON field_value (finding_id, field);

-- Dépôts de code autorisés et correspondance scan/commit.
CREATE TABLE repo (
    id              TEXT PRIMARY KEY,
    campaign_id     TEXT NOT NULL REFERENCES campaign(id),
    name            TEXT NOT NULL,
    path            TEXT NOT NULL,
    commit_sha      TEXT,
    scanner_roots_json TEXT NOT NULL DEFAULT '[]',  -- préfixes de chemins scanner à retirer
    created_at      TEXT NOT NULL,
    UNIQUE (campaign_id, name)
);

-- Schéma d'onglet (mapping par onglet, versionné).
CREATE TABLE sheet_schema (
    id              TEXT PRIMARY KEY,
    campaign_id     TEXT NOT NULL REFERENCES campaign(id),
    tool_id         TEXT NOT NULL REFERENCES tool(id),
    version         INTEGER NOT NULL,
    sheet_name      TEXT NOT NULL,
    mode            TEXT NOT NULL,          -- complete_existing | generate_rows
    row_key_json    TEXT NOT NULL,          -- colonnes formant la clé stable
    columns_json    TEXT NOT NULL,          -- en-tête réel <-> clé interne, éditable ?, transformation
    status          TEXT NOT NULL,          -- SchemaStatus
    proposed_by     TEXT NOT NULL,          -- human | agent:<modèle> | default
    proposal_json   TEXT,                   -- SheetSchemaProposal d'origine
    validated_at    TEXT,
    created_at      TEXT NOT NULL,
    UNIQUE (tool_id, version)
);

CREATE TABLE target_binding (
    id              TEXT PRIMARY KEY,
    finding_id      TEXT NOT NULL REFERENCES finding(id),
    workbook_ref    TEXT NOT NULL,
    sheet_name      TEXT NOT NULL,
    row_key_json    TEXT NOT NULL,
    schema_id       TEXT NOT NULL REFERENCES sheet_schema(id),
    input_fingerprint TEXT NOT NULL,
    status          TEXT NOT NULL,          -- bound | unmatched | collision | new_row_proposal
    created_at      TEXT NOT NULL,
    UNIQUE (finding_id, workbook_ref, sheet_name)
);

-- Jobs d'agent avec réservation temporaire (bail).
CREATE TABLE job (
    id              TEXT PRIMARY KEY,
    campaign_id     TEXT NOT NULL REFERENCES campaign(id),
    finding_id      TEXT REFERENCES finding(id),
    kind            TEXT NOT NULL,          -- JobKind
    status          TEXT NOT NULL,          -- JobStatus
    input_revision  INTEGER,
    attempt         INTEGER NOT NULL DEFAULT 0,
    lease_owner     TEXT,
    lease_expires_at TEXT,
    payload_json    TEXT NOT NULL DEFAULT '{}',
    error           TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX ix_job_queue ON job (campaign_id, status, kind);
-- Au plus un job d'analyse actif par finding.
CREATE UNIQUE INDEX ux_job_active ON job (finding_id, kind)
    WHERE status IN ('pending', 'claimed');

CREATE TABLE analysis (
    id              TEXT PRIMARY KEY,
    finding_id      TEXT NOT NULL REFERENCES finding(id),
    job_id          TEXT REFERENCES job(id),
    seq             INTEGER NOT NULL,       -- version de l'analyse pour ce finding
    input_revision  INTEGER NOT NULL,
    proposed_verdict TEXT NOT NULL,         -- Verdict (interne)
    summary         TEXT NOT NULL,
    suggested_comment TEXT NOT NULL DEFAULT '',
    discussion_required INTEGER NOT NULL DEFAULT 0,
    discussion_reason TEXT NOT NULL DEFAULT '',
    payload_json    TEXT NOT NULL,          -- AgentProposal complète
    validation_json TEXT NOT NULL DEFAULT '{}',  -- contrôles de schéma et de références
    model_requested TEXT,
    model_provider  TEXT,
    model_resolved  TEXT,                   -- 'unknown' si non disponible
    skill_version   TEXT,
    software_version TEXT NOT NULL,
    context_version TEXT,
    is_simulated    INTEGER NOT NULL DEFAULT 0,  -- proposition de démo, jamais un modèle réel
    created_at      TEXT NOT NULL,
    UNIQUE (finding_id, seq)
);

CREATE TABLE evidence (
    id              TEXT PRIMARY KEY,
    analysis_id     TEXT NOT NULL REFERENCES analysis(id),
    finding_id      TEXT NOT NULL REFERENCES finding(id),
    repo_id         TEXT,
    file_path       TEXT NOT NULL,
    commit_sha      TEXT,
    line_start      INTEGER NOT NULL,
    line_end        INTEGER,
    excerpt         TEXT,
    excerpt_sha256  TEXT,
    note            TEXT,
    reference_check TEXT NOT NULL DEFAULT 'not_checked',  -- verified | mismatch | missing_file | not_checked
    created_at      TEXT NOT NULL
);

-- Journal append-only des décisions. Annuler = nouvel événement UNDO.
CREATE TABLE decision_event (
    id                  TEXT PRIMARY KEY,
    finding_id          TEXT NOT NULL REFERENCES finding(id),
    seq                 INTEGER NOT NULL,
    action              TEXT NOT NULL,      -- DecisionAction
    authority           TEXT NOT NULL,      -- Authority
    author              TEXT NOT NULL,
    analysis_id         TEXT REFERENCES analysis(id),
    verdict             TEXT,               -- TRUE_POSITIVE | NOT_AN_ISSUE | NULL
    comment             TEXT,               -- texte exact `Analysis result comment`
    discussion_required INTEGER NOT NULL DEFAULT 0,
    discussion_reason   TEXT,
    investigation_question TEXT,
    investigation_reason   TEXT,
    correction_category TEXT,               -- écart confirmé (section 11)
    batch_id            TEXT,
    rule_id             TEXT,
    rule_version        INTEGER,
    previous_event_id   TEXT REFERENCES decision_event(id),
    undoes_event_id     TEXT REFERENCES decision_event(id),
    finding_revision    INTEGER NOT NULL,   -- révision du finding au moment de l'écriture
    created_at          TEXT NOT NULL,
    UNIQUE (finding_id, seq)
);

CREATE TABLE draft (
    finding_id      TEXT PRIMARY KEY REFERENCES finding(id),
    verdict         TEXT,
    comment         TEXT,
    updated_at      TEXT NOT NULL
);

CREATE TABLE rule (
    id              TEXT NOT NULL,
    version         INTEGER NOT NULL,
    campaign_id     TEXT REFERENCES campaign(id),   -- NULL = transversale
    title           TEXT NOT NULL,
    conditions_json TEXT NOT NULL,
    scope_json      TEXT NOT NULL,
    exceptions_json TEXT NOT NULL DEFAULT '[]',
    example_json    TEXT,
    counter_example_json TEXT,
    status          TEXT NOT NULL,          -- RuleStatus
    validated_by    TEXT,
    validated_at    TEXT,
    revoked_at      TEXT,
    created_at      TEXT NOT NULL,
    PRIMARY KEY (id, version)
);

CREATE TABLE review_group (
    id              TEXT PRIMARY KEY,
    campaign_id     TEXT NOT NULL REFERENCES campaign(id),
    kind            TEXT NOT NULL,          -- exact_duplicate | root_cause | similar
    rule_id         TEXT,
    rule_version    INTEGER,
    criteria_json   TEXT NOT NULL,
    status          TEXT NOT NULL,          -- open | validated | dissolved
    created_at      TEXT NOT NULL
);

CREATE TABLE group_member (
    group_id        TEXT NOT NULL REFERENCES review_group(id),
    finding_id      TEXT NOT NULL REFERENCES finding(id),
    comparison_json TEXT NOT NULL DEFAULT '{}',  -- contrôles par membre
    eligible        INTEGER NOT NULL DEFAULT 0,
    exclusion_reason TEXT,
    PRIMARY KEY (group_id, finding_id)
);

-- Lot figé : seuls les IDs listés reçoivent une décision.
CREATE TABLE batch (
    id              TEXT PRIMARY KEY,
    group_id        TEXT REFERENCES review_group(id),
    member_ids_json TEXT NOT NULL,
    excluded_json   TEXT NOT NULL DEFAULT '[]',
    verdict         TEXT NOT NULL,
    comment         TEXT,
    rule_id         TEXT,
    rule_version    INTEGER,
    author          TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    undone_at       TEXT
);

CREATE TABLE export_run (
    id              TEXT PRIMARY KEY,
    campaign_id     TEXT NOT NULL REFERENCES campaign(id),
    mode            TEXT NOT NULL,          -- working_copy | final
    source_path     TEXT NOT NULL,
    source_sha256   TEXT,
    destination_path TEXT NOT NULL,
    destination_sha256 TEXT,
    backup_path     TEXT,
    status          TEXT NOT NULL,          -- pending | written | verified | failed | conflict | locked
    summary_json    TEXT NOT NULL DEFAULT '{}',
    error           TEXT,
    created_at      TEXT NOT NULL,
    finished_at     TEXT
);

-- Manifeste : chaque cellule modifiée reliée à sa décision ou à son lien.
CREATE TABLE export_cell (
    export_run_id   TEXT NOT NULL REFERENCES export_run(id),
    finding_id      TEXT REFERENCES finding(id),
    sheet_name      TEXT NOT NULL,
    cell_ref        TEXT NOT NULL,
    column_key      TEXT NOT NULL,
    old_value       TEXT,
    new_value       TEXT,
    decision_event_id TEXT REFERENCES decision_event(id),
    relation_ids_json TEXT,
    PRIMARY KEY (export_run_id, sheet_name, cell_ref)
);

CREATE TABLE comparison_run (
    id              TEXT PRIMARY KEY,
    campaign_id     TEXT NOT NULL REFERENCES campaign(id),
    tool_a_id       TEXT NOT NULL REFERENCES tool(id),
    tool_b_id       TEXT NOT NULL REFERENCES tool(id),
    corpus_json     TEXT NOT NULL,          -- applications, versions, imports comparés
    filters_json    TEXT NOT NULL DEFAULT '{}',
    completeness    TEXT NOT NULL,          -- Completeness ; 'unknown' => projection Unknown
    comparable      INTEGER NOT NULL DEFAULT 0,
    comparator_version TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    reviewed_at     TEXT                    -- recherche revue => autorise 'No confirmed match'
);

CREATE TABLE finding_relation (
    id              TEXT PRIMARY KEY,
    comparison_run_id TEXT NOT NULL REFERENCES comparison_run(id),
    finding_a_id    TEXT NOT NULL REFERENCES finding(id),
    finding_b_id    TEXT NOT NULL REFERENCES finding(id),
    proposed_type   TEXT NOT NULL,          -- RelationType
    confirmed_type  TEXT,
    state           TEXT NOT NULL,          -- RelationState
    score_json      TEXT NOT NULL DEFAULT '{}',
    evidence_json   TEXT NOT NULL DEFAULT '[]',
    differences_json TEXT NOT NULL DEFAULT '[]',
    cross_version   INTEGER NOT NULL DEFAULT 0,
    comparator_version TEXT NOT NULL,
    revision        INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    UNIQUE (finding_a_id, finding_b_id)
);

CREATE TABLE relation_event (
    id              TEXT PRIMARY KEY,
    relation_id     TEXT NOT NULL REFERENCES finding_relation(id),
    action          TEXT NOT NULL,          -- propose | confirm | reject | defer | undo | invalidate
    relation_type   TEXT,
    author          TEXT NOT NULL,
    batch_id        TEXT,
    reason          TEXT,
    created_at      TEXT NOT NULL
);

-- État d'interface durable (finding courant, vue...).
CREATE TABLE ui_state (
    campaign_id     TEXT NOT NULL REFERENCES campaign(id),
    key             TEXT NOT NULL,
    value_json      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    PRIMARY KEY (campaign_id, key)
);
