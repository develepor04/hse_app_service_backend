-- Migration: 056_capa_polymorphic_subject
-- Stages 05 IMPROVE and 06 VERIFY, for every family
-- Source: HSE_Workflow_Engine_Slide.pptx, stages 05-06
--
-- capa_actions could only ever hang off an incident, because incident_id was
-- the single link to a parent. That is the reason IMPROVE and VERIFY were
-- unreachable for near misses, hazards, permits and audits: those families had
-- no way to raise a corrective action at all, so there was nothing to improve
-- and nothing whose effectiveness could be confirmed.
--
-- subject_family + subject_id generalise the link. incident_id is deliberately
-- left in place and still populated for incidents, so the fourteen existing
-- aggregate queries that join or filter on it keep working untouched.

ALTER TABLE capa_actions
    ADD COLUMN subject_family VARCHAR(20) NULL
        COMMENT 'incident | near_miss | unsafe_act | risk | hazard_register | permit | audit',
    ADD COLUMN subject_id INT NULL
        COMMENT 'id within subject_family';

CREATE INDEX idx_capa_subject ON capa_actions (subject_family, subject_id);

-- Existing rows are all incidents by definition — there was no other way to
-- create one.
UPDATE capa_actions
   SET subject_family = 'incident',
       subject_id     = incident_id
 WHERE incident_id IS NOT NULL
   AND subject_family IS NULL;
