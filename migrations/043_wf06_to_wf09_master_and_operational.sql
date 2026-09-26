-- ══════════════════════════════════════════════════════════════════════════════
-- 043 — WF-06 … WF-09 data layer.
--
-- Implements the "DATA ADDITIONS" block of HSE_Mobile_Architecture_v4: the new
-- master data, the new operational data, and the mandatory cross-cutting
-- metadata every AI-ISMS entity has to carry.
--
--   WF-06  Training, Competence & Human Readiness   (feeds the permit gate)
--   WF-07  Safety Performance Scoring               (aggregates all of them)
--   WF-08  Contractor & High-Risk Work
--   WF-09  Transport & Logistics
--
-- Build order per the spec footer: WF-06 competence + fatigue feed the WF-02
-- permit gate, so they come first. WF-08 and WF-09 consume that gate. WF-07
-- aggregates everything and lands last.
--
-- NOTE: keep statement separators out of comments anywhere in this file.
-- run_migrations.py splits the file on the separator character, so one inside
-- a comment turns into a bogus statement and aborts the run.
--
-- Mandatory metadata on every new entity (AI-ISMS Data Input Architecture v1.0):
--   created_at · last_reviewed_at · last_verified_at · source_system ·
--   jurisdiction · confidence_score · ai_generated · override_history
-- ══════════════════════════════════════════════════════════════════════════════

-- ──────────────────────────────────────────────────────────────────────────────
-- MASTER DATA — defined centrally on web, consumed in the field
-- ──────────────────────────────────────────────────────────────────────────────

