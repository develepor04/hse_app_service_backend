-- Migration: 055_create_event_drafts
-- Stage 01 RECORD — "Capture in <60 sec"
-- Source: HSE_Workflow_Engine_Slide.pptx, stage 01
--
-- Every event family needs a state to occupy stage 01: something captured but
-- not yet submitted. The obvious approach -- a `draft` row in incidents /
-- near_misses / permits_to_work -- was tried during the incident work and
-- rejected. Those tables are counted unconditionally by the 12-month recurrence
-- lookup that drives HIPO and the P1-P5 classification, by the SPS engine, by
-- contractor risk and by every dashboard. An unsubmitted form sitting in them
-- would inflate KPIs and, worse, change the computed severity of OTHER records.
--
-- So drafts live here instead. Nothing aggregates this table. A draft is the
-- record at stage 01; submitting it creates the real row at stage 02 through
-- the family's normal report/request/create path and deletes the draft.

CREATE TABLE IF NOT EXISTS event_drafts (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id     INT NULL,

    -- Which family this draft will become on submit: incident, near_miss,
    -- unsafe_act, risk, hazard_register, permit, audit.
    family              VARCHAR(20) NOT NULL,

    -- The employee who started it. A draft is private to its author until
    -- submitted, so this is the ownership check, not just provenance.
    created_by          INT NULL,

    -- The partially-filled form, shaped exactly like the family's submit
    -- payload. Kept opaque so adding a field to a report form needs no
    -- migration here.
    payload             JSON NULL,

    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_event_drafts_owner (organisation_id, created_by, family)
);
