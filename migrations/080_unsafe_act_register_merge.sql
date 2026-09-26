-- ─────────────────────────────────────────────────────────────────────────────
-- 080 · Fold unsafe acts into the register, one family under one name
--
-- "Unsafe Act" and "Hazard Register" were the same family carried twice. An
-- unsafe act IS a hazard -- the behavioural half of one, next to the physical
-- half -- and the platform modelled them as siblings: two tables, two
-- controllers, two chips in the console, two cards on the manager's tasks tab
-- and two entries in the worker's report menu.
--
-- The register wins, because it is the half with the workflow. It runs all
-- eight stages with real forms behind them (assess, interim control, control
-- hierarchy planning, verification, lesson, close), where the unsafe-act side
-- had a read-only list over the shared report factory. The register keeps its
-- implementation and takes the Unsafe Act name.
--
-- What this migration does NOT do is rename the `hazards` table. It doubles as
-- the organisation-wide hazard *catalogue*, and four unrelated models point at
-- it that way -- incidents.hazard_id, near_misses.hazard_id,
-- risk_reports.hazard_id and working_stations.primary_hazard_id all mean
-- "which catalogued hazard was involved". Renaming it would make those four
-- columns read as nonsense, and `unsafe_acts` is a taken name besides. The
-- physical table stays `hazards`. Everything a user reads says "Unsafe Act".
--
-- The four columns below are what the unsafe-act side carried and the register
-- did not. Without them a fold-in would silently drop the behavioural half of
-- every migrated row -- who was seen doing it, and which rule it broke.
--
-- Nullable and additive. Every existing row stays valid.
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE hazards
    ADD COLUMN act_type VARCHAR(100) NULL COMMENT 'Behavioural: the kind of act observed',
    ADD COLUMN person_observed VARCHAR(255) NULL COMMENT 'Free text - may be a contractor or someone unidentifiable',
    ADD COLUMN rule_violated VARCHAR(255) NULL COMMENT 'Which rule or procedure the act broke',
    ADD COLUMN corrective_advice_given VARCHAR(10) NULL COMMENT 'Whether the observer intervened at the time',
    ADD COLUMN merged_from_unsafe_act_id INT NULL COMMENT 'Set by 078 - the unsafe_acts row this came from, for traceability and rollback';

-- hazards.category_id is NOT NULL, so the migrated rows need a real category
-- rather than the NULL a first cut of this migration tried. One per
-- organisation, created only where it is missing, so re-running is safe.
INSERT INTO hazard_categories (organisation_id, category_name, description)
SELECT DISTINCT
    ua.organisation_id,
    'Behavioural / Unsafe Act',
    'Added by 078 - the behavioural half of the merged Unsafe Act family'
FROM unsafe_acts ua
WHERE NOT EXISTS (
    SELECT 1 FROM (SELECT organisation_id, category_name FROM hazard_categories) hc
    WHERE hc.category_name = 'Behavioural / Unsafe Act'
      AND (hc.organisation_id <=> ua.organisation_id)
);

-- Idempotent on re-run: merged_from_unsafe_act_id is the guard, so a second
-- run inserts nothing rather than duplicating the whole table.
INSERT INTO hazards (
    organisation_id, category_id, hazard_name, description,
    act_type, person_observed, rule_violated, corrective_advice_given,
    location_station_id, logged_by, logged_at,
    reported_severity, severity, register_status,
    evidence_json, merged_from_unsafe_act_id
)
SELECT
    ua.organisation_id,
    COALESCE(hc.id, (SELECT MIN(id) FROM (SELECT id FROM hazard_categories) c)),
    COALESCE(NULLIF(TRIM(ua.act_type), ''), CONCAT('Unsafe act #', ua.id)),
    ua.description,
    ua.act_type,
    ua.person_observed,
    ua.rule_violated,
    ua.corrective_advice_given,
    ua.location_station_id,
    ua.reported_by,
    COALESCE(ua.observed_date_time, ua.reported_at, ua.created_at),
    ua.severity,
    ua.severity,
    CASE ua.workflow_status
        WHEN 'reported'             THEN 'open'
        WHEN 'acknowledged'         THEN 'open'
        WHEN 'under_investigation'  THEN 'under_review'
        WHEN 'escalated'            THEN 'under_review'
        WHEN 'pending_approval'     THEN 'controls_planned'
        WHEN 'capa_open'            THEN 'controls_planned'
        WHEN 'pending_verification' THEN 'pending_verification'
        WHEN 'approved'             THEN 'controlled'
        WHEN 'closed'               THEN 'closed'
        ELSE 'open'
    END,
    ua.evidence_json,
    ua.id
FROM unsafe_acts ua
LEFT JOIN hazard_categories hc
       ON hc.category_name = 'Behavioural / Unsafe Act'
      AND (hc.organisation_id <=> ua.organisation_id)
WHERE NOT EXISTS (
    SELECT 1 FROM (SELECT merged_from_unsafe_act_id FROM hazards) h
    WHERE h.merged_from_unsafe_act_id = ua.id
);

CREATE INDEX idx_hazards_merged_from_unsafe_act
    ON hazards (merged_from_unsafe_act_id);
