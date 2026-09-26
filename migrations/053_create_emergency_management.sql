-- Migration: 053_create_emergency_management
-- WF-15: Emergency Management
-- Purpose: Emergency preparedness, response planning, drills, and incident command
-- Source: NFPA 1600, ICS/NIMS, ISO 22320, OSHA Emergency Action Plans

-- ==============================================================================
-- 1. EMERGENCY PLANS
-- ==============================================================================
-- Master emergency response plans for different scenarios

CREATE TABLE IF NOT EXISTS emergency_plans (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id         INT NOT NULL,
    site_id                 INT NOT NULL,
    
    -- Plan identification
    plan_name               VARCHAR(255) NOT NULL,
    plan_number             VARCHAR(100) UNIQUE,
    emergency_type          VARCHAR(100) NOT NULL COMMENT 'Fire, Chemical Spill, Medical Emergency, Natural Disaster, etc.',
    scenario_description    TEXT COMMENT 'What triggers this plan',
    
    -- Scope & applicability
    applicable_sites        JSON COMMENT 'Array of site_ids where this plan applies',
    applicable_areas        TEXT COMMENT 'Specific buildings/zones covered',
    affected_population     INT COMMENT 'Max number of people affected',
    
    -- Response objectives
    response_objectives     TEXT COMMENT 'What the response aims to achieve',
    critical_actions        TEXT COMMENT 'Immediate actions required',
    
    -- Activation criteria
    activation_triggers     TEXT COMMENT 'When to activate this plan',
    activation_authority    VARCHAR(255) COMMENT 'Who can activate',
    
    -- Status
    status                  VARCHAR(50) DEFAULT 'draft' COMMENT 'draft, under_review, approved, active, obsolete',
    version                 VARCHAR(50) DEFAULT '1.0',
    
    -- Review cycle
    review_frequency        INT DEFAULT 12 COMMENT 'Months between reviews',
    last_review_date        DATE,
    next_review_due         DATE,
    last_drill_date         DATE COMMENT 'When this plan was last exercised',
    
    -- Ownership & approval
    plan_owner_id           INT,
    approved_by             INT,
    approved_at             DATETIME,
    effective_date          DATE,
    
    -- Documentation
    document_file_path      VARCHAR(500),
    
    created_by              INT,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_org (organisation_id),
    INDEX idx_site (site_id),
    INDEX idx_plan_number (plan_number),
    INDEX idx_type (emergency_type),
    INDEX idx_status (status),
    INDEX idx_review_due (next_review_due),
    
    CONSTRAINT fk_eplan_org FOREIGN KEY (organisation_id)
        REFERENCES organisation(id) ON DELETE CASCADE,
    CONSTRAINT fk_eplan_site FOREIGN KEY (site_id)
        REFERENCES sites(id) ON DELETE CASCADE,
    CONSTRAINT fk_eplan_owner FOREIGN KEY (plan_owner_id)
        REFERENCES employees(id) ON DELETE SET NULL,
    CONSTRAINT fk_eplan_approver FOREIGN KEY (approved_by)
        REFERENCES employees(id) ON DELETE SET NULL,
    CONSTRAINT fk_eplan_creator FOREIGN KEY (created_by)
        REFERENCES users(id) ON DELETE SET NULL
        
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Emergency response plans register';



-- ==============================================================================
-- 2. EMERGENCY RESPONSE TEAMS
-- ==============================================================================
-- Emergency response organization structure (ICS-based)

CREATE TABLE IF NOT EXISTS emergency_response_teams (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id         INT NOT NULL,
    site_id                 INT,
    
    -- Team identification
    team_name               VARCHAR(255) NOT NULL,
    team_type               VARCHAR(100) COMMENT 'Fire Brigade, First Aid, Evacuation, HAZMAT, etc.',
    team_function           TEXT COMMENT 'What this team does',
    
    -- ICS roles
    incident_commander_id   INT COMMENT 'Primary IC',
    deputy_commander_id     INT COMMENT 'Backup IC',
    team_members            JSON COMMENT 'Array of employee_ids',
    
    -- Activation
    activation_level        VARCHAR(50) COMMENT 'Level 1, 2, 3 emergency',
    call_out_procedure      TEXT COMMENT 'How to mobilize this team',
    
    -- Training requirements
    required_training       TEXT,
    required_certifications TEXT,
    training_current        BOOLEAN DEFAULT FALSE,
    
    -- Equipment
    assigned_equipment      TEXT COMMENT 'PPE, tools, vehicles assigned',
    equipment_location      VARCHAR(255),
    
    -- Status
    status                  VARCHAR(50) DEFAULT 'active' COMMENT 'active, standby, inactive',
    last_activation_date    DATETIME,
    last_drill_date         DATE,
    
    created_by              INT,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_org (organisation_id),
    INDEX idx_site (site_id),
    INDEX idx_type (team_type),
    INDEX idx_status (status),
    
    CONSTRAINT fk_eteam_org FOREIGN KEY (organisation_id)
        REFERENCES organisation(id) ON DELETE CASCADE,
    CONSTRAINT fk_eteam_site FOREIGN KEY (site_id)
        REFERENCES sites(id) ON DELETE SET NULL,
    CONSTRAINT fk_eteam_ic FOREIGN KEY (incident_commander_id)
        REFERENCES employees(id) ON DELETE SET NULL,
    CONSTRAINT fk_eteam_deputy FOREIGN KEY (deputy_commander_id)
        REFERENCES employees(id) ON DELETE SET NULL,
    CONSTRAINT fk_eteam_creator FOREIGN KEY (created_by)
        REFERENCES users(id) ON DELETE SET NULL
        
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Emergency response team register';


-- ==============================================================================
-- 3. EMERGENCY CONTACTS
-- ==============================================================================
-- Emergency notification list (internal & external)

CREATE TABLE IF NOT EXISTS emergency_contacts (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id         INT NOT NULL,
    site_id                 INT,
    
    -- Contact details
    contact_name            VARCHAR(255) NOT NULL,
    contact_type            VARCHAR(100) NOT NULL COMMENT 'Internal, Fire Department, Police, Hospital, etc.',
    organisation_name       VARCHAR(255) COMMENT 'External agency name',
    
    -- Contact info
    primary_phone           VARCHAR(50) NOT NULL,
    alternate_phone         VARCHAR(50),
    email                   VARCHAR(255),
    address                 TEXT,
    
    -- When to contact
    contact_priority        INT DEFAULT 1 COMMENT '1=Primary, 2=Secondary, 3=Tertiary',
    emergency_types         JSON COMMENT 'Array of emergency types to contact for',
    response_time_minutes   INT COMMENT 'Expected arrival time',
    
    -- Availability
    available_24_7          BOOLEAN DEFAULT TRUE,
    available_hours         VARCHAR(255) COMMENT 'Business hours if not 24/7',
    
    -- Verification
    last_verified_date      DATE COMMENT 'When contact details were last checked',
    next_verification_due   DATE,
    
    -- Status
    status                  VARCHAR(50) DEFAULT 'active' COMMENT 'active, inactive',
    
    created_by              INT,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_org (organisation_id),
    INDEX idx_site (site_id),
    INDEX idx_type (contact_type),
    INDEX idx_priority (contact_priority),
    INDEX idx_status (status),
    
    CONSTRAINT fk_econtact_org FOREIGN KEY (organisation_id)
        REFERENCES organisation(id) ON DELETE CASCADE,
    CONSTRAINT fk_econtact_site FOREIGN KEY (site_id)
        REFERENCES sites(id) ON DELETE SET NULL,
    CONSTRAINT fk_econtact_creator FOREIGN KEY (created_by)
        REFERENCES users(id) ON DELETE SET NULL
        
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Emergency contact list';


-- ==============================================================================
-- 4. EVACUATION PROCEDURES
-- ==============================================================================
-- Evacuation routes, assembly points, procedures

CREATE TABLE IF NOT EXISTS evacuation_procedures (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id         INT NOT NULL,
    site_id                 INT NOT NULL,
    
    -- Identification
    procedure_name          VARCHAR(255) NOT NULL,
    building_area           VARCHAR(255) COMMENT 'Which building/area',
    floor_level             VARCHAR(100),
    
    -- Routes & assembly points
    primary_route           TEXT COMMENT 'Primary evacuation route description',
    alternate_route         TEXT COMMENT 'Backup route if primary blocked',
    assembly_point_primary  VARCHAR(255) NOT NULL COMMENT 'Primary muster point',
    assembly_point_alternate VARCHAR(255) COMMENT 'Alternate muster point',
    assembly_point_gps      VARCHAR(100) COMMENT 'GPS coordinates',
    
    -- Evacuation details
    evacuation_method       VARCHAR(100) COMMENT 'Walk out, Assisted, Shelter-in-Place',
    estimated_time_minutes  INT COMMENT 'Expected time to evacuate area',
    max_occupancy           INT COMMENT 'Max people in this area',
    
    -- Special considerations
    vulnerable_persons      TEXT COMMENT 'People needing assistance',
    critical_equipment      TEXT COMMENT 'Equipment to secure before evacuating',
    hazardous_areas         TEXT COMMENT 'Areas to avoid',
    
    -- Signage & maps
    evacuation_map_path     VARCHAR(500),
    signage_adequate        BOOLEAN DEFAULT TRUE,
    lighting_adequate       BOOLEAN DEFAULT TRUE,
    
    -- Status
    status                  VARCHAR(50) DEFAULT 'active',
    last_reviewed_date      DATE,
    last_drill_date         DATE,
    
    created_by              INT,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_org (organisation_id),
    INDEX idx_site (site_id),
    INDEX idx_building (building_area),
    
    CONSTRAINT fk_evac_org FOREIGN KEY (organisation_id)
        REFERENCES organisation(id) ON DELETE CASCADE,
    CONSTRAINT fk_evac_site FOREIGN KEY (site_id)
        REFERENCES sites(id) ON DELETE CASCADE,
    CONSTRAINT fk_evac_creator FOREIGN KEY (created_by)
        REFERENCES users(id) ON DELETE SET NULL
        
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Evacuation procedures register';



-- ==============================================================================
-- 5. EMERGENCY DRILLS
-- ==============================================================================
-- Scheduled and executed emergency drills

CREATE TABLE IF NOT EXISTS emergency_drills (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id         INT NOT NULL,
    site_id                 INT NOT NULL,
    emergency_plan_id       INT COMMENT 'Which plan is being exercised',
    
    -- Drill identification
    drill_name              VARCHAR(255) NOT NULL,
    drill_type              VARCHAR(100) NOT NULL COMMENT 'Evacuation, Tabletop, Full-Scale, Functional',
    emergency_scenario      VARCHAR(255) COMMENT 'What scenario is simulated',
    
    -- Schedule
    scheduled_date          DATE NOT NULL,
    scheduled_time          TIME,
    actual_date             DATE,
    actual_time             TIME,
    duration_minutes        INT,
    
    -- Participants
    drill_coordinator_id    INT,
    participants_planned    INT COMMENT 'Expected number of participants',
    participants_actual     INT COMMENT 'Actual turnout',
    observers               JSON COMMENT 'Array of observer employee_ids',
    
    -- Drill objectives
    objectives              TEXT COMMENT 'What the drill aims to test',
    success_criteria        TEXT COMMENT 'How success is measured',
    
    -- Results
    status                  VARCHAR(50) DEFAULT 'scheduled' COMMENT 'scheduled, in_progress, completed, cancelled',
    overall_rating          INT COMMENT '1-5: Poor to Excellent',
    objectives_met          BOOLEAN,
    
    -- Performance metrics
    response_time_minutes   INT COMMENT 'Time to mobilize',
    evacuation_time_minutes INT COMMENT 'Time to fully evacuate',
    headcount_accurate      BOOLEAN COMMENT 'Was attendance accurate at assembly point',
    communications_effective BOOLEAN,
    equipment_functional    BOOLEAN,
    
    -- Findings
    strengths_identified    TEXT COMMENT 'What worked well',
    weaknesses_identified   TEXT COMMENT 'What needs improvement',
    lessons_learned         TEXT,
    corrective_actions      TEXT COMMENT 'Actions to address weaknesses',
    
    -- Documentation
    report_file_path        VARCHAR(500),
    photos                  JSON,
    
    created_by              INT,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_org (organisation_id),
    INDEX idx_site (site_id),
    INDEX idx_plan (emergency_plan_id),
    INDEX idx_scheduled_date (scheduled_date),
    INDEX idx_status (status),
    
    CONSTRAINT fk_drill_org FOREIGN KEY (organisation_id)
        REFERENCES organisation(id) ON DELETE CASCADE,
    CONSTRAINT fk_drill_site FOREIGN KEY (site_id)
        REFERENCES sites(id) ON DELETE CASCADE,
    CONSTRAINT fk_drill_plan FOREIGN KEY (emergency_plan_id)
        REFERENCES emergency_plans(id) ON DELETE SET NULL,
    CONSTRAINT fk_drill_coordinator FOREIGN KEY (drill_coordinator_id)
        REFERENCES employees(id) ON DELETE SET NULL,
    CONSTRAINT fk_drill_creator FOREIGN KEY (created_by)
        REFERENCES users(id) ON DELETE SET NULL
        
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Emergency drill register';


-- ==============================================================================
-- 6. EMERGENCY EQUIPMENT
-- ==============================================================================
-- Emergency response equipment inventory

CREATE TABLE IF NOT EXISTS emergency_equipment (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id         INT NOT NULL,
    site_id                 INT NOT NULL,
    
    -- Equipment identification
    equipment_name          VARCHAR(255) NOT NULL,
    equipment_type          VARCHAR(100) COMMENT 'Fire Extinguisher, AED, First Aid Kit, SCBA, etc.',
    asset_tag               VARCHAR(100) UNIQUE,
    
    -- Location
    building                VARCHAR(255),
    floor_level             VARCHAR(100),
    location_description    TEXT COMMENT 'Exact location within building',
    
    -- Specifications
    capacity_size           VARCHAR(100) COMMENT 'e.g., 10lb, 20-person kit',
    manufacturer            VARCHAR(255),
    model_number            VARCHAR(100),
    serial_number           VARCHAR(100),
    
    -- Lifecycle
    installation_date       DATE,
    manufacture_date        DATE,
    expiry_date             DATE COMMENT 'When equipment expires',
    
    -- Inspection requirements
    inspection_frequency    INT COMMENT 'Days between inspections',
    last_inspection_date    DATE,
    next_inspection_due     DATE,
    inspector_required      VARCHAR(255) COMMENT 'Certification required',
    
    -- Status
    equipment_status        VARCHAR(50) DEFAULT 'operational' COMMENT 'operational, out_of_service, expired, missing',
    -- Backquoted: CONDITION is a MySQL reserved word, and unquoted it fails the
    -- whole CREATE TABLE. The name is kept because EmergencyEquipment.condition
    -- in app/models/emergency.py maps to it.
    `condition`             VARCHAR(50) COMMENT 'Excellent, Good, Fair, Poor',
    deficiencies            TEXT,
    
    -- Ownership
    responsible_person_id   INT,
    
    created_by              INT,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_org (organisation_id),
    INDEX idx_site (site_id),
    INDEX idx_type (equipment_type),
    INDEX idx_asset_tag (asset_tag),
    INDEX idx_inspection_due (next_inspection_due),
    INDEX idx_expiry (expiry_date),
    INDEX idx_status (equipment_status),
    
    CONSTRAINT fk_eequip_org FOREIGN KEY (organisation_id)
        REFERENCES organisation(id) ON DELETE CASCADE,
    CONSTRAINT fk_eequip_site FOREIGN KEY (site_id)
        REFERENCES sites(id) ON DELETE CASCADE,
    CONSTRAINT fk_eequip_responsible FOREIGN KEY (responsible_person_id)
        REFERENCES employees(id) ON DELETE SET NULL,
    CONSTRAINT fk_eequip_creator FOREIGN KEY (created_by)
        REFERENCES users(id) ON DELETE SET NULL
        
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Emergency equipment inventory';


-- ==============================================================================
-- 7. EMERGENCY ACTIVATIONS (Real Emergencies)
-- ==============================================================================
-- Log of actual emergency activations and response

CREATE TABLE IF NOT EXISTS emergency_activations (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id         INT NOT NULL,
    site_id                 INT NOT NULL,
    emergency_plan_id       INT COMMENT 'Which plan was activated',
    
    -- Emergency details
    emergency_type          VARCHAR(100) NOT NULL,
    emergency_description   TEXT NOT NULL,
    severity_level          VARCHAR(50) COMMENT 'Minor, Moderate, Major, Catastrophic',
    
    -- Timeline
    occurred_at             DATETIME NOT NULL COMMENT 'When emergency started',
    detected_at             DATETIME COMMENT 'When it was first noticed',
    reported_at             DATETIME COMMENT 'When it was reported',
    response_initiated_at   DATETIME COMMENT 'When response began',
    under_control_at        DATETIME COMMENT 'When situation stabilized',
    all_clear_at            DATETIME COMMENT 'When emergency ended',
    
    -- Location
    location_description    TEXT,
    affected_area           VARCHAR(255),
    
    -- Response
    incident_commander_id   INT COMMENT 'Who led the response',
    teams_activated         JSON COMMENT 'Array of team_ids mobilized',
    external_agencies       JSON COMMENT 'Array of agencies that responded',
    
    -- Impact
    evacuated               BOOLEAN DEFAULT FALSE,
    people_evacuated        INT,
    injuries                INT DEFAULT 0,
    fatalities              INT DEFAULT 0,
    property_damage         DECIMAL(15,2),
    environmental_impact    TEXT,
    business_interruption_hours INT,
    
    -- Response effectiveness
    plan_followed           BOOLEAN,
    plan_adequate           BOOLEAN,
    response_time_minutes   INT,
    evacuation_successful   BOOLEAN,
    communications_effective BOOLEAN,
    
    -- Post-emergency
    debriefing_conducted    BOOLEAN DEFAULT FALSE,
    debriefing_date         DATE,
    lessons_learned         TEXT,
    plan_updates_required   TEXT COMMENT 'Changes needed to emergency plan',
    
    -- Investigation
    investigation_required  BOOLEAN DEFAULT FALSE,
    incident_id             INT COMMENT 'Link to incidents table if formal investigation',
    
    -- Documentation
    report_file_path        VARCHAR(500),
    
    -- Status
    status                  VARCHAR(50) DEFAULT 'active' COMMENT 'active, under_control, closed',
    
    reported_by             INT,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_org (organisation_id),
    INDEX idx_site (site_id),
    INDEX idx_plan (emergency_plan_id),
    INDEX idx_occurred_at (occurred_at),
    INDEX idx_status (status),
    INDEX idx_severity (severity_level),
    
    CONSTRAINT fk_eact_org FOREIGN KEY (organisation_id)
        REFERENCES organisation(id) ON DELETE CASCADE,
    CONSTRAINT fk_eact_site FOREIGN KEY (site_id)
        REFERENCES sites(id) ON DELETE CASCADE,
    CONSTRAINT fk_eact_plan FOREIGN KEY (emergency_plan_id)
        REFERENCES emergency_plans(id) ON DELETE SET NULL,
    CONSTRAINT fk_eact_ic FOREIGN KEY (incident_commander_id)
        REFERENCES employees(id) ON DELETE SET NULL,
    CONSTRAINT fk_eact_incident FOREIGN KEY (incident_id)
        REFERENCES incidents(id) ON DELETE SET NULL,
    CONSTRAINT fk_eact_reporter FOREIGN KEY (reported_by)
        REFERENCES users(id) ON DELETE SET NULL
        
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Emergency activation log (real emergencies)';
