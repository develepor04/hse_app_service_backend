-- Migration: 066_hazard_workflow_stages
-- The Hazard register (flow 5) gets a real eight-stage lifecycle, the way
-- incidents got one in 028 and 057.
--
-- Migration 031 gave the register four states -- open, under_review, controlled,
-- closed -- and a single `review_notes` column to carry every one of them.
-- workflow_stages.HAZARD_REGISTER_STATUS_STAGE already names eight states, so
-- interim_control, controls_planned and pending_verification were reachable in
-- the mapping but had nowhere to record what was actually done or who did it.
-- A hazard could be marked `controlled` with no evidence that any control was
-- designed, applied or checked, which is the failure the VERIFY stage exists to
-- prevent.
--
-- PURELY ADDITIVE. `register_status`, `controls` and `review_notes` keep their
-- meanings, so the existing register list, the auditor list and the stats
-- summary are unaffected. Every column added here is NULLable.

-- ═══════════════════════════════════════════════════════════════════════════
-- Stage 02 ASSESS -- triage the logged hazard
-- ═══════════════════════════════════════════════════════════════════════════
-- `severity` and `probability` are the reporter's impression and drive nothing.
-- assessed_priority is what ranks this hazard against every other safety event
-- on the unified queue, and matches the P1-P5 scale the report families use.
ALTER TABLE hazards
    ADD COLUMN assessed_priority VARCHAR(4) DEFAULT NULL
        COMMENT 'P1..P5 -- the shared cross-family priority scale',
    ADD COLUMN assessed_label VARCHAR(60) DEFAULT NULL,
    ADD COLUMN risk_score INT DEFAULT NULL
        COMMENT 'Severity x probability, 1-25, computed at assessment',
    ADD COLUMN assessed_by INT DEFAULT NULL,
    ADD COLUMN assessed_at DATETIME DEFAULT NULL,
    ADD COLUMN response_due_at DATETIME DEFAULT NULL
        COMMENT 'When containment is owed by, derived from assessed_priority';

-- ═══════════════════════════════════════════════════════════════════════════
-- Stage 03 RESPOND -- the temporary control, while the permanent one is designed
-- ═══════════════════════════════════════════════════════════════════════════
-- Kept apart from `controls`, which 031 uses for the permanent control. Folding
-- the two together would lose the distinction between "barriered off this
-- morning" and "guard fitted", and the register would then claim a hazard is
-- controlled when all that happened was a cone was put in front of it.
ALTER TABLE hazards
    ADD COLUMN interim_control TEXT DEFAULT NULL
        COMMENT 'Temporary measure holding the hazard while the fix is designed',
    ADD COLUMN interim_control_by INT DEFAULT NULL,
    ADD COLUMN interim_control_at DATETIME DEFAULT NULL,
    ADD COLUMN work_stopped TINYINT(1) NOT NULL DEFAULT 0
        COMMENT 'The hazard was severe enough to stop the job';

-- ═══════════════════════════════════════════════════════════════════════════
-- Stage 04 INVESTIGATE -- why the hazard exists, not merely that it does
-- ═══════════════════════════════════════════════════════════════════════════
ALTER TABLE hazards
    ADD COLUMN review_started_at DATETIME DEFAULT NULL,
    ADD COLUMN root_cause VARCHAR(255) DEFAULT NULL,
    ADD COLUMN persons_exposed INT DEFAULT NULL
        COMMENT 'How many people the hazard can reach -- drives control urgency';

-- ═══════════════════════════════════════════════════════════════════════════
-- Stage 05 IMPROVE -- the permanent control, by hierarchy
-- ═══════════════════════════════════════════════════════════════════════════
-- control_hierarchy is recorded rather than inferred because the whole point of
-- the stage is that PPE is the weakest answer and elimination the strongest. A
-- register that cannot report how many hazards were closed out with PPE alone
-- cannot show whether controls are improving.
ALTER TABLE hazards
    ADD COLUMN planned_controls TEXT DEFAULT NULL,
    ADD COLUMN control_hierarchy VARCHAR(40) DEFAULT NULL
        COMMENT 'elimination | substitution | engineering | administrative | ppe',
    ADD COLUMN control_owner_id INT DEFAULT NULL,
    ADD COLUMN control_due_date DATE DEFAULT NULL,
    ADD COLUMN controls_planned_by INT DEFAULT NULL,
    ADD COLUMN controls_planned_at DATETIME DEFAULT NULL;

