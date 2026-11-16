"""Impact KPIs: eight weighted criteria scored 0-5 per regulation, combined into an impact score of 0-100.

    score = sum(weight * criterion_score / 5)       (weights total 100)
    band  = High >= BANDS["High"], Medium >= BANDS["Medium"], else Low

Each criterion is first computed from the regulation's data (`auto_scores`). Three come from facts the pipeline
extracted (basis "data"); five are estimates from the regulation's topics (basis "estimate"), because what they
measure depends on the company's products, not on the regulation text. A score the team sets
(table regulation_kpi_scores, migration 0025) replaces the computed one (basis "team"). 0 means not applicable.

The weights, the bands and the rules below are the one definition: the API, the portal and the tests use them.
"""

from __future__ import annotations

from datetime import date

# key, label, weight (%), what is assessed
CRITERIA: list[tuple[str, str, int, str]] = [
    (
        "regulatory",
        "Regulatory / compliance impact",
        20,
        "Mandatory provisions, approval or certification consequences",
    ),
    ("functional_safety", "Functional safety impact", 20, "Safety goals, hazards, ASIL-related implications"),
    ("cybersecurity", "Cybersecurity impact", 15, "Vulnerabilities, authentication, encryption, security controls"),
    (
        "protocol_interface",
        "Protocol / interface compatibility",
        15,
        "Backward compatibility, message structure, API or bus changes",
    ),
    (
        "architecture",
        "Architecture / implementation effort",
        10,
        "ECU software, middleware, BSW, drivers or hardware changes",
    ),
    ("verification", "Verification and validation effort", 10, "Regression, interoperability, SIL/HIL or retesting"),
    ("exposure", "Product / platform exposure", 5, "Number and criticality of affected products, variants, markets"),
    ("urgency", "Schedule / deployment urgency", 5, "Time until applicable deadline, launch or committed deployment"),
]
KEYS = [c[0] for c in CRITERIA]
WEIGHTS = {c[0]: c[2] for c in CRITERIA}
BANDS = {"High": 60, "Medium": 30}  # score thresholds; below Medium is Low
assert sum(WEIGHTS.values()) == 100

FROM_DATA = {"regulatory", "exposure", "urgency"}  # the rest are estimates from the topics

ADMIN_DOMAINS = {"registration", "number_plates", "licensing", "permit", "fees", "fitness_puc", "recall_scrappage"}
SAFETY_DOMAINS = {"braking", "safety_equipment"}
ELECTRONIC_DOMAINS = {"cybersecurity", "tracking_its", "charging", "battery"}
DRAFTS = ("NOTIFICATION_DRAFT", "AIS_DRAFT")


def _technical(r: dict) -> bool:
    return (
        r.get("nature") == "technical"
        or (r.get("doc_class") or "").startswith(("AIS_", "TAP_"))
        or r.get("doc_class") in ("TIS_STANDARD", "MY_SUBSIDIARY_LEGISLATION")
    )


