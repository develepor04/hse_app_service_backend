"""Appendix A — statutory reporting thresholds and deadlines.

Source: EHSERA AI Orchestration Platform ISMS v1.0, Appendix A "Statutory
Reporting Reference".

What this module does: given the facts of an incident and the jurisdiction of
the site it happened at, decide whether a regulator must be notified, which
regulator, under which named provision, and by when.

What this module deliberately does NOT do: notify anyone. The spec is explicit —
"All regulatory submissions remain subject to human review and authorisation."
This produces a draft obligation for a Safety Manager to authorise; it never
submits, and it never marks anything as reported.

All six Appendix A jurisdictions are encoded: UK (RIDDOR 2013), US (OSHA 29 CFR
1904), UAE (Ministerial Decree 32/1982), KSA (Labour Law Art. 138), Australia
(Model WHS Act 2011) and the EU (89/391/EEC + Seveso III).

Three of them route to a sub-national authority — the emirate for UAE major
construction incidents, the state for Australian WHS notifications, the member
state for EU transposition. Pass it as `region`. Without it the obligation is
still raised, but marked `encoded=False` so the UI can show that the specific
authority or deadline needs confirming rather than presenting a guess as fact.

Deadlines are expressed as hours from the incident. "Immediate" is modelled as
0 hours, which is what makes it sort first in a notification queue.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional


# ── Jurisdictions ────────────────────────────────────────────────────────────
UK = "UK"
US = "US"
UAE = "UAE"
KSA = "KSA"
AU = "AU"
EU = "EU"

REGULATORS = {
    UK: "Health and Safety Executive (HSE)",
    US: "Occupational Safety and Health Administration (OSHA)",
    UAE: "Ministry of Human Resources and Emiratisation (MOHRE)",
    KSA: "Ministry of Human Resources and Social Development (HRSD)",
    AU: "State/Territory WHS regulator",
    EU: "National competent authority",
}

LEGAL_BASIS = {
    UK: "RIDDOR 2013",
    US: "OSHA 29 CFR 1904",
    UAE: "Ministerial Decree No. 32 of 1982",
    KSA: "Saudi Labour Law Art. 138 / OSH Regulations",
    AU: "Model WHS Act 2011 s.38",
    EU: "Directive 89/391/EEC / Seveso III 2012/18/EU",
}

# All six Appendix A jurisdictions now have encoded thresholds. Kept as an empty
# tuple rather than deleted: `evaluate` no longer branches on it, but anything
# importing it (dashboards, tests) still resolves.
NOT_YET_ENCODED = ()

# Some obligations still return encoded=False at the individual level — an AU
# incident with no state set, an EU one with no member state, a UAE major
# construction incident with no emirate. In those cases the obligation is real
# but the specific authority or deadline depends on a region we were not given.

IMMEDIATE = 0


@dataclass
class StatutoryObligation:
    jurisdiction: str
    regulator: str
    legal_basis: str
    event: str                       # the Appendix A "Reportable Event" row
    criteria: str                    # why this incident met it
    notify_within_hours: int         # 0 = immediate
    written_report_days: Optional[int] = None
    due_at: Optional[datetime] = None
    written_due_at: Optional[datetime] = None
    requires_human_authorisation: bool = True
    encoded: bool = True             # False = registered but rules not written


@dataclass
class StatutoryResult:
    reportable: bool
    obligations: List[StatutoryObligation] = field(default_factory=list)
    explanation: str = ""

    @property
    def earliest_due_at(self) -> Optional[datetime]:
        due = [o.due_at for o in self.obligations if o.due_at is not None]
        return min(due) if due else None

    @property
    def most_urgent(self) -> Optional[StatutoryObligation]:
        if not self.obligations:
            return None
        return min(self.obligations, key=lambda o: o.notify_within_hours)


# ══════════════════════════════════════════════════════════════════════════════
# United Kingdom — RIDDOR 2013 · regulator: HSE
#
#   Fatality              immediate  + written within 10 days
#   Specified Injury      immediate  + written within 10 days
#   Dangerous Occurrence  immediate  + written within 10 days
#   Over-7-Day Injury     within 15 days
#   Occupational Disease  within 10 days of written diagnosis
# ══════════════════════════════════════════════════════════════════════════════

# Appendix A's Specified Injury list. Matched against a caller-supplied injury
# type, lowercased and substring-matched so "Amputation of finger" hits
# "amputation" without needing an exact enum from the mobile form.
_UK_SPECIFIED_INJURIES = (
    "amputation",
    "fracture",
    "loss of sight",
    "crush",
    "scalping",
    "chemical burn",
    "resuscitation",
    "unconscious",
)


def _uk(
    fatality: bool,
    injury_type: Optional[str],
    days_away: Optional[int],
    dangerous_occurrence: bool,
    hospitalised_over_24h: bool,
    occupational_disease: bool,
) -> List[StatutoryObligation]:
    out: List[StatutoryObligation] = []
    itype = (injury_type or "").strip().lower()

    if fatality:
        out.append(StatutoryObligation(
            UK, REGULATORS[UK], LEGAL_BASIS[UK],
            event="Fatality",
            criteria="Death arising from a work activity.",
            notify_within_hours=IMMEDIATE, written_report_days=10,
        ))

    specified = [s for s in _UK_SPECIFIED_INJURIES if s in itype]
    if specified or hospitalised_over_24h:
        criteria = (
            f"Specified Injury — matched {', '.join(specified)}."
            if specified else
            "Specified Injury — hospital admission of 24 hours or more."
        )
        out.append(StatutoryObligation(
            UK, REGULATORS[UK], LEGAL_BASIS[UK],
            event="Specified Injury",
            criteria=criteria,
            notify_within_hours=IMMEDIATE, written_report_days=10,
        ))

    if dangerous_occurrence:
        out.append(StatutoryObligation(
            UK, REGULATORS[UK], LEGAL_BASIS[UK],
            event="Dangerous Occurrence",
            criteria="One of the 27 specified dangerous occurrences.",
            notify_within_hours=IMMEDIATE, written_report_days=10,
        ))

    # Over-7-day is measured in consecutive days unable to perform normal duties,
    # excluding the day of the accident. Only raise it when a Specified Injury
    # has not already been raised — the stricter obligation supersedes it.
    if days_away is not None and days_away > 7 and not out:
        out.append(StatutoryObligation(
            UK, REGULATORS[UK], LEGAL_BASIS[UK],
            event="Over-7-Day Injury",
            criteria=f"{days_away} consecutive days unable to perform normal duties (>7).",
            notify_within_hours=15 * 24,
        ))

    if occupational_disease:
        out.append(StatutoryObligation(
            UK, REGULATORS[UK], LEGAL_BASIS[UK],
            event="Occupational Disease",
            criteria="Schedule 3 occupational disease with written diagnosis.",
            notify_within_hours=10 * 24,
        ))

    return out


# ══════════════════════════════════════════════════════════════════════════════
# United States — OSHA 29 CFR 1904 · regulator: OSHA
#
#   Fatality                        within 8 hours
#   Inpatient hospitalisation       within 24 hours
#   Amputation / loss of an eye     within 24 hours
#   OSHA 300 Log recordable         annual log, not a notification
# ══════════════════════════════════════════════════════════════════════════════

_US_24H_INJURIES = ("amputation", "loss of an eye", "loss of eye", "eye loss")


def _us(
    fatality: bool,
    injury_type: Optional[str],
    days_away: Optional[int],
    hospitalised: bool,
    medical_treatment: bool,
    loss_of_consciousness: bool,
) -> List[StatutoryObligation]:
    out: List[StatutoryObligation] = []
    itype = (injury_type or "").strip().lower()

    if fatality:
        out.append(StatutoryObligation(
            US, REGULATORS[US], LEGAL_BASIS[US],
            event="Fatality (Severe)",
            criteria="Work-related fatality.",
            notify_within_hours=8,
        ))

    if hospitalised:
        out.append(StatutoryObligation(
            US, REGULATORS[US], LEGAL_BASIS[US],
            event="Hospitalisation",
            criteria="Inpatient hospitalisation of one or more workers.",
            notify_within_hours=24,
        ))

    matched = [s for s in _US_24H_INJURIES if s in itype]
    if matched:
        out.append(StatutoryObligation(
            US, REGULATORS[US], LEGAL_BASIS[US],
            event="Amputation / Eye Loss",
            criteria=f"Work-related {matched[0]}.",
            notify_within_hours=24,
        ))

    # OSHA 300 recordability. Not a phone-in notification — it is an entry on the
    # annual log — so it carries the year-end deadline rather than an hour clock.
    recordable = (
        fatality
        or hospitalised
        or medical_treatment
        or loss_of_consciousness
        or bool(matched)          # an amputation or eye loss is always recordable
        or (days_away is not None and days_away > 0)
    )
    if recordable:
        out.append(StatutoryObligation(
            US, REGULATORS[US], LEGAL_BASIS[US],
            event="OSHA 300 Log (Annual)",
            criteria=(
                "Recordable: days away, restricted work/transfer, medical treatment "
                "beyond first aid, loss of consciousness, or significant diagnosis."
            ),
            notify_within_hours=365 * 24,
            requires_human_authorisation=False,   # a log entry, not a submission
        ))

    return out


# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# UAE — Ministerial Decree No. 32 of 1982 · MOHRE
#
#   Fatality           police immediately + MOHRE within 24 hours
#   Work Injury        MOHRE within 48 hours, if unable to work 1+ day
#   Occupational Dis.  MOHRE on diagnosis
#   Major Construction OSHAD-SF (Abu Dhabi) / DCD (Dubai) immediately
# ══════════════════════════════════════════════════════════════════════════════

# Emirate-specific authorities for major construction incidents. `emirate` is
# supplied by the caller from the site record when it is known.
_UAE_LOCAL_AUTHORITY = {
    "abu dhabi": "OSHAD-SF (Abu Dhabi Occupational Safety and Health Centre)",
    "abudhabi": "OSHAD-SF (Abu Dhabi Occupational Safety and Health Centre)",
    "dubai": "DCD (Dubai Civil Defence)",
}


def _uae(fatality, days_away, occupational_disease, major_construction, emirate):
    out = []
    if fatality:
        out.append(StatutoryObligation(
            UAE, "Police + " + REGULATORS[UAE], LEGAL_BASIS[UAE],
            event="Fatality",
            criteria="Work-related fatality. Police notified immediately, MOHRE within 24 hours.",
            notify_within_hours=IMMEDIATE,
        ))
    if days_away is not None and days_away >= 1 and not fatality:
        out.append(StatutoryObligation(
            UAE, REGULATORS[UAE], LEGAL_BASIS[UAE],
            event="Work Injury Notification",
            criteria=f"Unable to work {days_away} day(s) beyond the day of injury.",
            notify_within_hours=48,
        ))
    if occupational_disease:
        out.append(StatutoryObligation(
            UAE, REGULATORS[UAE], LEGAL_BASIS[UAE],
            event="Occupational Disease",
            criteria="Disease from the prescribed list, notified on diagnosis.",
            notify_within_hours=IMMEDIATE,
        ))
    if major_construction:
        authority = _UAE_LOCAL_AUTHORITY.get((emirate or "").strip().lower())
        out.append(StatutoryObligation(
            UAE, authority or "Relevant local authority (emirate not set)", LEGAL_BASIS[UAE],
            event="Major Construction Incident",
            criteria="Collapse, explosion or fire at a construction site.",
            notify_within_hours=IMMEDIATE,
            encoded=bool(authority),   # without the emirate we cannot name the authority
        ))
    return out


# ══════════════════════════════════════════════════════════════════════════════
# KSA — Labour Law Art. 138 / OSH Regulations · HRSD + GOSI
#
#   Fatality        police immediately + HRSD within 24 h + GOSI mortality
#   Work Injury     HRSD within 48 h, GOSI claim filed simultaneously
#   Fire/Explosion  NFSC notification
#   Major Hazard    Royal Commission (Jubail, Yanbu) immediately
# ══════════════════════════════════════════════════════════════════════════════

def _ksa(fatality, days_away, medical_treatment, fire_or_explosion, royal_commission_site):
    out = []
    if fatality:
        out.append(StatutoryObligation(
            KSA, "Police + " + REGULATORS[KSA] + " + GOSI", LEGAL_BASIS[KSA],
            event="Fatality",
            criteria="Work fatality. Police immediately, HRSD within 24 hours, GOSI mortality notification.",
            notify_within_hours=IMMEDIATE,
        ))
    elif medical_treatment or (days_away is not None and days_away > 0):
        out.append(StatutoryObligation(
            KSA, REGULATORS[KSA] + " + GOSI", LEGAL_BASIS[KSA],
            event="Work Injury (Labour Law Art. 138)",
            criteria="Injury resulting in medical treatment, days lost or disability. "
                     "GOSI insurance claim filed simultaneously.",
            notify_within_hours=48,
        ))
    if fire_or_explosion:
        out.append(StatutoryObligation(
            KSA, "National Fire Safety Committee (NFSC)", LEGAL_BASIS[KSA],
            event="Reportable HSE Event — NFSC",
            criteria="Fire or explosive incident at an industrial facility.",
            notify_within_hours=IMMEDIATE,
        ))
    if royal_commission_site:
        out.append(StatutoryObligation(
            KSA, "Royal Commission EHS Authority (Jubail / Yanbu)", LEGAL_BASIS[KSA],
            event="Major Hazard Facility Incident",
            criteria="Incident at a facility subject to Royal Commission regulations.",
            notify_within_hours=IMMEDIATE,
        ))
    return out


# ══════════════════════════════════════════════════════════════════════════════
# Australia — Model WHS Act 2011 s.35-38 · state/territory regulator
#
#   All notifiable incidents: notify immediately by phone, written within 48 h.
#   Site preservation is a legal obligation after any notifiable incident.
# ══════════════════════════════════════════════════════════════════════════════

_AU_SERIOUS_INJURY = (
    "amputation", "serious head", "serious eye", "serious burn", "degloving",
    "scalping", "spinal", "loss of bodily function", "unconscious", "entrapment",
)

# State/territory regulator by site state, per Appendix A's "state/territory
# specific notification based on site location".
_AU_REGULATORS = {
    "nsw": "SafeWork NSW", "vic": "WorkSafe Victoria", "qld": "Workplace Health and Safety Queensland",
    "wa": "WorkSafe WA", "sa": "SafeWork SA", "tas": "WorkSafe Tasmania",
    "nt": "NT WorkSafe", "act": "WorkSafe ACT",
}


def _au(fatality, injury_type, hospitalised_over_24h, dangerous_incident, state):
    regulator = _AU_REGULATORS.get((state or "").strip().lower(), REGULATORS[AU])
    out = []
    itype = (injury_type or "").strip().lower()

    def add(event, criteria):
        out.append(StatutoryObligation(
            AU, regulator, LEGAL_BASIS[AU], event=event, criteria=criteria,
            notify_within_hours=IMMEDIATE, written_report_days=2,
        ))

    if fatality:
        add("Notifiable Incident — Death", "Death resulting from a work activity.")

    matched = [s for s in _AU_SERIOUS_INJURY if s in itype]
    if matched or hospitalised_over_24h:
        add(
            "Notifiable Incident — Serious Injury or Illness",
            f"Matched {', '.join(matched)}." if matched
            else "Hospitalisation exceeding 24 hours.",
        )

    if dangerous_incident:
        add(
            "Dangerous Incident",
            "Uncontrolled release, explosion or fire, electric shock, excavation "
            "collapse, or collapse of plant or structure.",
        )

    # Site preservation is a duty, not a notification — surfaced so the UI can
    # show it, and marked as needing no authorisation because nothing is filed.
    if out:
        out.append(StatutoryObligation(
            AU, regulator, LEGAL_BASIS[AU],
            event="Preservation of Incident Site",
            criteria="Do not disturb the site until an inspector attends or directs "
                     "otherwise, except to assist an injured person or make safe. "
                     "This is a legal obligation, not optional.",
            notify_within_hours=IMMEDIATE,
            requires_human_authorisation=False,
        ))
    return out


# ══════════════════════════════════════════════════════════════════════════════
# EU — Directive 89/391/EEC · Seveso III 2012/18/EU
#
#   Serious accident   national authority, timeframe varies by member state
#   Major accident     Seveso competent authority immediately, full report 1 year
# ══════════════════════════════════════════════════════════════════════════════

# Transposition differs per member state. Where we know the deadline we use it,
# otherwise we fall back to the directive's typical 24-72 h and say so.
_EU_MEMBER_AUTHORITY = {
    "IE": ("Health and Safety Authority (HSA), Ireland", 24),
    "DE": ("Deutsche Gesetzliche Unfallversicherung (DGUV), Germany", 72),
    "FR": ("Inspection du travail / CARSAT, France", 48),
    "NL": ("Nederlandse Arbeidsinspectie, Netherlands", 24),
    "PL": ("Panstwowa Inspekcja Pracy (PIP), Poland", 24),
}


def _eu(fatality, permanent_disability, significant_injury, seveso_major_accident, member_state):
    code = (member_state or "").strip().upper()
    authority, default_hours = _EU_MEMBER_AUTHORITY.get(
        code, (REGULATORS[EU] + (f" ({code})" if code else " — member state not set"), 72)
    )
    known = code in _EU_MEMBER_AUTHORITY
    out = []

    if fatality or permanent_disability or significant_injury:
        reason = ("Fatality." if fatality else
                  "Permanent disability." if permanent_disability else
                  "Significant injury.")
        out.append(StatutoryObligation(
            EU, authority, "Directive 89/391/EEC (as transposed)",
            event="Serious Accident (General OSH)",
            criteria=reason + (
                "" if known else
                " Member state not set — deadline defaulted to the directive's "
                "typical 72 h and must be confirmed against local transposition."
            ),
            notify_within_hours=IMMEDIATE if fatality else default_hours,
            encoded=known,
        ))

    if seveso_major_accident:
        out.append(StatutoryObligation(
            EU, authority, "Seveso III Directive 2012/18/EU",
            event="Major Accident (Seveso III)",
            criteria="Release of dangerous substances at an Upper- or Lower-Tier "
                     "Seveso site causing death, injury, or environmental/property damage. "
                     "Full report due within 1 year.",
            notify_within_hours=IMMEDIATE,
            written_report_days=365,
        ))
    return out


# ══════════════════════════════════════════════════════════════════════════════

def evaluate(
    jurisdiction: Optional[str],
    *,
    incident_at: Optional[datetime] = None,
    fatality: bool = False,
    injury_type: Optional[str] = None,
    days_away: Optional[int] = None,
    dangerous_occurrence: bool = False,
    hospitalised: bool = False,
    hospitalised_over_24h: bool = False,
    medical_treatment: bool = False,
    loss_of_consciousness: bool = False,
    occupational_disease: bool = False,
    # ── Jurisdiction-specific context, all optional ──────────────────────────
    permanent_disability: bool = False,
    fire_or_explosion: bool = False,
    major_construction: bool = False,
    seveso_major_accident: bool = False,
    royal_commission_site: bool = False,
    region: Optional[str] = None,     # emirate (UAE), state (AU), member state (EU)
) -> StatutoryResult:
    """Which statutory notifications does this incident trigger, and by when?

    `jurisdiction` is the site's jurisdiction (see the constants above). An
    unknown or missing jurisdiction returns not-reportable with an explanation —
    it never guesses UK.

    Every returned obligation requires human authorisation before submission,
    per Appendix A. Nothing here sends anything.
    """
    juris = (jurisdiction or "").strip().upper()

    if not juris:
        return StatutoryResult(
            reportable=False,
            explanation="No jurisdiction configured for this site — statutory reportability "
                        "cannot be determined. Set the site jurisdiction.",
        )

    if juris == UK:
        obligations = _uk(
            fatality, injury_type, days_away, dangerous_occurrence,
            hospitalised_over_24h, occupational_disease,
        )
    elif juris == US:
        obligations = _us(
            fatality, injury_type, days_away, hospitalised,
            medical_treatment, loss_of_consciousness,
        )
    elif juris == UAE:
        obligations = _uae(
            fatality, days_away, occupational_disease, major_construction, region,
        )
    elif juris == KSA:
        obligations = _ksa(
            fatality, days_away, medical_treatment, fire_or_explosion, royal_commission_site,
        )
    elif juris == AU:
        obligations = _au(
            fatality, injury_type, hospitalised_over_24h,
            dangerous_occurrence or fire_or_explosion, region,
        )
    elif juris == EU:
        obligations = _eu(
            fatality, permanent_disability,
            significant_injury=(hospitalised or medical_treatment or bool(days_away)),
            seveso_major_accident=seveso_major_accident, member_state=region,
        )
    else:
        return StatutoryResult(
            reportable=False,
            explanation=f"Jurisdiction {juris!r} is not in Appendix A.",
        )

    # Stamp the clocks now that we know which obligations fired.
    if incident_at is not None:
        for o in obligations:
            o.due_at = incident_at + timedelta(hours=o.notify_within_hours)
            if o.written_report_days is not None:
                o.written_due_at = incident_at + timedelta(days=o.written_report_days)

    if not obligations:
        return StatutoryResult(
            reportable=False,
            explanation=f"{juris}: no reportable threshold met.",
        )

    return StatutoryResult(
        reportable=True,
        obligations=obligations,
        explanation="; ".join(
            f"{o.event} ({'immediate' if o.notify_within_hours == 0 else f'{o.notify_within_hours}h'})"
            for o in obligations
        ),
    )
