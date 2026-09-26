-- Migration: 052_create_psm
-- WF-14: Process Safety Management (PSM)
-- Purpose: Systematic framework for managing process hazards
-- Source: OSHA PSM 1910.119, API RP 750, CCPS Guidelines

-- ==============================================================================
-- 1. PSM PROGRAM ELEMENTS
-- ==============================================================================
-- PSM consists of 14 elements (OSHA) or 20 elements (CCPS)
-- This tracks implementation status and compliance for each element

CREATE TABLE IF NOT EXISTS psm_elements (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id         INT NOT NULL,
    site_id                 INT COMMENT 'Site where this element applies',
    
    -- Element identification
    element_name            VARCHAR(255) NOT NULL COMMENT 'e.g., Process Safety Information, PHA, MOC',
    element_code            VARCHAR(50) COMMENT 'e.g., PSM-01, PSM-02',
    element_category        VARCHAR(100) COMMENT 'Technical, Organizational, Human Factors',
    regulatory_requirement  TEXT COMMENT 'Specific regulation requiring this',
    
    -- Implementation status
    status                  VARCHAR(50) DEFAULT 'not_started' COMMENT 'not_started, in_progress, implemented, non_compliant',
    implementation_date     DATE COMMENT 'When element was implemented',
    compliance_level        INT COMMENT '1-5: Non-compliant to Fully Compliant',
    
    -- Documentation
    procedures_documented   BOOLEAN DEFAULT FALSE,
    training_completed      BOOLEAN DEFAULT FALSE,
    audits_conducted        BOOLEAN DEFAULT FALSE,
    
    -- Compliance tracking
    last_audit_date         DATE,
    next_audit_due          DATE,
    audit_findings_count    INT DEFAULT 0,
    open_actions            INT DEFAULT 0,
    
    -- Ownership
    element_owner_id        INT COMMENT 'Employee responsible',
    
    created_by              INT,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_org (organisation_id),
    INDEX idx_site (site_id),
    INDEX idx_status (status),
    INDEX idx_audit_due (next_audit_due),
    
    CONSTRAINT fk_psm_element_org FOREIGN KEY (organisation_id)
        REFERENCES organisation(id) ON DELETE CASCADE,
    CONSTRAINT fk_psm_element_site FOREIGN KEY (site_id)
        REFERENCES sites(id) ON DELETE SET NULL,
    CONSTRAINT fk_psm_element_owner FOREIGN KEY (element_owner_id)
        REFERENCES employees(id) ON DELETE SET NULL,
    CONSTRAINT fk_psm_element_creator FOREIGN KEY (created_by)
        REFERENCES users(id) ON DELETE SET NULL
        
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='PSM program element register';



-- ==============================================================================
-- 2. PROCESS HAZARD ANALYSIS (PHA) REGISTER
-- ==============================================================================
-- Core PSM element: systematic hazard identification and analysis
-- Methods: HAZOP, LOPA, What-If, Bow-Tie, FMEA, etc.

CREATE TABLE IF NOT EXISTS psm_pha_studies (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id         INT NOT NULL,
    site_id                 INT NOT NULL,
    
    -- Study identification
    study_name              VARCHAR(255) NOT NULL,
    study_number            VARCHAR(100) UNIQUE,
    process_unit            VARCHAR(255) COMMENT 'Equipment/process being analyzed',
    process_description     TEXT,
    
    -- PHA methodology
    pha_method              VARCHAR(100) NOT NULL COMMENT 'HAZOP, LOPA, What-If, Checklist, FMEA, etc.',
    study_scope             TEXT COMMENT 'What is included/excluded',
    
    -- Regulatory requirements
    regulatory_trigger      VARCHAR(255) COMMENT 'Why PHA is required',
    revalidation_required   BOOLEAN DEFAULT TRUE,
    revalidation_years      INT DEFAULT 5 COMMENT 'Years between revalidations',
    
    -- Study status
    status                  VARCHAR(50) DEFAULT 'planned' COMMENT 'planned, in_progress, completed, overdue, revalidation_due',
    
    -- Schedule
    planned_start_date      DATE,
    actual_start_date       DATE,
    planned_completion_date DATE,
    actual_completion_date  DATE,
    last_revalidation_date  DATE,
    next_revalidation_due   DATE,
    
    -- Team
    team_leader_id          INT,
    facilitator_id          INT,
    team_members            JSON COMMENT 'Array of employee_ids',
    
    -- Results summary
    scenarios_analyzed      INT DEFAULT 0,
    recommendations_total   INT DEFAULT 0,
    recommendations_open    INT DEFAULT 0,
    high_risk_scenarios     INT DEFAULT 0,
    
    -- Documentation
    report_file_path        VARCHAR(500),
    approval_status         VARCHAR(50) DEFAULT 'draft' COMMENT 'draft, under_review, approved',
    approved_by             INT,
    approved_at             DATETIME,
    
    created_by              INT,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_org (organisation_id),
    INDEX idx_site (site_id),
    INDEX idx_status (status),
    INDEX idx_revalidation_due (next_revalidation_due),
    INDEX idx_study_number (study_number),
    
    CONSTRAINT fk_pha_org FOREIGN KEY (organisation_id)
        REFERENCES organisation(id) ON DELETE CASCADE,
    CONSTRAINT fk_pha_site FOREIGN KEY (site_id)
        REFERENCES sites(id) ON DELETE CASCADE,
    CONSTRAINT fk_pha_leader FOREIGN KEY (team_leader_id)
        REFERENCES employees(id) ON DELETE SET NULL,
    CONSTRAINT fk_pha_facilitator FOREIGN KEY (facilitator_id)
        REFERENCES employees(id) ON DELETE SET NULL,
    CONSTRAINT fk_pha_creator FOREIGN KEY (created_by)
        REFERENCES users(id) ON DELETE SET NULL
        
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Process Hazard Analysis register';



-- ==============================================================================
-- 3. PHA SCENARIOS & RECOMMENDATIONS
-- ==============================================================================
-- Individual hazard scenarios identified during PHA

CREATE TABLE IF NOT EXISTS psm_pha_scenarios (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    pha_study_id            INT NOT NULL,
    
    -- Scenario details
    node_number             VARCHAR(50) COMMENT 'HAZOP node or section',
    scenario_number         VARCHAR(50),
    deviation               VARCHAR(255) COMMENT 'HAZOP: More, Less, No, As Well As, etc.',
    cause                   TEXT COMMENT 'What initiates the hazard',
    consequence             TEXT COMMENT 'Potential outcome',
    
    -- Risk assessment
    likelihood_before       INT COMMENT '1-5: before safeguards',
    severity_before         INT COMMENT '1-5: before safeguards',
    risk_score_before       INT,
    
    -- Existing safeguards
    safeguards              TEXT COMMENT 'Current controls',
    safeguards_adequate     BOOLEAN,
    
    likelihood_after        INT COMMENT '1-5: with safeguards',
    severity_after          INT COMMENT '1-5: with safeguards',
    risk_score_after        INT,
    
    -- Risk tolerance
    risk_acceptable         BOOLEAN DEFAULT FALSE,
    requires_action         BOOLEAN DEFAULT TRUE,
    
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_pha_study (pha_study_id),
    INDEX idx_risk_after (risk_score_after),
    
    CONSTRAINT fk_scenario_pha FOREIGN KEY (pha_study_id)
        REFERENCES psm_pha_studies(id) ON DELETE CASCADE
        
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='PHA hazard scenarios';


CREATE TABLE IF NOT EXISTS psm_pha_recommendations (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    pha_study_id            INT NOT NULL,
    scenario_id             INT COMMENT 'Link to specific scenario',
    
    -- Recommendation details
    recommendation_number   VARCHAR(50),
    recommendation_text     TEXT NOT NULL,
    recommendation_type     VARCHAR(100) COMMENT 'Engineering, Administrative, PPE, etc.',
    priority                VARCHAR(50) COMMENT 'Critical, High, Medium, Low',
    
    -- Assignment
    assigned_to             INT,
    due_date                DATE,
    
    -- Status
    status                  VARCHAR(50) DEFAULT 'open' COMMENT 'open, in_progress, completed, closed, deferred',
    completion_date         DATE,
    completion_notes        TEXT,
    verified_by             INT,
    verified_at             DATETIME,
    
    -- Cost tracking
    estimated_cost          DECIMAL(15,2),
    actual_cost             DECIMAL(15,2),
    
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_pha_study (pha_study_id),
    INDEX idx_scenario (scenario_id),
    INDEX idx_status (status),
    INDEX idx_due_date (due_date),
    INDEX idx_assigned (assigned_to),
    
    CONSTRAINT fk_recommendation_pha FOREIGN KEY (pha_study_id)
        REFERENCES psm_pha_studies(id) ON DELETE CASCADE,
    CONSTRAINT fk_recommendation_scenario FOREIGN KEY (scenario_id)
        REFERENCES psm_pha_scenarios(id) ON DELETE CASCADE,
    CONSTRAINT fk_recommendation_assignee FOREIGN KEY (assigned_to)
        REFERENCES employees(id) ON DELETE SET NULL,
    CONSTRAINT fk_recommendation_verifier FOREIGN KEY (verified_by)
        REFERENCES employees(id) ON DELETE SET NULL
        
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='PHA recommendations tracking';



-- ==============================================================================
-- 4. MECHANICAL INTEGRITY PROGRAM
-- ==============================================================================
-- Equipment inspection, testing, and maintenance to prevent failures

CREATE TABLE IF NOT EXISTS psm_critical_equipment (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id         INT NOT NULL,
    site_id                 INT NOT NULL,
    
    -- Equipment identification
    equipment_tag           VARCHAR(100) UNIQUE NOT NULL,
    equipment_name          VARCHAR(255) NOT NULL,
    equipment_type          VARCHAR(100) COMMENT 'Pressure Vessel, Relief Valve, Pump, etc.',
    process_unit            VARCHAR(255),
    
    -- Classification
    is_safety_critical      BOOLEAN DEFAULT FALSE,
    criticality_level       VARCHAR(50) COMMENT 'Critical, Essential, Important, Standard',
    failure_consequence     TEXT COMMENT 'What happens if this fails',
    
    -- Design information
    design_pressure         VARCHAR(100),
    design_temperature      VARCHAR(100),
    material_of_construction VARCHAR(255),
    manufacture_date        DATE,
    installation_date       DATE,
    design_life_years       INT,
    
    -- Inspection requirements
    inspection_strategy     VARCHAR(100) COMMENT 'RBI, Fixed Interval, Condition-Based',
    inspection_frequency    INT COMMENT 'Days between inspections',
    last_inspection_date    DATE,
    next_inspection_due     DATE,
    inspection_method       VARCHAR(255) COMMENT 'Visual, UT, RT, PT, etc.',
    
    -- Testing requirements
    testing_frequency       INT COMMENT 'Days between tests',
    last_test_date          DATE,
    next_test_due           DATE,
    
    -- Status
    equipment_status        VARCHAR(50) DEFAULT 'in_service' COMMENT 'in_service, out_of_service, decommissioned',
    condition_rating        INT COMMENT '1-5: Poor to Excellent',
    deficiencies_open       INT DEFAULT 0,
    
    -- Owner
    owner_id                INT,
    
    created_by              INT,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_org (organisation_id),
    INDEX idx_site (site_id),
    INDEX idx_tag (equipment_tag),
    INDEX idx_inspection_due (next_inspection_due),
    INDEX idx_test_due (next_test_due),
    INDEX idx_critical (is_safety_critical),
    
    CONSTRAINT fk_equipment_org FOREIGN KEY (organisation_id)
        REFERENCES organisation(id) ON DELETE CASCADE,
    CONSTRAINT fk_equipment_site FOREIGN KEY (site_id)
        REFERENCES sites(id) ON DELETE CASCADE,
    CONSTRAINT fk_equipment_owner FOREIGN KEY (owner_id)
        REFERENCES employees(id) ON DELETE SET NULL,
    CONSTRAINT fk_equipment_creator FOREIGN KEY (created_by)
        REFERENCES users(id) ON DELETE SET NULL
        
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Critical equipment register for MI program';


CREATE TABLE IF NOT EXISTS psm_equipment_inspections (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    equipment_id            INT NOT NULL,
    organisation_id         INT NOT NULL,
    
    -- Inspection details
    inspection_date         DATE NOT NULL,
    inspection_type         VARCHAR(100) COMMENT 'Routine, Emergency, Regulatory',
    inspection_method       VARCHAR(255),
    inspector_id            INT,
    inspector_cert_number   VARCHAR(100) COMMENT 'Certification of inspector',
    
    -- Results
    result                  VARCHAR(50) NOT NULL COMMENT 'pass, fail, conditional, deferred',
    condition_rating        INT COMMENT '1-5: Equipment condition after inspection',
    findings                TEXT,
    deficiencies_found      TEXT,
    
    -- Corrective actions
    requires_repair         BOOLEAN DEFAULT FALSE,
    requires_replacement    BOOLEAN DEFAULT FALSE,
    action_required_by      DATE,
    action_completed        BOOLEAN DEFAULT FALSE,
    action_completion_date  DATE,
    
    -- Next inspection
    next_inspection_due     DATE,
    
    -- Documentation
    report_file_path        VARCHAR(500),
    photos                  JSON COMMENT 'Array of photo file paths',
    
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_equipment (equipment_id),
    INDEX idx_org (organisation_id),
    INDEX idx_date (inspection_date),
    INDEX idx_result (result),
    
    CONSTRAINT fk_inspection_equipment FOREIGN KEY (equipment_id)
        REFERENCES psm_critical_equipment(id) ON DELETE CASCADE,
    CONSTRAINT fk_inspection_org FOREIGN KEY (organisation_id)
        REFERENCES organisation(id) ON DELETE CASCADE,
    CONSTRAINT fk_inspection_inspector FOREIGN KEY (inspector_id)
        REFERENCES employees(id) ON DELETE SET NULL
        
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Equipment inspection records';



-- ==============================================================================
-- 5. PSM OPERATING PROCEDURES
-- ==============================================================================
-- Written procedures for safe operation

CREATE TABLE IF NOT EXISTS psm_operating_procedures (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id         INT NOT NULL,
    site_id                 INT,
    
    -- Procedure identification
    procedure_number        VARCHAR(100) UNIQUE,
    procedure_title         VARCHAR(255) NOT NULL,
    procedure_type          VARCHAR(100) COMMENT 'Normal Ops, Startup, Shutdown, Emergency, Maintenance',
    process_unit            VARCHAR(255),
    
    -- Content
    procedure_description   TEXT,
    operating_limits        TEXT COMMENT 'Critical process parameters',
    safety_considerations   TEXT,
    equipment_required      TEXT,
    
    -- Version control
    version                 VARCHAR(50) DEFAULT '1.0',
    revision_number         INT DEFAULT 1,
    revision_reason         TEXT,
    
    -- Status
    status                  VARCHAR(50) DEFAULT 'draft' COMMENT 'draft, under_review, approved, obsolete',
    effective_date          DATE,
    review_frequency        INT DEFAULT 24 COMMENT 'Months between reviews',
    last_review_date        DATE,
    next_review_due         DATE,
    
    -- Ownership & approval
    author_id               INT,
    reviewer_id             INT,
    approver_id             INT,
    approved_at             DATETIME,
    
    -- Documentation
    document_file_path      VARCHAR(500),
    
    created_by              INT,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_org (organisation_id),
    INDEX idx_site (site_id),
    INDEX idx_procedure_number (procedure_number),
    INDEX idx_status (status),
    INDEX idx_review_due (next_review_due),
    
    CONSTRAINT fk_procedure_org FOREIGN KEY (organisation_id)
        REFERENCES organisation(id) ON DELETE CASCADE,
    CONSTRAINT fk_procedure_site FOREIGN KEY (site_id)
        REFERENCES sites(id) ON DELETE SET NULL,
    CONSTRAINT fk_procedure_author FOREIGN KEY (author_id)
        REFERENCES employees(id) ON DELETE SET NULL,
    CONSTRAINT fk_procedure_approver FOREIGN KEY (approver_id)
        REFERENCES employees(id) ON DELETE SET NULL,
    CONSTRAINT fk_procedure_creator FOREIGN KEY (created_by)
        REFERENCES users(id) ON DELETE SET NULL
        
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='PSM operating procedures register';


-- ==============================================================================
-- 6. PSM COMPLIANCE AUDITS
-- ==============================================================================
-- Periodic audits of PSM program effectiveness

CREATE TABLE IF NOT EXISTS psm_audits (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id         INT NOT NULL,
    site_id                 INT,
    
    -- Audit identification
    audit_number            VARCHAR(100) UNIQUE,
    audit_name              VARCHAR(255) NOT NULL,
    audit_type              VARCHAR(100) COMMENT 'Internal, External, Regulatory, Self-Assessment',
    audit_scope             TEXT COMMENT 'Which PSM elements are audited',
    
    -- Schedule
    planned_start_date      DATE,
    actual_start_date       DATE,
    planned_completion_date DATE,
    actual_completion_date  DATE,
    
    -- Team
    lead_auditor_id         INT,
    audit_team              JSON COMMENT 'Array of employee_ids',
    
    -- Results
    status                  VARCHAR(50) DEFAULT 'planned' COMMENT 'planned, in_progress, completed',
    elements_audited        INT COMMENT 'Number of PSM elements covered',
    findings_total          INT DEFAULT 0,
    findings_critical       INT DEFAULT 0,
    findings_major          INT DEFAULT 0,
    findings_minor          INT DEFAULT 0,
    observations            INT DEFAULT 0,
    
    -- Compliance rating
    overall_compliance      INT COMMENT '1-5: Non-compliant to Fully Compliant',
    compliance_percentage   DECIMAL(5,2),
    
    -- Documentation
    report_file_path        VARCHAR(500),
    
    created_by              INT,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_org (organisation_id),
    INDEX idx_site (site_id),
    INDEX idx_audit_number (audit_number),
    INDEX idx_status (status),
    
    CONSTRAINT fk_psm_audit_org FOREIGN KEY (organisation_id)
        REFERENCES organisation(id) ON DELETE CASCADE,
    CONSTRAINT fk_psm_audit_site FOREIGN KEY (site_id)
        REFERENCES sites(id) ON DELETE SET NULL,
    CONSTRAINT fk_psm_audit_leader FOREIGN KEY (lead_auditor_id)
        REFERENCES employees(id) ON DELETE SET NULL,
    CONSTRAINT fk_psm_audit_creator FOREIGN KEY (created_by)
        REFERENCES users(id) ON DELETE SET NULL
        
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='PSM compliance audit register';


CREATE TABLE IF NOT EXISTS psm_audit_findings (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    audit_id                INT NOT NULL,
    psm_element_id          INT COMMENT 'Which PSM element has the finding',
    
    -- Finding details
    finding_number          VARCHAR(50),
    finding_type            VARCHAR(50) COMMENT 'Critical, Major, Minor, Observation',
    finding_description     TEXT NOT NULL,
    requirement_reference   VARCHAR(255) COMMENT 'Regulation or standard violated',
    
    -- Evidence
    evidence                TEXT,
    root_cause              TEXT,
    
    -- Corrective action
    corrective_action       TEXT,
    assigned_to             INT,
    due_date                DATE,
    
    -- Status
    status                  VARCHAR(50) DEFAULT 'open' COMMENT 'open, in_progress, completed, verified, closed',
    completion_date         DATE,
    verified_by             INT,
    verified_at             DATETIME,
    
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_audit (audit_id),
    INDEX idx_element (psm_element_id),
    INDEX idx_type (finding_type),
    INDEX idx_status (status),
    INDEX idx_assigned (assigned_to),
    
    CONSTRAINT fk_finding_audit FOREIGN KEY (audit_id)
        REFERENCES psm_audits(id) ON DELETE CASCADE,
    CONSTRAINT fk_finding_element FOREIGN KEY (psm_element_id)
        REFERENCES psm_elements(id) ON DELETE SET NULL,
    CONSTRAINT fk_finding_assignee FOREIGN KEY (assigned_to)
        REFERENCES employees(id) ON DELETE SET NULL,
    CONSTRAINT fk_finding_verifier FOREIGN KEY (verified_by)
        REFERENCES employees(id) ON DELETE SET NULL
        
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='PSM audit findings and corrective actions';