-- ═══════════════════════════════════════════════════════════════════════════
-- Stage 06 VERIFY -- did the control actually hold?
-- ═══════════════════════════════════════════════════════════════════════════
-- control_verification_notes, not `verification_notes`: that column already
-- belongs to the auditor's post-closure assurance check from 031 and gates
-- nothing. Reusing it would overwrite the auditor's record with the manager's,
-- and the two answer different questions.
ALTER TABLE hazards
    ADD COLUMN controls_verified_by INT DEFAULT NULL,
    ADD COLUMN controls_verified_at DATETIME DEFAULT NULL,
    ADD COLUMN control_verification_notes TEXT DEFAULT NULL,
    ADD COLUMN verification_failures INT NOT NULL DEFAULT 0
        COMMENT 'Times the control was checked and found not to hold';

-- ═══════════════════════════════════════════════════════════════════════════
-- Stage 07 LEARN and 08 CLOSE
-- ═══════════════════════════════════════════════════════════════════════════
ALTER TABLE hazards
    ADD COLUMN lessons_learned TEXT DEFAULT NULL,
    ADD COLUMN lesson_captured_by INT DEFAULT NULL,
    ADD COLUMN lesson_captured_at DATETIME DEFAULT NULL,
    ADD COLUMN closure_notes TEXT DEFAULT NULL,
    ADD COLUMN closed_by INT DEFAULT NULL,
    ADD COLUMN closed_at DATETIME DEFAULT NULL;

-- ═══════════════════════════════════════════════════════════════════════════
-- Foreign keys
-- ═══════════════════════════════════════════════════════════════════════════
-- ON DELETE SET NULL throughout: losing an employee row must not delete the
-- hazard that person logged.
ALTER TABLE hazards
    ADD CONSTRAINT fk_hz_assessed_by
        FOREIGN KEY (assessed_by) REFERENCES employees (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_hz_interim_control_by
        FOREIGN KEY (interim_control_by) REFERENCES employees (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_hz_control_owner
        FOREIGN KEY (control_owner_id) REFERENCES employees (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_hz_controls_planned_by
        FOREIGN KEY (controls_planned_by) REFERENCES employees (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_hz_controls_verified_by
        FOREIGN KEY (controls_verified_by) REFERENCES employees (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_hz_lesson_captured_by
        FOREIGN KEY (lesson_captured_by) REFERENCES employees (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_hz_closed_by
        FOREIGN KEY (closed_by) REFERENCES employees (id)
        ON DELETE SET NULL ON UPDATE CASCADE;

-- ═══════════════════════════════════════════════════════════════════════════
-- Indexes
-- ═══════════════════════════════════════════════════════════════════════════
-- The register list, the auditor list and the pipeline all filter on
-- register_status within an organisation, and the queue orders by priority.
CREATE INDEX idx_hz_org_status ON hazards (organisation_id, register_status);
CREATE INDEX idx_hz_priority ON hazards (assessed_priority, response_due_at);

-- ═══════════════════════════════════════════════════════════════════════════
-- Backfill
-- ═══════════════════════════════════════════════════════════════════════════
-- Rows logged before this migration carry their permanent control in `controls`
-- and were reviewed through the generic /review endpoint. Copy that forward so
-- an existing `controlled` hazard does not read as having no planned control at
-- all once the detail screen starts showing planned_controls.
UPDATE hazards
   SET planned_controls = controls
 WHERE planned_controls IS NULL
   AND controls IS NOT NULL
   AND controls <> '';

-- A hazard already sitting at `controlled` or `closed` was verified by whoever
-- last reviewed it -- that is the only signal the old four-state model recorded.
-- Stamped from the review columns rather than left NULL, so the VERIFY stage on
-- the tracker does not show as never having happened for historical rows.
UPDATE hazards
   SET controls_verified_by = reviewed_by,
       controls_verified_at = reviewed_at
 WHERE register_status IN ('controlled', 'closed')
   AND controls_verified_at IS NULL
   AND reviewed_at IS NOT NULL;

UPDATE hazards
   SET closed_by = reviewed_by,
       closed_at = reviewed_at
 WHERE register_status = 'closed'
   AND closed_at IS NULL
   AND reviewed_at IS NOT NULL;
