"""The hierarchy of control, and why PPE-only is the one the system argues with.

Source: WF-01 "Hazard Flow and Risk Flow — Two Different Journeys", Rev 5.0.
The spec's own wording, on the five levels:

    1  Eliminate    remove the hazard entirely. Kills the risk permanently.
    2  Substitute   replace it with something less dangerous.
    3  Engineering  guard, isolate, ventilate. Works without anyone remembering.
    4  Administrative  procedures, training, signage. Depends on people complying.
    5  PPE          last line. Hazard fully intact; only a barrier between it
                    and a person.

And the consequence it draws: "Levels 1 and 2 remove the hazard. Levels 3 to 5
only reduce the risk — the hazard is still there, waiting for the control to
fail. This is why the system flags any PPE-only control for mandatory review,
and why heavy PPE reliance lowers the Control Integrity domain of the safety
score."

Both of those were written down and neither was built. A control set to PPE was
accepted in silence on the hazard register and on a Flow B assessment alike,
which makes the weakest control in the hierarchy the easiest one to choose.
"""
from typing import Optional

ELIMINATE = "eliminate"
SUBSTITUTE = "substitute"
ENGINEERING = "engineering"
ADMINISTRATIVE = "administrative"
PPE = "ppe"

# Strongest first, which is the order they should be offered in.
HIERARCHY = (ELIMINATE, SUBSTITUTE, ENGINEERING, ADMINISTRATIVE, PPE)

RANK = {name: i + 1 for i, name in enumerate(HIERARCHY)}

LABEL = {
    ELIMINATE: "Eliminate",
    SUBSTITUTE: "Substitute",
    ENGINEERING: "Engineering",
    ADMINISTRATIVE: "Administrative",
    PPE: "PPE",
}

# Levels 1 and 2 remove the hazard; 3 to 5 leave it in place.
REMOVES_HAZARD = (ELIMINATE, SUBSTITUTE)

PPE_ONLY_NOTICE = (
    "PPE is the last line of defence — the hazard is fully intact and only a "
    "barrier stands between it and a person. This control needs review: "
    "eliminate, substitute or engineer the hazard out if it can be done."
)


def normalise(value: Optional[str]) -> Optional[str]:
    v = (value or "").strip().lower().replace(" ", "_")
    return v if v in RANK else None


def is_ppe_only(value: Optional[str]) -> bool:
    """True when the only thing between the hazard and a person is PPE."""
    return normalise(value) == PPE


def removes_hazard(value: Optional[str]) -> bool:
    return normalise(value) in REMOVES_HAZARD


def review_notice(value: Optional[str]) -> Optional[str]:
    """The mandatory review notice the spec attaches, or None."""
    return PPE_ONLY_NOTICE if is_ppe_only(value) else None


def ppe_reliance(hierarchies) -> float:
    """Share of controls that are PPE-only, 0.0 to 100.0.

    Feeds the Control Integrity domain of the safety performance score. The
    spec: "heavy PPE reliance lowers the Control Integrity domain". A site
    whose controls are mostly PPE has not controlled anything — it has issued
    equipment and hoped, and a score that cannot tell that apart from a site
    that engineered its hazards out is not measuring control integrity.
    """
    named = [normalise(h) for h in hierarchies]
    named = [h for h in named if h]
    if not named:
        return 0.0
    return round(100.0 * sum(1 for h in named if h == PPE) / len(named), 2)
