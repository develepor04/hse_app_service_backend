import re
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.config.settings import get_settings
from app.config.logging_config import configure_logging
from app.core.exceptions import (
    NotFoundError, ConflictError, ValidationError,
    not_found_handler, conflict_handler, validation_handler,
)
from app.core.middleware import RequestLoggingMiddleware, SecurityHeadersMiddleware
from app.core.idempotency import IdempotencyMiddleware
from app.services import media_storage
from app.services.scheduler import start_scheduler, stop_scheduler

# Ensure all models are registered with SQLAlchemy metadata
import app.models  # noqa: F401

# ── Controllers ───────────────────────────────────────────────────────────────
from app.controllers import (
    organisation, site, department, working_station,
    role, employee, policy, permit_type, hazard_category,
    hazard, training_program, permit_to_work, incident,
    near_miss, safety_walk, capa_action, shift_schedule,
    training_video as training_video_controller,
    auth as auth_controller, dashboard as dashboard_controller,
    superadmin as superadmin_controller,
    organisation_setup as organisation_setup_controller,
    analytics as analytics_controller,
    checklists as checklists_controller,
    stubs as stubs_controller,
    people as people_controller,
    data_management as data_management_controller,
    org_users as org_users_controller,
    equipment_certification as equipment_certification_controller,
    equipment_register as equipment_register_controller,
    notification as notification_controller,
    vendor as vendor_controller,
    ai as ai_controller,
    worker as worker_controller,
    assigned_tasks as assigned_tasks_controller,
    team as team_controller,
    incident_workflow as incident_workflow_controller,
    capa_workflow as capa_workflow_controller,
    event_drafts as event_drafts_controller,
    settings as settings_controller,
    near_miss_workflow as near_miss_workflow_controller,
    unsafe_act_workflow as unsafe_act_workflow_controller,
    risk_workflow as risk_workflow_controller,
    permit_workflow as permit_workflow_controller,
    hazard_register as hazard_register_controller,
    hazard_trail as hazard_trail_controller,
    audit as audit_controller,
    audit_trail as audit_trail_controller,
    incident_trail as incident_trail_controller,
    near_miss_trail as near_miss_trail_controller,
    unsafe_act_trail as unsafe_act_trail_controller,
    risk_trail as risk_trail_controller,
    risk_assessment as risk_assessment_controller,
    permit_trail as permit_trail_controller,
    # ── WF-06 … WF-09 (HSE_Mobile_Architecture_v4) ───────────────────────────
    competence as competence_controller,
    fatigue as fatigue_controller,
    gates as gates_controller,
    contractor as contractor_controller,
    transport as transport_controller,
    sps as sps_controller,
    ai_governance as ai_governance_controller,
    orchestrator as orchestrator_controller,
    workflow_engine as workflow_engine_controller,
    events as events_controller,
    change_log as change_log_controller,
    # ── WF-13 Barrier/Bowtie Analysis ────────────────────────────────────────
    bowtie as bowtie_controller,
    # ── WF-14 Process Safety Management ──────────────────────────────────────
    psm as psm_controller,
    # ── WF-15 Emergency Management ───────────────────────────────────────────
    emergency as emergency_controller,
)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    start_scheduler()
    yield
    stop_scheduler()


