"""Patient clinical context for ML narratives (history, pathology, doctor feedback)."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from app.services.measurement_service import list_latest_doctor_feedback
from app.services.user_service import get_user_profile

# (regex pattern, condition key, label FR)
_CONDITION_PATTERNS: Tuple[Tuple[str, str, str], ...] = (
    (r"hypertension|\bhta\b|tension art[ée]rielle", "hypertension", "hypertension"),
    (r"bpco|copd|emphys[èe]me|bronchopneumopathie", "bpco", "BPCO"),
    (r"insuffisance cardiaque|\bicc\b|heart failure", "icc", "insuffisance cardiaque"),
    (r"diab[èe]te|diabetic", "diabete", "diabète"),
    (r"anticoagulant|\bavk\b|coumadin|eliquis|xarelto|pr[ée]vent|apixaban|rivaroxaban", "anticoagulation", "anticoagulation"),
    (r"insuffisance r[ée]nale|\birc\b|dialyse", "irc", "insuffisance rénale"),
    (r"arythmie|fibrillation|\bfa\b|flutter", "arythmie", "arythmie cardiaque"),
    (r"asthme", "asthme", "asthme"),
    (r"pacemaker|stimulateur", "pacemaker", "pacemaker"),
    (r"post[- ]?op[ée]|chirurgie r[ée]cente|op[ée]ration r[ée]cente", "post_op", "post-opératoire récent"),
    (r"pneumopathie|pneumonie", "pneumopathie", "pneumopathie"),
    (r"ob[ée]sit[ée]", "obesite", "obésité"),
)

_RECENT_PROFILE_DAYS = 14
_RECENT_FEEDBACK_DAYS = 21


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _truncate(text: str, max_len: int) -> str:
    text = _normalize_text(text)
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def _parse_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _is_within_days(value: Any, days: int) -> bool:
    dt = _parse_datetime(value)
    if dt is None:
        return False
    return datetime.now(timezone.utc) - dt <= timedelta(days=days)


def extract_conditions_from_text(text: str) -> List[Dict[str, str]]:
    """Detect known conditions from any free-text medical content."""
    blob = _normalize_text(text).lower()
    if not blob:
        return []
    found: Dict[str, Dict[str, str]] = {}
    for pattern, key, label in _CONDITION_PATTERNS:
        if re.search(pattern, blob, re.IGNORECASE):
            found[key] = {"key": key, "label": label}
    return list(found.values())


def extract_conditions_from_history(medical_history: str, pathology: Optional[str] = None) -> List[Dict[str, str]]:
    """Detect known conditions from patient-declared history and pathology field."""
    blob = " ".join(filter(None, [_normalize_text(medical_history), _normalize_text(pathology)]))
    return extract_conditions_from_text(blob)


def _conditions_from_feedbacks(feedbacks: List[Dict[str, Any]]) -> Tuple[List[Dict[str, str]], bool]:
    """Extract conditions mentioned in doctor messages/recommendations."""
    parts: List[str] = []
    has_recent = False
    for fb in feedbacks:
        parts.append(_normalize_text(fb.get("message")))
        parts.append(_normalize_text(fb.get("recommendation")))
        if _is_within_days(fb.get("created_at"), _RECENT_FEEDBACK_DAYS):
            has_recent = True
    blob = " ".join(p for p in parts if p)
    return extract_conditions_from_text(blob), has_recent


def _merge_conditions(
    patient_conditions: List[Dict[str, str]],
    doctor_conditions: List[Dict[str, str]],
) -> List[Dict[str, Any]]:
    """Merge conditions with source tracking (patient / doctor / both)."""
    merged: Dict[str, Dict[str, Any]] = {}
    for cond in patient_conditions:
        key = cond["key"]
        merged[key] = {"key": key, "label": cond["label"], "sources": {"patient"}}
    for cond in doctor_conditions:
        key = cond["key"]
        if key in merged:
            merged[key]["sources"].add("doctor")
        else:
            merged[key] = {"key": key, "label": cond["label"], "sources": {"doctor"}}
    return list(merged.values())


def _doctor_only_labels(conditions: List[Dict[str, Any]]) -> List[str]:
    return [
        c["label"] for c in conditions
        if c.get("sources") == {"doctor"}
    ]


def _recent_change_phrases(
    ctx: Dict[str, Any],
    *,
    audience: str,
) -> List[str]:
    """Natural-language notes when dossier or doctor guidance recently changed."""
    lines: List[str] = []
    doctor_only = ctx.get("doctor_only_labels") or []
    profile_recent = bool(ctx.get("profile_recently_updated"))
    feedback_recent = bool(ctx.get("has_recent_doctor_feedback"))

    if doctor_only and feedback_recent:
        joined = ", ".join(doctor_only[:3])
        if audience == "clinical":
            lines.append(
                f"Mise à jour récente du suivi : le médecin a précisé {joined} "
                f"({'non mentionné' if len(doctor_only) == 1 else 'non mentionnés'} dans l'historique patient déclaré). "
                "Les interprétations ci-dessous en tiennent compte."
            )
        elif audience == "caregiver":
            lines.append(
                f"Le médecin a récemment précisé que votre proche présente {joined}. "
                "Ce résumé en tient compte pour interpréter les mesures."
            )
        else:
            lines.append(
                f"Votre médecin a récemment indiqué que vous avez {joined}. "
                "Nous intégrons cette information à l'analyse de vos constantes."
            )
    elif doctor_only:
        joined = ", ".join(doctor_only[:3])
        if audience == "clinical":
            lines.append(
                f"Élément(s) signalé(s) par le médecin et absent(s) du questionnaire patient : {joined}."
            )
        elif audience == "caregiver":
            lines.append(
                f"Le dossier médical mentionne {joined} d'après les commentaires du médecin."
            )
        else:
            lines.append(
                f"Votre médecin a signalé {joined} ; nous l'avons pris en compte pour ce résumé."
            )

    if profile_recent and not doctor_only:
        if audience == "clinical":
            lines.append(
                "Historique patient mis à jour récemment dans le questionnaire : "
                "recommandations recalculées sur la base du dossier actuel."
            )
        elif audience == "caregiver":
            lines.append(
                "L'historique médical de votre proche a été mis à jour récemment ; "
                "ce résumé reflète ces informations."
            )
        else:
            lines.append(
                "Vous avez récemment mis à jour votre historique médical ; "
                "ce résumé en tient compte."
            )
    elif profile_recent and doctor_only:
        if audience == "clinical":
            lines.append("Questionnaire patient actualisé récemment.")
        elif audience == "patient":
            lines.append("Votre profil médical a aussi été actualisé récemment.")

    return lines[:2]


def _latest_vital_snapshot(analysis: Dict[str, Any]) -> Dict[str, Optional[float]]:
    out: Dict[str, Optional[float]] = {"heart_rate": None, "spo2": None, "temperature": None}
    vitals = analysis.get("vitals") or {}
    for feat in out:
        info = vitals.get(feat) or {}
        if info.get("status") != "ok":
            continue
        series = info.get("series") or []
        if series:
            try:
                out[feat] = float(series[-1]["value"])
                continue
            except (TypeError, ValueError, KeyError, IndexError):
                pass
        stats = info.get("statistics") or {}
        mean_val = stats.get("mean")
        if mean_val is not None:
            try:
                out[feat] = float(mean_val)
            except (TypeError, ValueError):
                pass
    return out


def _condition_cross_insights(
    conditions: List[Dict[str, Any]],
    analysis: Dict[str, Any],
    *,
    audience: str,
) -> List[str]:
    """Generate measure × history cross-insights adapted to audience."""
    if not conditions or analysis.get("status") == "insufficient_data":
        return []
    keys = {c["key"] for c in conditions}
    vitals = _latest_vital_snapshot(analysis)
    hr, spo2, temp = vitals.get("heart_rate"), vitals.get("spo2"), vitals.get("temperature")
    lines: List[str] = []

    if "bpco" in keys or "asthme" in keys:
        resp_label = "BPCO" if "bpco" in keys else "asthme"
        if spo2 is not None:
            if spo2 < 88:
                if audience == "clinical":
                    lines.append(
                        f"SpO₂ basse ({spo2:.0f} %) chez un patient {resp_label} : évaluer la décompensation "
                        "respiratoire et l'observance du traitement de fond."
                    )
                elif audience == "caregiver":
                    lines.append(
                        f"L'oxygène est bas ({spo2:.0f} %) alors que votre proche a une {resp_label} : "
                        "contactez l'équipe soignante si l'essoufflement augmente."
                    )
                else:
                    lines.append(
                        f"Votre taux d'oxygène est bas ({spo2:.0f} %) et vous avez une {resp_label} : "
                        "prévenez votre médecin si vous êtes plus essoufflé que d'habitude."
                    )
            elif spo2 < 92:
                if audience == "clinical":
                    lines.append(
                        f"SpO₂ modérée ({spo2:.0f} %) compatible avec un terrain {resp_label} ; "
                        "interpréter la tendance plutôt qu'une valeur isolée."
                    )
                elif audience == "patient":
                    lines.append(
                        f"Votre oxygène ({spo2:.0f} %) peut être plus bas que la moyenne à cause de votre {resp_label} ; "
                        "surveillez surtout si cela baisse encore ou si l'essoufflement augmente."
                    )

    if "icc" in keys:
        if spo2 is not None and spo2 < 92 and hr is not None and hr > 100:
            if audience == "clinical":
                lines.append(
                    "Association SpO₂ basse et tachycardie chez patient IC : évoquer une décompensation "
                    "cardiaque et rechercher prise de poids, œdèmes, orthopnée."
                )
            elif audience == "caregiver":
                lines.append(
                    "Oxygène bas et pouls élevé chez votre proche avec insuffisance cardiaque : "
                    "surveillez l'essoufflement, les gonflements et contactez le médecin si cela empire."
                )
            else:
                lines.append(
                    "Votre oxygène est bas et votre pouls élevé : avec votre insuffisance cardiaque, "
                    "contactez votre médecin si vous ressentez plus d'essoufflement ou de fatigue."
                )

    if "hypertension" in keys and hr is not None and hr > 110:
        if audience == "clinical":
            lines.append(
                f"Tachycardie ({hr:.0f} bpm) sur terrain hypertendu : vérifier observance antihypertenseur, "
                "douleur, anxiété ou déshydratation."
            )
        elif audience == "patient":
            lines.append(
                f"Votre pouls est un peu élevé ({hr:.0f} bpm) : avec votre hypertension, "
                "vérifiez que vous avez bien pris vos traitements et contactez votre médecin si cela persiste."
            )

    if "anticoagulation" in keys and temp is not None and temp > 38.0:
        if audience == "clinical":
            lines.append(
                f"Fièvre ({temp:.1f} °C) sous anticoagulation : surveiller signes hémorragiques "
                "et interactions médicamenteuses en cas de nouvelle prescription."
            )
        elif audience == "patient":
            lines.append(
                "Vous avez de la fièvre et prenez un anticoagulant : signalez tout saignement inhabituel à votre médecin."
            )

    if "arythmie" in keys and hr is not None and (hr > 120 or hr < 50):
        if audience == "clinical":
            lines.append(
                f"Fréquence cardiaque {hr:.0f} bpm avec antécédent d'arythmie : contrôler le rythme "
                "et l'observance du traitement antiarythmique."
            )
        elif audience == "patient":
            lines.append(
                f"Votre pouls ({hr:.0f} bpm) est inhabituel pour vous avec votre arythmie : "
                "contactez votre médecin si vous ressentez palpitations ou malaise."
            )

    if "diabete" in keys and temp is not None and temp > 38.0:
        if audience == "clinical":
            lines.append(
                f"Fièvre ({temp:.1f} °C) chez patient diabétique : contrôler la glycémie et rechercher "
                "une origine infectieuse."
            )
        elif audience == "patient":
            lines.append(
                "Vous avez de la fièvre : avec votre diabète, surveillez aussi votre glycémie et contactez votre médecin si besoin."
            )

    return lines[:3]


def _doctor_feedback_insights(
    feedbacks: List[Dict[str, Any]],
    known_labels: List[str],
    *,
    audience: str,
) -> Tuple[List[str], Optional[str]]:
    """Extract recent doctor guidance, avoiding redundancy with condition labels already cited."""
    if not feedbacks:
        return [], None

    active = [
        fb for fb in feedbacks
        if str(fb.get("status") or "").lower() not in ("resolved",)
    ] or feedbacks[:2]

    snippets: List[str] = []
    action_hint: Optional[str] = None
    known_lower = " ".join(known_labels).lower()

    for fb in active[:3]:
        msg = _normalize_text(fb.get("message"))
        rec = _normalize_text(fb.get("recommendation"))
        is_recent = _is_within_days(fb.get("created_at"), _RECENT_FEEDBACK_DAYS)
        recent_tag = " (récent)" if is_recent else ""

        if not msg and not rec:
            continue

        # Skip message if it only repeats conditions already in intro
        msg_adds_context = bool(msg) and not all(
            lbl.lower() in msg.lower() for lbl in known_labels[:2]
        ) if known_labels else bool(msg)

        if audience == "clinical":
            if msg and msg_adds_context:
                snippets.append(f"Commentaire médecin{recent_tag} : « {_truncate(msg, 180)} »")
            elif msg:
                snippets.append(f"Consigne médicale{recent_tag} : « {_truncate(msg, 180)} »")
            if rec:
                action_hint = action_hint or _truncate(rec, 220)
        elif audience == "caregiver":
            if msg:
                prefix = "Le médecin vient de préciser" if is_recent else "Le médecin a indiqué"
                snippets.append(f"{prefix} : « {_truncate(msg, 160)} »")
            if rec and not action_hint:
                action_hint = _truncate(rec, 200)
        else:
            if msg:
                prefix = "Votre médecin vient de vous dire" if is_recent else "Votre médecin vous a conseillé"
                snippets.append(f"{prefix} : « {_truncate(msg, 160)} »")
            if rec and not action_hint:
                action_hint = _truncate(rec, 200)

    return snippets[:2], action_hint


def build_patient_clinical_context(
    profile: Optional[Dict[str, Any]],
    feedbacks: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Structured context from profile questionnaire and doctor comments."""
    profile = profile or {}
    feedbacks = feedbacks or []
    medical_history = _normalize_text(profile.get("medical_history"))
    pathology = _normalize_text(profile.get("pathology"))

    patient_conditions = extract_conditions_from_history(medical_history, pathology)
    doctor_conditions, has_recent_feedback = _conditions_from_feedbacks(feedbacks)
    conditions = _merge_conditions(patient_conditions, doctor_conditions)
    condition_labels = [c["label"] for c in conditions]
    doctor_only = _doctor_only_labels(conditions)

    profile_recently_updated = bool(
        medical_history and _is_within_days(profile.get("updated_at"), _RECENT_PROFILE_DAYS)
    )

    ctx: Dict[str, Any] = {
        "medical_history_excerpt": _truncate(medical_history, 320) if medical_history else None,
        "pathology": pathology or None,
        "conditions": conditions,
        "condition_labels": condition_labels,
        "doctor_only_labels": doctor_only,
        "profile_recently_updated": profile_recently_updated,
        "has_recent_doctor_feedback": has_recent_feedback,
        "age": profile.get("age"),
        "sex": profile.get("sex"),
        "profile_updated_at": profile.get("updated_at"),
        "recent_doctor_feedback": feedbacks[:5],
    }
    return ctx


