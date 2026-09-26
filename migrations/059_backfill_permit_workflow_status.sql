-- Migration: 059_backfill_permit_workflow_status
-- Reconcile historical permits onto the workflow_status vocabulary
--
-- The eight stages for permits are derived from workflow_status (see
-- PERMIT_STATUS_STAGE — `status` could not be used because six analytics
-- aggregates count status='Active' to mean "live permit").
--
-- Historically only `status` was maintained properly. workflow_status was set to
-- 'approved' at approval and then largely left alone, so the table contains
-- 12,724 permits reading workflow_status='approved' with status='Closed', and
-- 1,129 reading 'acknowledged' with status='Expired'. Deriving the stage from
-- workflow_status without this backfill would report ~17k closed and expired
-- permits as sitting at stage 05 IMPROVE and stage 02 ASSESS.
--
-- `status` is the trustworthy column for these rows, so it is the source of
-- truth here. Ordered most-specific first; each statement only touches rows the
-- previous ones did not resolve.

UPDATE permits_to_work
   SET workflow_status = 'closed'
 WHERE status = 'Closed' AND workflow_status <> 'closed';

UPDATE permits_to_work
   SET workflow_status = 'rejected'
 WHERE status = 'Rejected' AND workflow_status <> 'rejected';

UPDATE permits_to_work
   SET workflow_status = 'cancelled'
 WHERE status = 'Cancelled' AND workflow_status <> 'cancelled';

UPDATE permits_to_work
   SET workflow_status = 'expired'
 WHERE status = 'Expired' AND workflow_status NOT IN ('expired', 'closed');

UPDATE permits_to_work
   SET workflow_status = 'suspended'
 WHERE status = 'Suspended' AND workflow_status NOT IN ('suspended', 'closed');

-- An approved permit whose status still says Active is work in progress: stage
-- 06 VERIFY. This is what the old `status`-based mapping reported for these
-- rows, so the backfill preserves the stage they already had.
UPDATE permits_to_work
   SET workflow_status = 'active'
 WHERE status = 'Active' AND workflow_status = 'approved';
