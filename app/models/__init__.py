# Import every model so SQLAlchemy's MetaData is fully populated before
# any flush/commit that involves cross-table foreign keys.
from app.models.base import Base
from app.models.organisation import Organisation
from app.models.hazard_category import HazardCategory
from app.models.hazard import Hazard
from app.models.role import Role
from app.models.site import Site
from app.models.permit_type import PermitType
from app.models.training_program import TrainingProgram
from app.models.training_video import TrainingVideo, TrainingVideoComment
from app.models.policy import Policy
from app.models.department import Department
from app.models.working_station import WorkingStation
from app.models.employee import Employee
from app.models.permit_to_work import PermitToWork
from app.models.incident import Incident
from app.models.near_miss import NearMiss
from app.models.unsafe_act import UnsafeAct
from app.models.risk_report import RiskReport
from app.models.safety_walk import SafetyWalk
from app.models.audit import (
    Audit,
    AuditChecklistItem,
    AuditChecklistTemplate,
    AuditChecklistTemplateItem,
    AuditEvidence,
    AuditFinding,
    AuditProgramme,
)
from app.models.capa_action import CapaAction
from app.models.capa_lifecycle import (
    CapaEffectivenessReview,
    CapaEvidence,
    CapaProgressNote,
)
from app.models.event_draft import EventDraft
from app.models.shift_schedule import ShiftSchedule
from app.models.app_role import AppRole
from app.models.user import User
from app.models.organisation_invite import OrganisationInvite
from app.models.subscription import Subscription
from app.models.notification import Notification
from app.models.notification_read import NotificationRead
from app.models.data_import import DataImport
from app.models.validation_log import ValidationLog
from app.models.api_integration import ApiIntegration
from app.models.document import Document
from app.models.equipment_certification import EquipmentCertification
from app.models.api_key import ApiKey
from app.models.webhook import Webhook
from app.models.audit_log import AuditLog

# ── WF-06 … WF-09 (HSE_Mobile_Architecture_v4) ────────────────────────────────
from app.models.competence import (
    CertificationType,
    CompetenceGap,
    CompetenceMatrix,
    CompetenceProfile,
    TrainingRecord,
)
from app.models.fatigue import FatigueDeclaration
from app.models.gates import GateDecisionLog, OverrideLog
from app.models.contractor import (
    ContractorCompany,
    ContractorScorecard,
    ContractorWorker,
    IogpBenchmark,
    RamsScore,
)
from app.models.transport import CheckInEvent, JourneyPlan, Vehicle, WeatherLimitTable
from app.models.sps import (
    CapaLookup,
    ChangeEvent,
    SpsAlert,
    SpsSnapshot,
    SupervisorInteraction,
    WorkExecutionEvent,
)
from app.models.ai_decision import AiDecisionLog

# ── WF-13 Barrier/Bowtie Analysis ─────────────────────────────────────────────
from app.models.bowtie import (
    BowtieDiagram,
    BowtieThreat,
    BowtieConsequence,
    BowtieBarrier,
    BowtieBarrierVerification,
    BowtieIncidentLink,
    BowtieReview,
    BowtieBarrierAlert,
)

# ── WF-14 Process Safety Management ───────────────────────────────────────────
from app.models.psm import (
    PSMElement,
    PHAStudy,
    PHAScenario,
    PHARecommendation,
    CriticalEquipment,
    EquipmentInspection,
    OperatingProcedure,
    PSMAudit,
    PSMAuditFinding,
)

# ── WF-15 Emergency Management ────────────────────────────────────────────────
from app.models.emergency import (
    EmergencyPlan,
    EmergencyResponseTeam,
    EmergencyContact,
    EvacuationProcedure,
    EmergencyDrill,
    EmergencyEquipment,
    EmergencyActivation,
)

__all__ = [
    "Base", "Organisation", "HazardCategory", "Hazard", "Role",
    "Site", "PermitType", "TrainingProgram", "TrainingVideo", "TrainingVideoComment", "Policy", "Department",
    "WorkingStation", "Employee", "PermitToWork", "Incident", "NearMiss",
    "UnsafeAct", "RiskReport",
    "SafetyWalk", "CapaAction", "ShiftSchedule", "AppRole", "User",
    # WF-05 audit, inspection & compliance monitoring
    "Audit", "AuditChecklistItem", "AuditFinding", "AuditEvidence", "AuditProgramme",
    "AuditChecklistTemplate", "AuditChecklistTemplateItem",
    "OrganisationInvite", "Subscription", "Notification", "NotificationRead",
    "DataImport", "ValidationLog", "ApiIntegration", "Document",
    "EquipmentCertification", "ApiKey", "Webhook", "AuditLog",
    # WF-06 competence & human readiness
    "CertificationType", "CompetenceProfile", "CompetenceMatrix",
    "TrainingRecord", "CompetenceGap", "FatigueDeclaration",
    # Gate engine
    "GateDecisionLog", "OverrideLog",
    # WF-08 contractor
    "ContractorCompany", "ContractorWorker", "RamsScore",
    "ContractorScorecard", "IogpBenchmark",
    # WF-09 transport
    "Vehicle", "WeatherLimitTable", "JourneyPlan", "CheckInEvent",
    # WF-07 SPS
    "SpsSnapshot", "SpsAlert", "CapaLookup", "WorkExecutionEvent",
    "SupervisorInteraction", "ChangeEvent",
    # AI governance
    "AiDecisionLog",
    # WF-13 Barrier/Bowtie Analysis
    "BowtieDiagram", "BowtieThreat", "BowtieConsequence", "BowtieBarrier",
    "BowtieBarrierVerification", "BowtieIncidentLink", "BowtieReview",
    "BowtieBarrierAlert",
    # WF-14 Process Safety Management
    "PSMElement", "PHAStudy", "PHAScenario", "PHARecommendation",
    "CriticalEquipment", "EquipmentInspection", "OperatingProcedure",
    "PSMAudit", "PSMAuditFinding",
    # WF-15 Emergency Management
    "EmergencyPlan", "EmergencyResponseTeam", "EmergencyContact",
    "EvacuationProcedure", "EmergencyDrill", "EmergencyEquipment",
    "EmergencyActivation",
    # Stage 01 RECORD
    "EventDraft",
]