def create_app() -> FastAPI:
    if settings.app_debug and settings.app_env.lower() in ("production", "prod"):
        raise RuntimeError(
            "Refusing to start with debug=True while APP_ENV=production — "
            "this would expose full Python tracebacks (source + locals) on errors."
        )

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        debug=settings.app_debug,
        lifespan=lifespan,
    )

    # ── CORS ─────────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Request logging ───────────────────────────────────────────────────────
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(IdempotencyMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)

    # ── Uploaded evidence ─────────────────────────────────────────────────────
    # Incident photos are written to backend/uploads and the record stores the
    # URL path, so the file has to be served back for the supervisor and manager
    # screens that render evidence_json. Mounted outside the /api/v1 prefix
    # because these are files, not API resources.
    #
    # U-020: this used to be a plain StaticFiles mount — any UUID filename,
    # guessed or leaked, was served to anyone with no auth and no log. Every
    # URL `save_image` hands out is now signed (see media_storage.sign_path);
    # this route is the other half, rejecting anything unsigned/expired/
    # tampered before FileResponse ever touches disk.
    media_storage.UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

    @app.get(media_storage.URL_PREFIX + "/{subdir}/{filename}", name="uploads")
    def serve_upload(subdir: str, filename: str, exp: str = "", sig: str = ""):
        safe_subdir = re.sub(r"[^a-z0-9_]", "", (subdir or "").lower())
        safe_filename = re.sub(r"[^a-zA-Z0-9_.-]", "", filename or "")
        if not safe_subdir or not safe_filename or safe_subdir != subdir or safe_filename != filename:
            raise HTTPException(status_code=404, detail="Not found")

        path = f"{media_storage.URL_PREFIX}/{safe_subdir}/{safe_filename}"
        if not media_storage.verify_signed_path(path, exp, sig):
            raise HTTPException(status_code=403, detail="Missing or expired signature")

        file_path = (media_storage.UPLOAD_ROOT / safe_subdir / safe_filename).resolve()
        if media_storage.UPLOAD_ROOT.resolve() not in file_path.parents or not file_path.is_file():
            raise HTTPException(status_code=404, detail="Not found")

        return FileResponse(file_path)

    # ── Exception handlers ────────────────────────────────────────────────────
    app.add_exception_handler(NotFoundError,   not_found_handler)
    app.add_exception_handler(ConflictError,   conflict_handler)
    app.add_exception_handler(ValidationError, validation_handler)

    # ── Routers ───────────────────────────────────────────────────────────────
    prefix = "/api/v1"
    for router_module in [
        organisation, site, department, working_station,
        role, employee, policy, permit_type, hazard_category,
        hazard, training_program, permit_to_work, incident,
        near_miss, safety_walk, capa_action, shift_schedule,
    ]:
        app.include_router(router_module.router, prefix=prefix)

    app.include_router(auth_controller.router, prefix=prefix)
    app.include_router(dashboard_controller.router, prefix=prefix)
    app.include_router(superadmin_controller.router, prefix=prefix)
    app.include_router(organisation_setup_controller.router, prefix=prefix)
    app.include_router(analytics_controller.router, prefix=prefix)
    app.include_router(checklists_controller.router, prefix=prefix)
    app.include_router(stubs_controller.router, prefix=prefix)
    app.include_router(people_controller.router, prefix=prefix)
    app.include_router(data_management_controller.router, prefix=prefix)
    app.include_router(org_users_controller.router, prefix=prefix)
    app.include_router(equipment_certification_controller.router, prefix=prefix)
    app.include_router(equipment_register_controller.router, prefix=prefix)
    app.include_router(notification_controller.router, prefix=prefix)
    app.include_router(vendor_controller.router, prefix=prefix)
    app.include_router(ai_controller.router, prefix=prefix)
    app.include_router(worker_controller.router, prefix=prefix)
    app.include_router(training_video_controller.router, prefix=prefix)
    app.include_router(assigned_tasks_controller.router, prefix=prefix)
    app.include_router(team_controller.router, prefix=prefix)
    app.include_router(incident_workflow_controller.router, prefix=prefix)
    # WF-04 — the ten-step CAPA lifecycle, shared by every event family. The
    # /capa-actions router above it is the website's plain CRUD on the same
    # table and is deliberately left alone.
    app.include_router(capa_workflow_controller.router, prefix=prefix)
    app.include_router(event_drafts_controller.router, prefix=prefix)
    app.include_router(settings_controller.router, prefix=prefix)
    # The web-console router first: its literal paths (/audits/templates,
    # /audits/trends, /audits/auditors) have the same shape as /audits/{id},
    # and FastAPI matches in registration order.
    app.include_router(audit_controller.web_router, prefix=prefix)
    app.include_router(audit_controller.router, prefix=prefix)
    app.include_router(audit_trail_controller.router, prefix=prefix)
    # Admin view: every action on an incident, stage 01 through stage 08.
    app.include_router(incident_trail_controller.router, prefix=prefix)
    app.include_router(near_miss_trail_controller.router, prefix=prefix)
    app.include_router(unsafe_act_trail_controller.router, prefix=prefix)
    # Risk observations on `risk_reports`. Its own trail, separate from the
    # hazard register's below — different table, different status vocabulary.
    app.include_router(risk_trail_controller.router, prefix=prefix)
    # WF-01 Flow B. Separate from risk_workflow above: that is a worker's
    # sighting of one hazard, this is the ten-step assessment of an activity.
    app.include_router(risk_assessment_controller.router, prefix=prefix)
    app.include_router(permit_trail_controller.router, prefix=prefix)
    # Near miss / unsafe act / risk each get their own table and their own workflow.
    app.include_router(near_miss_workflow_controller.router, prefix=prefix)
    app.include_router(unsafe_act_workflow_controller.router, prefix=prefix)
    app.include_router(risk_workflow_controller.router, prefix=prefix)
    # Permit to Work (flow 6) and Hazard register (flow 5) role workflows.
    app.include_router(permit_workflow_controller.router, prefix=prefix)
    # The Unsafe Act register (flow 5). Mounted twice on purpose: the family
    # was renamed from "Hazard" when the two merged in 080, and the /hazard-*
    # paths stay so already-shipped mobile builds and old bookmarks keep
    # resolving. Same router, same handlers — only the path differs.
    app.include_router(hazard_register_controller.router, prefix=f"{prefix}/unsafe-act-register")
    app.include_router(hazard_trail_controller.router, prefix=f"{prefix}/unsafe-act-register-trail")
    app.include_router(hazard_register_controller.router, prefix=f"{prefix}/hazard-register")
    app.include_router(hazard_trail_controller.router, prefix=f"{prefix}/hazard-trail")

    # ── WF-06 … WF-09 · competence gates the permit, so it registers first ────
    app.include_router(competence_controller.router, prefix=prefix)
    app.include_router(competence_controller.training_router, prefix=prefix)
    app.include_router(fatigue_controller.router, prefix=prefix)
    app.include_router(gates_controller.router, prefix=prefix)
    app.include_router(contractor_controller.router, prefix=prefix)
    app.include_router(contractor_controller.rams_router, prefix=prefix)
    app.include_router(transport_controller.router, prefix=prefix)
    app.include_router(transport_controller.vehicles_router, prefix=prefix)
    app.include_router(sps_controller.router, prefix=prefix)
    app.include_router(ai_governance_controller.router, prefix=prefix)
    # Every AI capability is reached through the Orchestrator, which enforces the
    # LEAN hierarchy and writes the decision log.
    app.include_router(orchestrator_controller.router, prefix=prefix)
    # One view of the eight stages across all five event families.
    app.include_router(workflow_engine_controller.router, prefix=prefix)
    # Domain event bus — the closure cascade and its audit trail.
    app.include_router(events_controller.router, prefix=prefix)
    app.include_router(change_log_controller.router, prefix=prefix)
    # ── WF-13 Barrier/Bowtie Analysis ────────────────────────────────────────
    app.include_router(bowtie_controller.router, prefix=prefix)
    # ── WF-14 Process Safety Management ──────────────────────────────────────
    app.include_router(psm_controller.router, prefix=prefix)
    # ── WF-15 Emergency Management ───────────────────────────────────────────
    app.include_router(emergency_controller.router, prefix=prefix)

    @app.get("/health", tags=["Health"])
    def health():
        return {"status": "ok", "version": settings.app_version}

    return app


app = create_app()
