"""Domain event types.

Source: Architecture doc section 6.1 (Platform Event Catalogue). Only the
closure events are emitted today — the rest are declared so consumers can be
written against a stable name before the publisher exists, and so the catalogue
reads as the spec defines it rather than as whatever happens to be wired.
"""

# ── Emitted today ────────────────────────────────────────────────────────────
INCIDENT_CLOSED = "IncidentInvestigationClosed"
NEAR_MISS_CLOSED = "NearMissClosed"
UNSAFE_ACT_CLOSED = "UnsafeActClosed"
HAZARD_CLOSED = "HazardClosed"

# ── Declared, not yet emitted ────────────────────────────────────────────────
INCIDENT_REPORTED = "IncidentReported"
INCIDENT_SEVERITY_CLASSIFIED = "IncidentSeverityClassified"
NEAR_MISS_REPORTED = "NearMissReported"
CAPA_CLOSED = "CAPAClosed"
CAPA_OVERDUE = "CAPAOverdue"
PERMIT_ISSUED = "PermitIssued"
PERMIT_EXPIRED = "PermitExpired"
RAMS_EXPIRING = "RAMSExpiring"
TRAINING_EXPIRED = "TrainingExpired"
COMPETENCY_GAP_DETECTED = "CompetencyGapDetected"
AUDIT_COMPLETED = "AuditCompleted"

# Workflow family -> its closure event, so a publisher looks it up instead of
# every call site hardcoding a string.
CLOSURE_EVENT_FOR = {
    "incident": INCIDENT_CLOSED,
    "near_miss": NEAR_MISS_CLOSED,
    "unsafe_act": UNSAFE_ACT_CLOSED,
    "risk": HAZARD_CLOSED,
    "hazard": HAZARD_CLOSED,
}
