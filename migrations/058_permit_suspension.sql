-- Migration: 058_permit_suspension
-- Stage 04 INVESTIGATE for permits
-- Source: HSE_Workflow_Engine_Slide.pptx, stage 04
--
-- A permit's investigate state is suspension: work has stopped because
-- something went wrong under a live permit, and nobody goes back in until the
-- cause is understood. The gate evaluation that happens before issue is triage
-- (stage 02), not investigation, which is why the permit had no stage 04 at all
-- until now.
--
-- Only the reason needs storing; the state itself rides on workflow_status.

ALTER TABLE permits_to_work
    ADD COLUMN suspension_reason TEXT NULL
        COMMENT 'Why the permit was suspended — stage 04 INVESTIGATE';