def auto_scores(r: dict, scope: list[str], today: date | None = None) -> dict[str, tuple[int, str]]:
    """criterion -> (score 0-5, reason) from a regulation row (portal REG_SQL: domains, nature, doc_class,
    doc_status, next_obligation, reapproval, open_mandates, vehicle_categories). scope: the country's in-scope
    vehicle categories."""
    today = today or date.today()
    doms = set(r.get("domains") or [])
    technical = _technical(r)
    admin = not technical and (r.get("nature") == "administrative" or bool(doms & ADMIN_DOMAINS))
    draft = r.get("doc_class") in DRAFTS or r.get("doc_status") == "draft"
    upcoming = r.get("next_obligation")
    out: dict[str, tuple[int, str]] = {}

    # regulatory / compliance: is it binding, and does it change what has to be approved?
    if draft:
        out["regulatory"] = (2, "draft: proposed, not yet binding")
    elif technical and (upcoming or r.get("reapproval")):
        out["regulatory"] = (5, "binding technical requirement with an obligation to come or a re-approval")
    elif technical and (r.get("open_mandates") or "type_approval" in doms):
        out["regulatory"] = (4, "binding technical requirement (type approval)")
    elif technical:
        out["regulatory"] = (3, "technical standard or rule")
    elif admin:
        out["regulatory"] = (1, "administrative (registration, licences, fees)")
    else:
        out["regulatory"] = (2, "general provision")

    # functional safety: from the topics
    if doms & SAFETY_DOMAINS:
        out["functional_safety"] = (5, "braking or safety equipment")
    elif "lighting" in doms:
        out["functional_safety"] = (4, "lighting and signalling")
    elif doms & (ELECTRONIC_DOMAINS | {"ev_alt_fuel"}):
        out["functional_safety"] = (3, "electrical / electronic systems")
    elif technical:
        out["functional_safety"] = (1, "technical, no safety topic")
    else:
        out["functional_safety"] = (0, "not applicable")

    # cybersecurity
    if "cybersecurity" in doms:
        out["cybersecurity"] = (5, "cybersecurity requirement")
    elif "tracking_its" in doms:
        out["cybersecurity"] = (3, "connected / tracking systems")
    elif "charging" in doms:
        out["cybersecurity"] = (2, "charging communication")
    else:
        out["cybersecurity"] = (0, "not applicable")

    # protocol / interface compatibility
    if "tracking_its" in doms:
        out["protocol_interface"] = (4, "telematics / ITS interfaces")
    elif doms & {"charging", "cybersecurity"}:
        out["protocol_interface"] = (3, "charging or secure communication interfaces")
    elif "emission" in doms:
        out["protocol_interface"] = (1, "diagnostics (OBD) may change")
    else:
        out["protocol_interface"] = (0, "not applicable")

    # architecture / implementation effort
    if doms & ELECTRONIC_DOMAINS:
        out["architecture"] = (3, "electronic systems: software or hardware changes likely")
    elif doms & (SAFETY_DOMAINS | {"lighting", "emission", "ev_alt_fuel"}):
        out["architecture"] = (2, "vehicle systems: component changes likely")
    elif technical:
        out["architecture"] = (1, "technical, small changes expected")
    else:
        out["architecture"] = (0, "not applicable")

    # verification and validation effort
    if technical and r.get("reapproval"):
        out["verification"] = (4, "revision needing re-approval: retesting")
    elif technical and upcoming:
        out["verification"] = (3, "new obligation: testing to its standard")
    elif technical:
        out["verification"] = (2, "technical: regression testing")
    else:
        out["verification"] = (0, "not applicable")

    # product / platform exposure: in-scope vehicle categories it covers
    cats = set(r.get("vehicle_categories") or [])
    covered = cats & set(scope)
    if "ALL" in cats:
        out["exposure"] = (5, "all vehicle categories")
    elif len(covered) >= 3:
        out["exposure"] = (4, f"{len(covered)} in-scope categories")
    elif len(covered) == 2:
        out["exposure"] = (3, "2 in-scope categories")
    elif covered:
        out["exposure"] = (2, "1 in-scope category")
    else:
        out["exposure"] = (0, "no in-scope category")

    # schedule / deployment urgency: time to the next obligation
    if upcoming:
        days = (upcoming - today).days
        score = 5 if days <= 180 else 4 if days <= 365 else 3 if days <= 730 else 2
        out["urgency"] = (score, f"next obligation in {days} days ({upcoming:%d %b %Y})")
    else:
        out["urgency"] = (0, "no obligation to come")
    return out


def combine(auto: dict[str, tuple[int, str]], team: dict[str, dict] | None = None) -> dict:
    """The criteria (team score over computed), the weighted score 0-100 and its band."""
    team = team or {}
    criteria, total = [], 0.0
    for key, label, weight, what in CRITERIA:
        if key in team:
            score, reason, basis = team[key]["score"], team[key].get("note") or "set by the team", "team"
        else:
            score, reason = auto[key]
            basis = "data" if key in FROM_DATA else "estimate"
        total += weight * score / 5
        criteria.append(
            {
                "key": key,
                "label": label,
                "weight": weight,
                "what": what,
                "score": score,
                "basis": basis,
                "reason": reason,
                "points": round(weight * score / 5, 1),
            }
        )
    score = round(total)
    band = "High" if score >= BANDS["High"] else "Medium" if score >= BANDS["Medium"] else "Low"
    return {"score": score, "band": band, "criteria": criteria}