-- Certification types (safety-critical flag is what makes the permit gate a hard block)
CREATE TABLE IF NOT EXISTS certification_types (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id     INT           NULL,
    name                VARCHAR(200)  NOT NULL,
    code                VARCHAR(60)   NULL,
    issuing_body        VARCHAR(200)  NULL,
    validity_months     INT           NULL,
    is_safety_critical  TINYINT(1)    NOT NULL DEFAULT 0,
    description         TEXT          NULL,
    created_at          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_reviewed_at    DATETIME      NULL,
    last_verified_at    DATETIME      NULL,
    source_system       VARCHAR(60)   NULL DEFAULT 'web',
    jurisdiction        VARCHAR(60)   NULL,
    confidence_score    DECIMAL(5,2)  NULL,
    ai_generated        TINYINT(1)    NOT NULL DEFAULT 0,
    override_history    JSON          NULL,
    INDEX idx_cert_types_org (organisation_id),
    INDEX idx_cert_types_critical (is_safety_critical)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Competence profile = a named requirement set (usually mirrors a role/job profile)
CREATE TABLE IF NOT EXISTS competence_profiles (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id     INT           NULL,
    name                VARCHAR(200)  NOT NULL,
    role_id             INT           NULL,
    description         TEXT          NULL,
    created_at          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_reviewed_at    DATETIME      NULL,
    last_verified_at    DATETIME      NULL,
    source_system       VARCHAR(60)   NULL DEFAULT 'web',
    jurisdiction        VARCHAR(60)   NULL,
    confidence_score    DECIMAL(5,2)  NULL,
    ai_generated        TINYINT(1)    NOT NULL DEFAULT 0,
    override_history    JSON          NULL,
    INDEX idx_comp_profiles_org (organisation_id),
    INDEX idx_comp_profiles_role (role_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Competence matrix: role → required course/certification → validity period.
-- "Which qualifications each role must hold and for how long" (web-authored,
-- Safety Manager may amend on mobile per the interaction matrix).
CREATE TABLE IF NOT EXISTS competence_matrix (
    id                     INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id        INT           NULL,
    competence_profile_id  INT           NULL,
    role_id                INT           NULL,
    training_program_id    INT           NULL,
    certification_type_id  INT           NULL,
    requirement_name       VARCHAR(200)  NOT NULL,
    is_mandatory           TINYINT(1)    NOT NULL DEFAULT 1,
    is_safety_critical     TINYINT(1)    NOT NULL DEFAULT 0,
    validity_months        INT           NULL,
    permit_types_gated     JSON          NULL,
    created_at             DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at             DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_reviewed_at       DATETIME      NULL,
    last_verified_at       DATETIME      NULL,
    source_system          VARCHAR(60)   NULL DEFAULT 'web',
    jurisdiction           VARCHAR(60)   NULL,
    confidence_score       DECIMAL(5,2)  NULL,
    ai_generated           TINYINT(1)    NOT NULL DEFAULT 0,
    override_history       JSON          NULL,
    INDEX idx_comp_matrix_org (organisation_id),
    INDEX idx_comp_matrix_role (role_id),
    INDEX idx_comp_matrix_profile (competence_profile_id),
    INDEX idx_comp_matrix_critical (is_safety_critical)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Contractor companies — pre-qualification status gates whether a permit may issue
CREATE TABLE IF NOT EXISTS contractor_companies (
    id                       INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id          INT           NULL,
    company_name             VARCHAR(200)  NOT NULL,
    registration_no          VARCHAR(120)  NULL,
    contact_name             VARCHAR(200)  NULL,
    contact_email            VARCHAR(200)  NULL,
    contact_phone            VARCHAR(60)   NULL,
    -- approved | conditional | barred | pending
    prequalification_status  VARCHAR(20)   NOT NULL DEFAULT 'pending',
    prequalified_by          INT           NULL,
    prequalified_at          DATETIME      NULL,
    prequalification_notes   TEXT          NULL,
    insurance_expiry         DATE          NULL,
    ssip_chas_status         VARCHAR(60)   NULL,
    ssip_chas_expiry         DATE          NULL,
    ltifr_3yr                DECIMAL(8,3)  NULL,
    trir_3yr                 DECIMAL(8,3)  NULL,
    approved_site_ids        JSON          NULL,
    suspended                TINYINT(1)    NOT NULL DEFAULT 0,
    suspended_reason         TEXT          NULL,
    created_at               DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at               DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_reviewed_at         DATETIME      NULL,
    last_verified_at         DATETIME      NULL,
    source_system            VARCHAR(60)   NULL DEFAULT 'web',
    jurisdiction             VARCHAR(60)   NULL,
    confidence_score         DECIMAL(5,2)  NULL,
    ai_generated             TINYINT(1)    NOT NULL DEFAULT 0,
    override_history         JSON          NULL,
    INDEX idx_contractor_co_org (organisation_id),
    INDEX idx_contractor_co_status (prequalification_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Individual contractor workers — induction + site access roll-call
CREATE TABLE IF NOT EXISTS contractor_workers (
    id                       INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id          INT           NULL,
    contractor_company_id    INT           NOT NULL,
    full_name                VARCHAR(200)  NOT NULL,
    badge_no                 VARCHAR(120)  NULL,
    trade                    VARCHAR(120)  NULL,
    induction_date           DATE          NULL,
    induction_valid_until    DATE          NULL,
    -- granted | revoked | pending
    site_access_status       VARCHAR(20)   NOT NULL DEFAULT 'pending',
    toolbox_completed_at     DATETIME      NULL,
    created_at               DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at               DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_reviewed_at         DATETIME      NULL,
    last_verified_at         DATETIME      NULL,
    source_system            VARCHAR(60)   NULL DEFAULT 'mobile',
    jurisdiction             VARCHAR(60)   NULL,
    confidence_score         DECIMAL(5,2)  NULL,
    ai_generated             TINYINT(1)    NOT NULL DEFAULT 0,
    override_history         JSON          NULL,
    INDEX idx_contractor_wk_org (organisation_id),
    INDEX idx_contractor_wk_company (contractor_company_id),
    INDEX idx_contractor_wk_badge (badge_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Vehicles — QR-scannable, roadworthiness feeds the WF-09 gate
CREATE TABLE IF NOT EXISTS vehicles (
    id                       INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id          INT           NULL,
    registration             VARCHAR(60)   NOT NULL,
    qr_code                  VARCHAR(120)  NULL,
    vehicle_type             VARCHAR(120)  NULL,
    make_model               VARCHAR(200)  NULL,
    site_id                  INT           NULL,
    roadworthiness_expiry    DATE          NULL,
    insurance_expiry         DATE          NULL,
    last_inspection_at       DATETIME      NULL,
    -- none | minor | major | grounded
    defect_status            VARCHAR(20)   NOT NULL DEFAULT 'none',
    defect_notes             TEXT          NULL,
    active                   TINYINT(1)    NOT NULL DEFAULT 1,
    created_at               DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at               DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_reviewed_at         DATETIME      NULL,
    last_verified_at         DATETIME      NULL,
    source_system            VARCHAR(60)   NULL DEFAULT 'web',
    jurisdiction             VARCHAR(60)   NULL,
    confidence_score         DECIMAL(5,2)  NULL,
    ai_generated             TINYINT(1)    NOT NULL DEFAULT 0,
    override_history         JSON          NULL,
    INDEX idx_vehicles_org (organisation_id),
    INDEX idx_vehicles_qr (qr_code),
    INDEX idx_vehicles_reg (registration)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Weather operating limits by transport mode (WF-09 gate 6)
CREATE TABLE IF NOT EXISTS weather_limit_tables (
    id                   INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id      INT           NULL,
    -- road | rail | marine | air
    transport_mode       VARCHAR(30)   NOT NULL,
    max_wind_kph         DECIMAL(6,2)  NULL,
    min_visibility_m     DECIMAL(8,2)  NULL,
    max_precip_mm_hr     DECIMAL(6,2)  NULL,
    max_wave_height_m    DECIMAL(6,2)  NULL,
    notes                TEXT          NULL,
    created_at           DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at           DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_reviewed_at     DATETIME      NULL,
    last_verified_at     DATETIME      NULL,
    source_system        VARCHAR(60)   NULL DEFAULT 'web',
    jurisdiction         VARCHAR(60)   NULL,
    confidence_score     DECIMAL(5,2)  NULL,
    ai_generated         TINYINT(1)    NOT NULL DEFAULT 0,
    override_history     JSON          NULL,
    INDEX idx_weather_org (organisation_id),
    INDEX idx_weather_mode (transport_mode)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- IOGP benchmark table — contractor LTIFR is judged against this
CREATE TABLE IF NOT EXISTS iogp_benchmarks (
    id                 INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id    INT           NULL,
    benchmark_year     INT           NOT NULL,
    region             VARCHAR(120)  NULL,
    industry           VARCHAR(120)  NULL,
    ltifr_benchmark    DECIMAL(8,3)  NOT NULL,
    trir_benchmark     DECIMAL(8,3)  NULL,
    created_at         DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at         DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_reviewed_at   DATETIME      NULL,
    last_verified_at   DATETIME      NULL,
    source_system      VARCHAR(60)   NULL DEFAULT 'web',
    jurisdiction       VARCHAR(60)   NULL,
    confidence_score   DECIMAL(5,2)  NULL,
    ai_generated       TINYINT(1)    NOT NULL DEFAULT 0,
    override_history   JSON          NULL,
    INDEX idx_iogp_org (organisation_id),
    INDEX idx_iogp_year (benchmark_year)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- CAPA lookup — the 2-3 pre-defined corrective actions each SPS alert offers
CREATE TABLE IF NOT EXISTS capa_lookups (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id     INT           NULL,
    -- sps_alert | gate_block | audit_finding | incident
    trigger_type        VARCHAR(40)   NOT NULL,
    trigger_key         VARCHAR(120)  NOT NULL,
    suggested_action    TEXT          NOT NULL,
    -- engineering | administrative | procedural | supervision | training
    control_type        VARCHAR(40)   NULL,
    default_due_days    INT           NOT NULL DEFAULT 14,
    priority            VARCHAR(20)   NULL,
    created_at          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_reviewed_at    DATETIME      NULL,
    last_verified_at    DATETIME      NULL,
    source_system       VARCHAR(60)   NULL DEFAULT 'web',
    jurisdiction        VARCHAR(60)   NULL,
    confidence_score    DECIMAL(5,2)  NULL,
    ai_generated        TINYINT(1)    NOT NULL DEFAULT 0,
    override_history    JSON          NULL,
    INDEX idx_capa_lookup_org (organisation_id),
    INDEX idx_capa_lookup_trigger (trigger_type, trigger_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ──────────────────────────────────────────────────────────────────────────────
-- OPERATIONAL DATA — captured in the field, reported centrally
-- ──────────────────────────────────────────────────────────────────────────────

-- WF-06 · Training records (C6/B4)
CREATE TABLE IF NOT EXISTS training_records (
    id                       INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id          INT           NULL,
    employee_id              INT           NOT NULL,
    training_program_id      INT           NULL,
    certification_type_id    INT           NULL,
    competence_matrix_id     INT           NULL,
    course_name              VARCHAR(200)  NULL,
    completed_at             DATE          NULL,
    expires_at               DATE          NULL,
    score                    DECIMAL(6,2)  NULL,
    -- pass | fail | pending
    result                   VARCHAR(20)   NULL,
    certificate_ref          VARCHAR(200)  NULL,
    evidence_photo           LONGTEXT      NULL,
    verified_by              INT           NULL,
    verified_at              DATETIME      NULL,
    toolbox_acknowledged_at  DATETIME      NULL,
    created_at               DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at               DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_reviewed_at         DATETIME      NULL,
    last_verified_at         DATETIME      NULL,
    source_system            VARCHAR(60)   NULL DEFAULT 'mobile',
    jurisdiction             VARCHAR(60)   NULL,
    confidence_score         DECIMAL(5,2)  NULL,
    ai_generated             TINYINT(1)    NOT NULL DEFAULT 0,
    override_history         JSON          NULL,
    INDEX idx_training_rec_org (organisation_id),
    INDEX idx_training_rec_emp (employee_id),
    INDEX idx_training_rec_expiry (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- WF-06 · Competence gaps — the supervisor's nightly gap report
CREATE TABLE IF NOT EXISTS competence_gaps (
    id                     INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id        INT           NULL,
    employee_id            INT           NOT NULL,
    competence_matrix_id   INT           NULL,
    requirement_name       VARCHAR(200)  NULL,
    -- missing | expired | expiring_60 | expiring_30 | expiring_7
    gap_type               VARCHAR(30)   NOT NULL,
    is_safety_critical     TINYINT(1)    NOT NULL DEFAULT 0,
    expires_at             DATE          NULL,
    detected_at            DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at            DATETIME      NULL,
    buddy_employee_id      INT           NULL,
    created_at             DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at             DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_reviewed_at       DATETIME      NULL,
    last_verified_at       DATETIME      NULL,
    source_system          VARCHAR(60)   NULL DEFAULT 'server',
    jurisdiction           VARCHAR(60)   NULL,
    confidence_score       DECIMAL(5,2)  NULL,
    ai_generated           TINYINT(1)    NOT NULL DEFAULT 0,
    override_history       JSON          NULL,
    INDEX idx_comp_gap_org (organisation_id),
    INDEX idx_comp_gap_emp (employee_id),
    INDEX idx_comp_gap_type (gap_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- WF-06 · Fatigue declarations (C7 — non-medical, privacy-safe proxies only)
CREATE TABLE IF NOT EXISTS fatigue_declarations (
    id                          INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id             INT           NULL,
    employee_id                 INT           NOT NULL,
    declared_at                 DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    shift_hours                 DECIMAL(5,2)  NOT NULL DEFAULT 0,
    consecutive_days            INT           NOT NULL DEFAULT 0,
    night_shifts_7d             INT           NOT NULL DEFAULT 0,
    task_intensity              VARCHAR(20)   NULL,
    fatigue_index               DECIMAL(6,2)  NOT NULL DEFAULT 0,
    -- acceptable | amber | signoff | block
    band                        VARCHAR(20)   NOT NULL DEFAULT 'acceptable',
    supervisor_ack_by           INT           NULL,
    supervisor_ack_at           DATETIME      NULL,
    supervisor_signoff_by       INT           NULL,
    supervisor_signoff_at       DATETIME      NULL,
    signoff_note                TEXT          NULL,
    exception_by                INT           NULL,
    exception_at                DATETIME      NULL,
    exception_reason            TEXT          NULL,
    created_at                  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at                  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_reviewed_at            DATETIME      NULL,
    last_verified_at            DATETIME      NULL,
    source_system               VARCHAR(60)   NULL DEFAULT 'mobile',
    jurisdiction                VARCHAR(60)   NULL,
    confidence_score            DECIMAL(5,2)  NULL,
    ai_generated                TINYINT(1)    NOT NULL DEFAULT 0,
    override_history            JSON          NULL,
    INDEX idx_fatigue_org (organisation_id),
    INDEX idx_fatigue_emp (employee_id),
    INDEX idx_fatigue_declared (declared_at),
    INDEX idx_fatigue_band (band)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Gate engine · every verdict the deterministic engine produces
CREATE TABLE IF NOT EXISTS gate_decision_log (
    id                    INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id       INT           NULL,
    -- permit | journey
    subject_type          VARCHAR(30)   NOT NULL,
    subject_id            INT           NULL,
    -- rams_linked | competence_verified | fatigue_index | zone_simops |
    -- contractor_approved | weather_journey
    gate_key              VARCHAR(40)   NOT NULL,
    -- pass | amber | block
    verdict               VARCHAR(20)   NOT NULL,
    reason                TEXT          NULL,
    details               JSON          NULL,
    subject_employee_id   INT           NULL,
    evaluated_by          INT           NULL,
    evaluated_at          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at            DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at            DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_reviewed_at      DATETIME      NULL,
    last_verified_at      DATETIME      NULL,
    source_system         VARCHAR(60)   NULL DEFAULT 'server',
    jurisdiction          VARCHAR(60)   NULL,
    confidence_score      DECIMAL(5,2)  NULL,
    ai_generated          TINYINT(1)    NOT NULL DEFAULT 0,
    override_history      JSON          NULL,
    INDEX idx_gate_log_org (organisation_id),
    INDEX idx_gate_log_subject (subject_type, subject_id),
    INDEX idx_gate_log_verdict (verdict),
    INDEX idx_gate_log_key (gate_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- D4 CORE FEATURE · every override captures reason, context and outcome
CREATE TABLE IF NOT EXISTS override_log (
    id                     INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id        INT           NULL,
    gate_decision_id       INT           NULL,
    subject_type           VARCHAR(30)   NULL,
    subject_id             INT           NULL,
    gate_key               VARCHAR(40)   NULL,
    -- accept | amend | reject
    decision               VARCHAR(20)   NOT NULL,
    reason                 TEXT          NOT NULL,
    context                TEXT          NULL,
    outcome                TEXT          NULL,
    original_verdict       VARCHAR(20)   NULL,
    resulting_verdict      VARCHAR(20)   NULL,
    overridden_by          INT           NULL,
    overridden_by_role     VARCHAR(60)   NULL,
    overridden_at          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at             DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at             DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_reviewed_at       DATETIME      NULL,
    last_verified_at       DATETIME      NULL,
    source_system          VARCHAR(60)   NULL DEFAULT 'mobile',
    jurisdiction           VARCHAR(60)   NULL,
    confidence_score       DECIMAL(5,2)  NULL,
    ai_generated           TINYINT(1)    NOT NULL DEFAULT 0,
    override_history       JSON          NULL,
    INDEX idx_override_org (organisation_id),
    INDEX idx_override_gate (gate_decision_id),
    INDEX idx_override_subject (subject_type, subject_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- WF-08 · RAMS scores — 6 criteria × 0-20
CREATE TABLE IF NOT EXISTS rams_scores (
    id                       INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id          INT           NULL,
    contractor_company_id    INT           NULL,
    permit_id                INT           NULL,
    risk_report_id           INT           NULL,
    task_description         TEXT          NULL,
    hazard_identification    INT           NOT NULL DEFAULT 0,
    control_adequacy         INT           NOT NULL DEFAULT 0,
    competence_evidence      INT           NOT NULL DEFAULT 0,
    equipment_suitability    INT           NOT NULL DEFAULT 0,
    emergency_arrangements   INT           NOT NULL DEFAULT 0,
    supervision_arrangements INT           NOT NULL DEFAULT 0,
    total_score              INT           NOT NULL DEFAULT 0,
    -- reject | conditional | approve
    verdict                  VARCHAR(20)   NOT NULL DEFAULT 'reject',
    scored_by                INT           NULL,
    scored_at                DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    auditor_rescored_by      INT           NULL,
    auditor_rescored_at      DATETIME      NULL,
    auditor_total_score      INT           NULL,
    auditor_notes            TEXT          NULL,
    created_at               DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at               DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_reviewed_at         DATETIME      NULL,
    last_verified_at         DATETIME      NULL,
    source_system            VARCHAR(60)   NULL DEFAULT 'mobile',
    jurisdiction             VARCHAR(60)   NULL,
    confidence_score         DECIMAL(5,2)  NULL,
    ai_generated             TINYINT(1)    NOT NULL DEFAULT 0,
    override_history         JSON          NULL,
    INDEX idx_rams_org (organisation_id),
    INDEX idx_rams_company (contractor_company_id),
    INDEX idx_rams_permit (permit_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- WF-08 · Quarterly contractor scorecard
CREATE TABLE IF NOT EXISTS contractor_scorecards (
    id                       INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id          INT           NULL,
    contractor_company_id    INT           NOT NULL,
    period_year              INT           NOT NULL,
    period_quarter           INT           NOT NULL,
    score                    DECIMAL(6,2)  NOT NULL DEFAULT 0,
    avg_rams_score           DECIMAL(6,2)  NULL,
    incident_count           INT           NOT NULL DEFAULT 0,
    permit_violations        INT           NOT NULL DEFAULT 0,
    audit_findings           INT           NOT NULL DEFAULT 0,
    ltifr                    DECIMAL(8,3)  NULL,
    -- ok | enhanced_oversight | contract_review | off_list
    verdict                  VARCHAR(30)   NOT NULL DEFAULT 'ok',
    computed_at              DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at               DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at               DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_reviewed_at         DATETIME      NULL,
    last_verified_at         DATETIME      NULL,
    source_system            VARCHAR(60)   NULL DEFAULT 'server',
    jurisdiction             VARCHAR(60)   NULL,
    confidence_score         DECIMAL(5,2)  NULL,
    ai_generated             TINYINT(1)    NOT NULL DEFAULT 0,
    override_history         JSON          NULL,
    UNIQUE KEY uq_scorecard (contractor_company_id, period_year, period_quarter),
    INDEX idx_scorecard_org (organisation_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- WF-09 · Journey plans (JRS = Route × Mode × Cargo)
CREATE TABLE IF NOT EXISTS journey_plans (
    id                        INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id           INT           NULL,
    employee_id               INT           NOT NULL,
    vehicle_id                INT           NULL,
    origin                    VARCHAR(200)  NULL,
    destination               VARCHAR(200)  NULL,
    -- road | rail | marine | air
    transport_mode            VARCHAR(30)   NOT NULL DEFAULT 'road',
    route_score               INT           NOT NULL DEFAULT 1,
    mode_score                INT           NOT NULL DEFAULT 1,
    cargo_score               INT           NOT NULL DEFAULT 1,
    journey_risk_score        INT           NOT NULL DEFAULT 1,
    -- low | medium | high
    risk_band                 VARCHAR(20)   NOT NULL DEFAULT 'low',
    -- draft | pending_authorisation | authorised | rejected | in_progress | completed
    status                    VARCHAR(30)   NOT NULL DEFAULT 'draft',
    requires_authorisation    TINYINT(1)    NOT NULL DEFAULT 0,
    authorised_by             INT           NULL,
    authorised_at             DATETIME      NULL,
    rejection_reason          TEXT          NULL,
    planned_departure         DATETIME      NULL,
    planned_arrival           DATETIME      NULL,
    actual_departure          DATETIME      NULL,
    actual_arrival            DATETIME      NULL,
    checkin_interval_minutes  INT           NOT NULL DEFAULT 120,
    comms_protocol            VARCHAR(200)  NULL,
    pretrip_completed_at      DATETIME      NULL,
    pretrip_defects           TEXT          NULL,
    weather_snapshot          JSON          NULL,
    created_at                DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at                DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_reviewed_at          DATETIME      NULL,
    last_verified_at          DATETIME      NULL,
    source_system             VARCHAR(60)   NULL DEFAULT 'mobile',
    jurisdiction              VARCHAR(60)   NULL,
    confidence_score          DECIMAL(5,2)  NULL,
    ai_generated              TINYINT(1)    NOT NULL DEFAULT 0,
    override_history          JSON          NULL,
    INDEX idx_journey_org (organisation_id),
    INDEX idx_journey_emp (employee_id),
    INDEX idx_journey_status (status),
    INDEX idx_journey_vehicle (vehicle_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- WF-09 · Timed check-in events (missed check-in → escalation)
CREATE TABLE IF NOT EXISTS check_in_events (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id     INT           NULL,
    journey_plan_id     INT           NOT NULL,
    sequence_no         INT           NOT NULL DEFAULT 1,
    due_at              DATETIME      NOT NULL,
    checked_in_at       DATETIME      NULL,
    missed              TINYINT(1)    NOT NULL DEFAULT 0,
    escalated_at        DATETIME      NULL,
    escalated_to        INT           NULL,
    gps_latitude        DECIMAL(10,7) NULL,
    gps_longitude       DECIMAL(10,7) NULL,
    defects_reported    TEXT          NULL,
    deviations          TEXT          NULL,
    notes               TEXT          NULL,
    created_at          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_reviewed_at    DATETIME      NULL,
    last_verified_at    DATETIME      NULL,
    source_system       VARCHAR(60)   NULL DEFAULT 'mobile',
    jurisdiction        VARCHAR(60)   NULL,
    confidence_score    DECIMAL(5,2)  NULL,
    ai_generated        TINYINT(1)    NOT NULL DEFAULT 0,
    override_history    JSON          NULL,
    INDEX idx_checkin_org (organisation_id),
    INDEX idx_checkin_journey (journey_plan_id),
    INDEX idx_checkin_due (due_at),
    INDEX idx_checkin_missed (missed)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- WF-07 · Safety Performance Score snapshots (weekly batch, five domains)
CREATE TABLE IF NOT EXISTS sps_snapshots (
    id                   INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id      INT           NULL,
    site_id              INT           NULL,
    department_id        INT           NULL,
    employee_id          INT           NULL,
    -- org | site | department | team | employee
    scope                VARCHAR(20)   NOT NULL DEFAULT 'org',
    period_start         DATE          NOT NULL,
    period_end           DATE          NOT NULL,
    hazard_exposure      DECIMAL(6,2)  NOT NULL DEFAULT 0,
    control_integrity    DECIMAL(6,2)  NOT NULL DEFAULT 0,
    work_discipline      DECIMAL(6,2)  NOT NULL DEFAULT 0,
    human_readiness      DECIMAL(6,2)  NOT NULL DEFAULT 0,
    org_health           DECIMAL(6,2)  NOT NULL DEFAULT 0,
    sps                  DECIMAL(6,2)  NOT NULL DEFAULT 0,
    -- critical | high | elevated | acceptable | low
    band                 VARCHAR(20)   NOT NULL DEFAULT 'low',
    data_completeness    DECIMAL(5,2)  NULL,
    stale_data_penalty   DECIMAL(5,2)  NOT NULL DEFAULT 0,
    inputs               JSON          NULL,
    computed_at          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at           DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at           DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_reviewed_at     DATETIME      NULL,
    last_verified_at     DATETIME      NULL,
    source_system        VARCHAR(60)   NULL DEFAULT 'server',
    jurisdiction         VARCHAR(60)   NULL,
    confidence_score     DECIMAL(5,2)  NULL,
    ai_generated         TINYINT(1)    NOT NULL DEFAULT 0,
    override_history     JSON          NULL,
    INDEX idx_sps_org (organisation_id),
    INDEX idx_sps_scope (scope, site_id, employee_id),
    INDEX idx_sps_period (period_start, period_end)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- WF-07 · SPS alerts — fire on Δ ≥ 10 pts/week, band change, or KPI red-line
CREATE TABLE IF NOT EXISTS sps_alerts (
    id                   INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id      INT           NULL,
    sps_snapshot_id      INT           NULL,
    site_id              INT           NULL,
    employee_id          INT           NULL,
    -- delta | band_change | kpi_redline
    alert_type           VARCHAR(30)   NOT NULL,
    delta                DECIMAL(6,2)  NULL,
    previous_band        VARCHAR(20)   NULL,
    new_band             VARCHAR(20)   NULL,
    severity             VARCHAR(20)   NULL,
    message              TEXT          NULL,
    suggested_capa       JSON          NULL,
    acknowledged_by      INT           NULL,
    acknowledged_at      DATETIME      NULL,
    capa_action_id       INT           NULL,
    created_at           DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at           DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_reviewed_at     DATETIME      NULL,
    last_verified_at     DATETIME      NULL,
    source_system        VARCHAR(60)   NULL DEFAULT 'server',
    jurisdiction         VARCHAR(60)   NULL,
    confidence_score     DECIMAL(5,2)  NULL,
    ai_generated         TINYINT(1)    NOT NULL DEFAULT 0,
    override_history     JSON          NULL,
    INDEX idx_sps_alert_org (organisation_id),
    INDEX idx_sps_alert_snapshot (sps_snapshot_id),
    INDEX idx_sps_alert_type (alert_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- AI · every answer stored with a confidence score and the human's decision.
-- "Each answer stored with a confidence score and marked as AI-generated, then
--  the user's decision to accept, amend or reject it is captured."
CREATE TABLE IF NOT EXISTS ai_decision_log (
    id                    INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id       INT           NULL,
    user_id               INT           NULL,
    user_role             VARCHAR(60)   NULL,
    role_bucket           VARCHAR(30)   NULL,
    question              TEXT          NULL,
    answer                LONGTEXT      NULL,
    model_id              VARCHAR(120)  NULL,
    model_version         VARCHAR(60)   NULL,
    provider              VARCHAR(60)   NULL,
    snapshot_hash         VARCHAR(64)   NULL,
    snapshot_built_at     DATETIME      NULL,
    -- accept | amend | reject  (null until the human decides)
    human_decision        VARCHAR(20)   NULL,
    decision_reason       TEXT          NULL,
    amended_answer        LONGTEXT      NULL,
    decided_by            INT           NULL,
    decided_at            DATETIME      NULL,
    created_at            DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at            DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_reviewed_at      DATETIME      NULL,
    last_verified_at      DATETIME      NULL,
    source_system         VARCHAR(60)   NULL DEFAULT 'ai',
    jurisdiction          VARCHAR(60)   NULL,
    confidence_score      DECIMAL(5,2)  NULL,
    ai_generated          TINYINT(1)    NOT NULL DEFAULT 1,
    override_history      JSON          NULL,
    INDEX idx_ai_log_org (organisation_id),
    INDEX idx_ai_log_user (user_id),
    INDEX idx_ai_log_decision (human_decision)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- MOC-Lite · change & drift log (WF-06/08 risk-spike input, C8)
CREATE TABLE IF NOT EXISTS change_events (
    id                   INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id      INT           NULL,
    site_id              INT           NULL,
    -- procedure_update | equipment_mod | staffing_change | temporary_arrangement
    change_type          VARCHAR(40)   NOT NULL,
    title                VARCHAR(200)  NOT NULL,
    description          TEXT          NULL,
    risk_spike_score     DECIMAL(6,2)  NULL,
    effective_from       DATE          NULL,
    effective_to         DATE          NULL,
    raised_by            INT           NULL,
    reviewed_by          INT           NULL,
    reviewed_at          DATETIME      NULL,
    status               VARCHAR(30)   NOT NULL DEFAULT 'open',
    created_at           DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at           DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_reviewed_at     DATETIME      NULL,
    last_verified_at     DATETIME      NULL,
    source_system        VARCHAR(60)   NULL DEFAULT 'mobile',
    jurisdiction         VARCHAR(60)   NULL,
    confidence_score     DECIMAL(5,2)  NULL,
    ai_generated         TINYINT(1)    NOT NULL DEFAULT 0,
    override_history     JSON          NULL,
    INDEX idx_change_org (organisation_id),
    INDEX idx_change_type (change_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Work execution + supervisor interaction events — WF-07 Work Discipline domain
CREATE TABLE IF NOT EXISTS work_execution_events (
    id                   INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id      INT           NULL,
    site_id              INT           NULL,
    employee_id          INT           NULL,
    permit_id            INT           NULL,
    -- permit_bypass | late_closure | poor_closure | repeat_breach | under_permit
    event_type           VARCHAR(40)   NOT NULL,
    detail               TEXT          NULL,
    occurred_at          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at           DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at           DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_reviewed_at     DATETIME      NULL,
    last_verified_at     DATETIME      NULL,
    source_system        VARCHAR(60)   NULL DEFAULT 'server',
    jurisdiction         VARCHAR(60)   NULL,
    confidence_score     DECIMAL(5,2)  NULL,
    ai_generated         TINYINT(1)    NOT NULL DEFAULT 0,
    override_history     JSON          NULL,
    INDEX idx_wee_org (organisation_id),
    INDEX idx_wee_type (event_type),
    INDEX idx_wee_occurred (occurred_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS supervisor_interactions (
    id                   INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id      INT           NULL,
    supervisor_id        INT           NULL,
    employee_id          INT           NULL,
    -- toolbox_talk | safety_walk | coaching | briefing
    interaction_type     VARCHAR(40)   NOT NULL,
    detail               TEXT          NULL,
    occurred_at          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at           DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at           DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_reviewed_at     DATETIME      NULL,
    last_verified_at     DATETIME      NULL,
    source_system        VARCHAR(60)   NULL DEFAULT 'mobile',
    jurisdiction         VARCHAR(60)   NULL,
    confidence_score     DECIMAL(5,2)  NULL,
    ai_generated         TINYINT(1)    NOT NULL DEFAULT 0,
    override_history     JSON          NULL,
    INDEX idx_supint_org (organisation_id),
    INDEX idx_supint_sup (supervisor_id),
    INDEX idx_supint_type (interaction_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