def load_patient_clinical_context(patient_user_id_auth: str, feedback_limit: int = 5) -> Dict[str, Any]:
    """Load fresh profile + recent doctor feedback for one patient (always current)."""
    profile = get_user_profile(patient_user_id_auth)
    feedbacks = list_latest_doctor_feedback(patient_user_id_auth, limit=feedback_limit)
    return build_patient_clinical_context(profile, feedbacks)


def _context_intro_clinical(ctx: Dict[str, Any]) -> Optional[str]:
    parts: List[str] = []
    labels = ctx.get("condition_labels") or []
    if labels:
        parts.append("Antécédents et suivi : " + ", ".join(labels) + ".")
    excerpt = ctx.get("medical_history_excerpt")
    if excerpt and not labels:
        parts.append(f"Historique déclaré : {excerpt}")
    elif excerpt and labels:
        parts.append(f"Détail questionnaire : {excerpt}")
    pathology = ctx.get("pathology")
    if pathology and pathology.lower() not in " ".join(labels).lower():
        parts.append(f"Pathologie suivie : {pathology}.")
    if not parts:
        return None
    return "Contexte patient - " + " ".join(parts)


def _context_intro_lay(ctx: Dict[str, Any], *, caregiver: bool = False) -> Optional[str]:
    labels = ctx.get("condition_labels") or []
    if not labels and not ctx.get("medical_history_excerpt"):
        return None
    if caregiver:
        if labels:
            return (
                "Pour interpréter les mesures de votre proche, son dossier indique : "
                + ", ".join(labels) + "."
            )
        return "Le dossier médical de votre proche guide l'interprétation de ces mesures."
    if labels:
        return (
            "Pour interpréter vos mesures, nous tenons compte de votre dossier : "
            + ", ".join(labels) + "."
        )
    return "Nous tenons compte des informations que vous avez renseignées dans votre profil médical."


