-- Migration: 051_create_bowtie_analysis
-- WF-13: Barrier/Bowtie Analysis
-- Purpose: Visualize hazard pathways, controls, and their effectiveness
-- Methodology: ISO 31010:2019 Bowtie Analysis

-- ==============================================================================
-- 1. BOWTIE DIAGRAMS (Top Event Register)
-- ==============================================================================
-- A bowtie diagram visualizes one major accident hazard (top event) with its
-- threat pathways (left) and consequence pathways (right), plus barriers

CREATE TABLE IF NOT EXISTS bowtie_diagrams (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id     INT NOT NULL,
    
    -- Top Event (center of bowtie)
    top_event_name      VARCHAR(255) NOT NULL COMMENT 'Major accident hazard event',
    top_event_desc      TEXT COMMENT 'Description of what happens if control fails',
    
    -- Classification
    hazard_category_id  INT COMMENT 'Link to hazard_categories',
    site_id             INT COMMENT 'Primary site where this hazard exists',
    process_unit        VARCHAR(255) COMMENT 'Process unit, area, or facility',
    
    -- Risk Rating (inherent - before barriers)
    inherent_severity   INT COMMENT '1-5: Catastrophic to Negligible',
    inherent_likelihood INT COMMENT '1-5: Almost Certain to Rare',
    inherent_risk_score INT COMMENT 'L x S',
    
    -- Current Risk (residual - with barriers in place)
    residual_severity   INT,
    residual_likelihood INT,
    residual_risk_score INT,
    
    -- Target Risk (with all planned barriers)
    target_severity     INT,
    target_likelihood   INT,
    target_risk_score   INT,
    
    -- Metadata
    status              VARCHAR(50) DEFAULT 'active' COMMENT 'active, archived, under_review',
    review_frequency    INT DEFAULT 12 COMMENT 'Months between reviews',
    last_reviewed_at    DATETIME COMMENT 'Last formal review date',
    next_review_due     DATE,
    owner_id            INT COMMENT 'Employee responsible for this bowtie',
    
    created_by          INT,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_org (organisation_id),
    INDEX idx_site (site_id),
    INDEX idx_status (status),
    INDEX idx_review_due (next_review_due),
    
    CONSTRAINT fk_bowtie_org FOREIGN KEY (organisation_id) 
        REFERENCES organisation(id) ON DELETE CASCADE,
    CONSTRAINT fk_bowtie_site FOREIGN KEY (site_id)
        REFERENCES sites(id) ON DELETE SET NULL,
    CONSTRAINT fk_bowtie_category FOREIGN KEY (hazard_category_id)
        REFERENCES hazard_categories(id) ON DELETE SET NULL,
    CONSTRAINT fk_bowtie_owner FOREIGN KEY (owner_id)
        REFERENCES employees(id) ON DELETE SET NULL,
    CONSTRAINT fk_bowtie_creator FOREIGN KEY (created_by)
        REFERENCES users(id) ON DELETE SET NULL
        
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='WF-13: Bowtie diagram register';


-- ==============================================================================
-- 2. THREAT PATHWAYS (Left side of bowtie)
-- ==============================================================================
-- Threats are initiating events that could cause the top event
-- Example: For "Loss of Containment", threats might be "Corrosion", "Overpressure"

CREATE TABLE IF NOT EXISTS bowtie_threats (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    bowtie_id       INT NOT NULL,
    
    threat_name     VARCHAR(255) NOT NULL COMMENT 'What initiates the hazard',
    threat_desc     TEXT,
    threat_type     VARCHAR(100) COMMENT 'Human Error, Equipment Failure, Natural Event, etc.',
    
    -- Threat likelihood before preventive barriers
    base_likelihood INT COMMENT '1-5: How often this threat occurs',
    
    -- Ordering for visual display
    display_order   INT DEFAULT 0,
    
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_bowtie (bowtie_id),
    
    CONSTRAINT fk_threat_bowtie FOREIGN KEY (bowtie_id)
        REFERENCES bowtie_diagrams(id) ON DELETE CASCADE
        
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Threat pathways - left side of bowtie';


-- ==============================================================================
-- 3. CONSEQUENCE PATHWAYS (Right side of bowtie)
-- ==============================================================================
-- Consequences are potential outcomes if the top event occurs
-- Example: For "Loss of Containment", consequences might be "Fire", "Toxic Release"

CREATE TABLE IF NOT EXISTS bowtie_consequences (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    bowtie_id           INT NOT NULL,
    
    consequence_name    VARCHAR(255) NOT NULL COMMENT 'What happens after top event',
    consequence_desc    TEXT,
    consequence_type    VARCHAR(100) COMMENT 'Fatality, Major Injury, Environmental, Asset Loss',
    
    -- Consequence severity if mitigative barriers fail
    max_severity        INT COMMENT '1-5: Worst case severity',
    
    -- Potential impacts
    max_fatalities      INT COMMENT 'Worst case fatality count',
    max_injuries        INT COMMENT 'Worst case injury count',
    financial_impact    DECIMAL(15,2) COMMENT 'Estimated cost in worst case',
    environmental_impact TEXT COMMENT 'Environmental damage description',
    reputational_impact  TEXT COMMENT 'Brand/reputation damage',
    
    -- Ordering for visual display
    display_order       INT DEFAULT 0,
    
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_bowtie (bowtie_id),
    
    CONSTRAINT fk_consequence_bowtie FOREIGN KEY (bowtie_id)
        REFERENCES bowtie_diagrams(id) ON DELETE CASCADE
        
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Consequence pathways - right side of bowtie';


-- ==============================================================================
-- 4. BARRIERS (Controls/Defenses)
-- ==============================================================================
-- Barriers are controls that either:
--   PREVENTIVE: Stop threats from causing the top event (left side)
--   MITIGATIVE: Reduce consequences after top event occurs (right side)

CREATE TABLE IF NOT EXISTS bowtie_barriers (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    bowtie_id           INT NOT NULL,
    
    -- Link to pathway
    threat_id           INT COMMENT 'For preventive barriers',
    consequence_id      INT COMMENT 'For mitigative barriers',
    barrier_side        VARCHAR(20) NOT NULL COMMENT 'preventive or mitigative',
    
    -- Barrier details
    barrier_name        VARCHAR(255) NOT NULL,
    barrier_desc        TEXT,
    barrier_type        VARCHAR(100) COMMENT 'Engineering, Administrative, PPE, etc.',
    
    -- Barrier classification per ISO 31010
    control_type        VARCHAR(50) COMMENT 'Hardware, Human Action, Management System',
    independence_level  INT COMMENT '1-3: Independent, Dependent, Shared',
    
    -- Effectiveness
    design_effectiveness    INT COMMENT '1-5: How effective when working perfectly',
    actual_effectiveness    INT COMMENT '1-5: Current real-world effectiveness',
    risk_reduction_factor   DECIMAL(5,2) COMMENT 'Multiplier (e.g., 0.1 = 90% reduction)',
    
    -- Verification Requirements
    verification_method     VARCHAR(100) COMMENT 'Inspection, Testing, Audit, etc.',
    verification_frequency  INT COMMENT 'Days between verifications',
    last_verified_at        DATETIME,
    next_verification_due   DATE,
    
    -- Performance Standards
    performance_standard    TEXT COMMENT 'What "working" looks like',
    failure_criteria        TEXT COMMENT 'What defines barrier degradation/failure',
    
    -- Status
    status                  VARCHAR(50) DEFAULT 'operational' COMMENT 'operational, degraded, failed, planned',
    degradation_reason      TEXT COMMENT 'Why barrier is degraded/failed',
    degraded_since          DATETIME,
    
    -- Ownership
    owner_id                INT COMMENT 'Person responsible for this barrier',
    
    -- Ordering
    display_order           INT DEFAULT 0,
    
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_bowtie (bowtie_id),
    INDEX idx_threat (threat_id),
    INDEX idx_consequence (consequence_id),
    INDEX idx_status (status),
    INDEX idx_verification_due (next_verification_due),
    
    CONSTRAINT fk_barrier_bowtie FOREIGN KEY (bowtie_id)
        REFERENCES bowtie_diagrams(id) ON DELETE CASCADE,
    CONSTRAINT fk_barrier_threat FOREIGN KEY (threat_id)
        REFERENCES bowtie_threats(id) ON DELETE CASCADE,
    CONSTRAINT fk_barrier_consequence FOREIGN KEY (consequence_id)
        REFERENCES bowtie_consequences(id) ON DELETE CASCADE,
    CONSTRAINT fk_barrier_owner FOREIGN KEY (owner_id)
        REFERENCES employees(id) ON DELETE SET NULL
        
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Barriers/Controls in bowtie diagram';


-- ==============================================================================
-- 5. BARRIER VERIFICATION HISTORY
-- ==============================================================================
-- Track every verification/inspection of a barrier to prove its effectiveness

CREATE TABLE IF NOT EXISTS bowtie_barrier_verifications (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    barrier_id              INT NOT NULL,
    organisation_id         INT NOT NULL,
    
    -- Verification details
    verification_date       DATE NOT NULL,
    verification_type       VARCHAR(100) COMMENT 'Inspection, Test, Audit, Drill, Review',
    verified_by             INT COMMENT 'Employee who performed verification',
    
    -- Result
    result                  VARCHAR(50) NOT NULL COMMENT 'pass, fail, degraded, not_tested',
    effectiveness_rating    INT COMMENT '1-5: How effective is this barrier right now',
    
    -- Findings
    findings                TEXT COMMENT 'What was observed',
    deficiencies_found      TEXT COMMENT 'Issues that reduce effectiveness',
    
    -- Actions
    corrective_actions      TEXT COMMENT 'What will be done to restore effectiveness',
    action_owner            INT COMMENT 'Who is fixing deficiencies',
    action_due_date         DATE,
    action_completed        BOOLEAN DEFAULT FALSE,
    
    -- Evidence
    evidence_photos         JSON COMMENT 'Array of file paths/URLs',
    evidence_docs           JSON COMMENT 'Array of document paths',
    
    -- Next verification
    next_verification_due   DATE COMMENT 'When this barrier needs checking again',
    
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_barrier (barrier_id),
    INDEX idx_org (organisation_id),
    INDEX idx_date (verification_date),
    INDEX idx_result (result),
    
    CONSTRAINT fk_verification_barrier FOREIGN KEY (barrier_id)
        REFERENCES bowtie_barriers(id) ON DELETE CASCADE,
    CONSTRAINT fk_verification_org FOREIGN KEY (organisation_id)
        REFERENCES organisation(id) ON DELETE CASCADE,
    CONSTRAINT fk_verification_verifier FOREIGN KEY (verified_by)
        REFERENCES employees(id) ON DELETE SET NULL,
    CONSTRAINT fk_verification_action_owner FOREIGN KEY (action_owner)
        REFERENCES employees(id) ON DELETE SET NULL
        
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Barrier verification/assurance records';


-- ==============================================================================
-- 6. BOWTIE-TO-INCIDENT LINKAGE
-- ==============================================================================
-- When a real incident occurs, link it to the bowtie to show which barriers failed

CREATE TABLE IF NOT EXISTS bowtie_incident_links (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    bowtie_id           INT NOT NULL,
    incident_id         INT COMMENT 'Link to incidents table',
    near_miss_id        INT COMMENT 'Link to near_misses table',
    
    -- What failed
    failed_barriers     JSON COMMENT 'Array of barrier_ids that failed/were bypassed',
    degraded_barriers   JSON COMMENT 'Array of barrier_ids that were degraded',
    threat_realized     INT COMMENT 'Which threat_id actually occurred',
    consequence_occurred INT COMMENT 'Which consequence_id actually happened',
    
    -- Analysis
    root_cause          TEXT COMMENT 'Why barriers failed',
    lessons_learned     TEXT,
    
    -- Actions taken
    barriers_strengthened TEXT COMMENT 'How barriers were improved post-incident',
    
    linked_by           INT,
    linked_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_bowtie (bowtie_id),
    INDEX idx_incident (incident_id),
    INDEX idx_near_miss (near_miss_id),
    
    CONSTRAINT fk_link_bowtie FOREIGN KEY (bowtie_id)
        REFERENCES bowtie_diagrams(id) ON DELETE CASCADE,
    CONSTRAINT fk_link_incident FOREIGN KEY (incident_id)
        REFERENCES incidents(id) ON DELETE CASCADE,
    CONSTRAINT fk_link_near_miss FOREIGN KEY (near_miss_id)
        REFERENCES near_misses(id) ON DELETE CASCADE,
    CONSTRAINT fk_link_user FOREIGN KEY (linked_by)
        REFERENCES users(id) ON DELETE SET NULL
        
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Link incidents to bowtie diagrams';


-- ==============================================================================
-- 7. BOWTIE REVIEW HISTORY
-- ==============================================================================
-- Track formal reviews of the bowtie (annual, after incidents, etc.)

CREATE TABLE IF NOT EXISTS bowtie_reviews (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    bowtie_id           INT NOT NULL,
    organisation_id     INT NOT NULL,
    
    review_date         DATE NOT NULL,
    review_type         VARCHAR(100) COMMENT 'Annual, Post-Incident, Regulatory, MOC-Triggered',
    reviewed_by         INT COMMENT 'Lead reviewer employee_id',
    review_team         JSON COMMENT 'Array of employee_ids who participated',
    
    -- Review findings
    bowtie_adequate     BOOLEAN COMMENT 'Is current bowtie still accurate?',
    barriers_effective  BOOLEAN COMMENT 'Are barriers still effective?',
    gaps_identified     TEXT COMMENT 'Missing barriers or pathways',
    recommendations     TEXT COMMENT 'Suggested improvements',
    
    -- Changes made
    threats_added       INT DEFAULT 0,
    threats_removed     INT DEFAULT 0,
    consequences_added  INT DEFAULT 0,
    consequences_removed INT DEFAULT 0,
    barriers_added      INT DEFAULT 0,
    barriers_removed    INT DEFAULT 0,
    
    -- Risk re-assessment
    risk_changed        BOOLEAN DEFAULT FALSE,
    old_risk_score      INT,
    new_risk_score      INT,
    
    -- Next review
    next_review_due     DATE,
    
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_bowtie (bowtie_id),
    INDEX idx_org (organisation_id),
    INDEX idx_date (review_date),
    
    CONSTRAINT fk_review_bowtie FOREIGN KEY (bowtie_id)
        REFERENCES bowtie_diagrams(id) ON DELETE CASCADE,
    CONSTRAINT fk_review_org FOREIGN KEY (organisation_id)
        REFERENCES organisation(id) ON DELETE CASCADE,
    CONSTRAINT fk_review_reviewer FOREIGN KEY (reviewed_by)
        REFERENCES employees(id) ON DELETE SET NULL
        
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Bowtie review history';


-- ==============================================================================
-- 8. BARRIER DEGRADATION ALERTS
-- ==============================================================================
-- Automated alerts when barriers fail verification or become overdue

CREATE TABLE IF NOT EXISTS bowtie_barrier_alerts (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    barrier_id          INT NOT NULL,
    bowtie_id           INT NOT NULL,
    organisation_id     INT NOT NULL,
    
    alert_type          VARCHAR(100) NOT NULL COMMENT 'verification_overdue, failed_test, degraded, not_independent',
    severity            VARCHAR(50) COMMENT 'critical, high, medium, low',
    
    alert_message       TEXT,
    triggered_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Who needs to act
    assigned_to         INT COMMENT 'Barrier owner',
    
    -- Resolution
    resolved            BOOLEAN DEFAULT FALSE,
    resolved_at         DATETIME,
    resolved_by         INT,
    resolution_notes    TEXT,
    
    INDEX idx_barrier (barrier_id),
    INDEX idx_bowtie (bowtie_id),
    INDEX idx_org (organisation_id),
    INDEX idx_resolved (resolved),
    INDEX idx_severity (severity),
    
    CONSTRAINT fk_alert_barrier FOREIGN KEY (barrier_id)
        REFERENCES bowtie_barriers(id) ON DELETE CASCADE,
    CONSTRAINT fk_alert_bowtie FOREIGN KEY (bowtie_id)
        REFERENCES bowtie_diagrams(id) ON DELETE CASCADE,
    CONSTRAINT fk_alert_org FOREIGN KEY (organisation_id)
        REFERENCES organisation(id) ON DELETE CASCADE,
    CONSTRAINT fk_alert_assigned FOREIGN KEY (assigned_to)
        REFERENCES employees(id) ON DELETE SET NULL,
    CONSTRAINT fk_alert_resolver FOREIGN KEY (resolved_by)
        REFERENCES employees(id) ON DELETE SET NULL
        
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Barrier degradation and overdue alerts';
