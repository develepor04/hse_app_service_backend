-- ─────────────────────────────────────────────────────────────────────────────
-- 082 · Sites and departments the employee form can actually offer
--
-- Two things, both needed before Site/Department dropdowns mean anything.
--
-- 1. MORE SITES. Org 4 had exactly one site, so a Site dropdown would be a
--    one-item list. Each organisation now has at least three.
--
-- 2. THE CROSS-ORG LINK, WHICH IS A BUG. departments.site_id pointed at sites
--    belonging to OTHER organisations -- org 4's eight departments were split
--    across sites owned by orgs 1, 2 and 3. Only org 1 was internally
--    consistent. That matters more than it looks: an employee's site is derived
--    as employee -> department -> site, so every org-4 employee would have
--    resolved to another tenant's site, and any site-scoped query would have
--    crossed the tenant boundary.
--
--    Fixed by repointing every department at a site inside its own
--    organisation. Departments already sitting on a correct site are left
--    alone, so this is safe to re-run.
--
-- Nothing is deleted. Existing ids keep their meaning.
-- ─────────────────────────────────────────────────────────────────────────────


-- ── Extra sites, one INSERT guarded per organisation so a re-run is a no-op ──
-- Also skip when the target organisation is missing (fresh empty DB).
INSERT INTO sites (site_name, address, city, type, operational_status, organisation_id)
SELECT * FROM (
    SELECT 'Port Talbot Blade Facility' AS a, 'Harbour Way, Port Talbot' AS b,
           'Neath Port Talbot' AS c, 'Manufacturing' AS d, 'Operational' AS e, 4 AS f
    UNION ALL SELECT 'Newport Tower Works', 'Queensway Meadows, Newport',
           'Newport', 'Manufacturing', 'Operational', 4
    UNION ALL SELECT 'Swansea Service Depot', 'Fabian Way, Swansea',
           'Swansea', 'Maintenance', 'Operational', 4
) AS candidate
WHERE EXISTS (SELECT 1 FROM organisation o WHERE o.id = candidate.f)
  AND NOT EXISTS (
    SELECT 1 FROM (SELECT site_name, organisation_id FROM sites) existing
     WHERE existing.site_name = candidate.a
       AND existing.organisation_id = candidate.f
);

INSERT INTO sites (site_name, address, city, type, operational_status, organisation_id)
SELECT * FROM (
    SELECT 'Coventry Gearbox Plant' AS a, 'Prologis Park, Coventry' AS b,
           'West Midlands' AS c, 'Manufacturing' AS d, 'Operational' AS e, 2 AS f
    UNION ALL SELECT 'Derby Drivetrain Works', 'Sinfin Lane, Derby',
           'Derbyshire', 'Manufacturing', 'Operational', 2
) AS candidate
WHERE EXISTS (SELECT 1 FROM organisation o WHERE o.id = candidate.f)
  AND NOT EXISTS (
    SELECT 1 FROM (SELECT site_name, organisation_id FROM sites) existing
     WHERE existing.site_name = candidate.a
       AND existing.organisation_id = candidate.f
);

INSERT INTO sites (site_name, address, city, type, operational_status, organisation_id)
SELECT * FROM (
    SELECT 'Hull Offshore Terminal' AS a, 'Alexandra Dock, Hull' AS b,
           'East Yorkshire' AS c, 'Logistics' AS d, 'Operational' AS e, 3 AS f
    UNION ALL SELECT 'Grimsby Support Base', 'Royal Dock, Grimsby',
           'Lincolnshire', 'Maintenance', 'Operational', 3
) AS candidate
WHERE EXISTS (SELECT 1 FROM organisation o WHERE o.id = candidate.f)
  AND NOT EXISTS (
    SELECT 1 FROM (SELECT site_name, organisation_id FROM sites) existing
     WHERE existing.site_name = candidate.a
       AND existing.organisation_id = candidate.f
);


-- ── Repoint departments that sit on another organisation's site ──────────────
-- Spread across that organisation's own sites rather than piling every
-- department onto the first one, so the Site filter actually narrows the
-- Department list instead of showing all of them under one site.
UPDATE departments d
  JOIN (
        SELECT s.id, s.organisation_id,
               ROW_NUMBER() OVER (PARTITION BY s.organisation_id ORDER BY s.id) - 1 AS seq,
               COUNT(*)    OVER (PARTITION BY s.organisation_id)                  AS total
          FROM sites s
       ) own_site
    ON own_site.organisation_id = d.organisation_id
   JOIN (
        SELECT id, organisation_id,
               ROW_NUMBER() OVER (PARTITION BY organisation_id ORDER BY id) - 1 AS dseq
          FROM departments
       ) dept_seq
    ON dept_seq.id = d.id
   SET d.site_id = own_site.id
 WHERE own_site.seq = dept_seq.dseq MOD own_site.total
   AND d.organisation_id IS NOT NULL
   AND d.site_id NOT IN (
        SELECT id FROM (SELECT id, organisation_id FROM sites) s2
         WHERE s2.organisation_id = d.organisation_id
   );