def enrich_narrative_summary(
    summary: Dict[str, Any],
    analysis: Dict[str, Any],
    clinical_context: Optional[Dict[str, Any]],
    *,
    audience: str,
) -> Dict[str, Any]:
    """
    Enrich ML narrative with patient history, doctor feedback and measure cross-insights.
    audience: clinical | patient | caregiver
    """
    if not clinical_context or not summary:
        return summary

    ctx = clinical_context
    paragraphs: List[str] = []

    update_lines = _recent_change_phrases(ctx, audience=audience)
    paragraphs.extend(update_lines)

    if audience == "clinical":
        intro = _context_intro_clinical(ctx)
    else:
        intro = _context_intro_lay(ctx, caregiver=(audience == "caregiver"))

    if intro:
        paragraphs.append(intro)

    cross = _condition_cross_insights(ctx.get("conditions") or [], analysis, audience=audience)
    paragraphs.extend(cross)

    fb_snippets, fb_action = _doctor_feedback_insights(
        ctx.get("recent_doctor_feedback") or [],
        ctx.get("condition_labels") or [],
        audience=audience,
    )
    paragraphs.extend(fb_snippets)

    base_text = _normalize_text(summary.get("text"))
    if paragraphs:
        enriched_text = "\n\n".join(paragraphs + ([base_text] if base_text else []))
    else:
        enriched_text = base_text

    action = _normalize_text(summary.get("recommended_action"))
    if fb_action:
        if audience == "clinical":
            if action:
                action = f"{action} Consigne médicale en cours : {fb_action}"
            else:
                action = fb_action
        else:
            if action:
                action = f"{action} Rappel du suivi médical : {fb_action}"
            else:
                action = fb_action
    elif cross and audience == "clinical" and action:
        labels = ctx.get("condition_labels") or []
        if labels:
            action = f"{action} Contextualiser avec le dossier ({', '.join(labels)})."

    out = dict(summary)
    out["text"] = enriched_text
    if action:
        out["recommended_action"] = action
    if paragraphs or cross or fb_snippets:
        out["context_enriched"] = True
        out["context_conditions"] = ctx.get("condition_labels") or []
        if update_lines or ctx.get("profile_recently_updated") or ctx.get("has_recent_doctor_feedback"):
            out["context_recently_updated"] = True
    return out
