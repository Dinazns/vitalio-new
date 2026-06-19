"""Weekly vitals narrative helpers."""
from typing import Any, Dict, List, Optional, Tuple

from app.api.helpers.patient_clinical_context import enrich_narrative_summary


def weekly_summary_max_severity(analysis: Dict[str, Any]) -> int:
    """Highest severity from point anomalies, drift alerts, and per-measurement ML levels."""
    rank = {"critical": 3, "warning": 2, "mild": 1, "moderate": 2, "negligible": 0, "normal": 0, "strong": 3}
    max_s = 0
    for feat in ("heart_rate", "spo2", "temperature"):
        info = (analysis.get("vitals") or {}).get(feat) or {}
        if info.get("status") != "ok":
            continue
        for ap in info.get("anomalous_points") or []:
            max_s = max(max_s, rank.get(str(ap.get("severity", "")), 0))
        for alert in info.get("clinical_alerts") or []:
            max_s = max(max_s, rank.get(str(alert.get("severity", "")), 0))
    for p in analysis.get("timeline") or []:
        if p.get("ml_level") == "critical":
            max_s = max(max_s, 3)
        elif p.get("ml_level") == "warning":
            max_s = max(max_s, 2)
    return max_s


def weekly_risk_bundle(max_severity: int) -> Tuple[str, str, str]:
    """risk_level, recommended_action (clinical), recommended_action (plain language for patients)."""
    if max_severity >= 3:
        return (
            "high",
            "Évaluation clinique urgente : recontacter le patient, vérifier les symptômes "
            "(dyspnée, douleur thoracique, confusion) et envisager le 15 en cas de détresse aiguë.",
            "Consultez votre médecin ou un professionnel de santé pour interpréter ces variations. "
            "En cas de malaise aiguë (douleur, essoufflement), appelez le 15.",
        )
    if max_severity >= 2:
        return (
            "moderate",
            "Surveillance renforcée : contrôler l'évolution sur 24–48 h et recontacter le patient "
            "si les anomalies persistent ou s'accompagnent de symptômes.",
            "Poursuivez le suivi à domicile. Si l'inquiétude ou des symptômes durent plus de quelques jours, contactez votre médecin ou votre infirmier.",
        )
    if max_severity >= 1:
        return (
            "low",
            "Poursuivre la surveillance habituelle ; réévaluer si aggravation ou nouveaux symptômes.",
            "Continuez vos mesures comme d'habitude. Prévenez la personne qui s'occupe de vous en cas de changement net.",
        )
    return (
        "minimal",
        "Poursuivre le suivi habituel ; pas d'action immédiate identifiée.",
        "Rien de particulier à changer si vous vous sentez bien. Continuez simplement à enregistrer vos relevés.",
    )


def period_intro_phrase(analysis: Dict[str, Any]) -> Optional[Tuple[int, str]]:
    n_meas = analysis.get("n_measurements", 0)
    span_h = analysis.get("time_span_hours")
    if not n_meas or span_h is None:
        return None
    if span_h < 24:
        period_txt = f"environ {max(1, int(round(span_h)) or 1)} heure(s)"
    else:
        period_txt = f"environ {max(span_h / 24.0, 0.1):.1f} jour(s)"
    return (n_meas, period_txt)


_LABELS_FR = {"heart_rate": "Fréquence cardiaque", "spo2": "SpO₂", "temperature": "Température"}
_FEAT_ORDER = ("heart_rate", "spo2", "temperature")
_ALERT_SEVERITY = {"critical": 3, "warning": 2, "mild": 1, "moderate": 2, "strong": 3}


def _latest_vital_value(info: Dict[str, Any]) -> Optional[float]:
    series = info.get("series") or []
    if series:
        try:
            return float(series[-1]["value"])
        except (TypeError, ValueError, KeyError, IndexError):
            pass
    stats = info.get("statistics") or {}
    mean_val = stats.get("mean")
    if mean_val is not None:
        try:
            return float(mean_val)
        except (TypeError, ValueError):
            pass
    return None


def _append_finding(
    findings: List[Dict[str, Any]],
    seen: set,
    *,
    severity: int,
    headline: str,
    action_hint: str,
    feat: str,
) -> None:
    key = (feat, headline)
    if key in seen:
        return
    seen.add(key)
    findings.append({
        "severity": severity,
        "headline": headline,
        "action_hint": action_hint,
        "feat": feat,
    })


def _collect_vital_extreme_findings(info: Dict[str, Any], feat: str) -> List[Dict[str, Any]]:
    """Detect named pathologies from min/max/latest values on the period."""
    findings: List[Dict[str, Any]] = []
    seen: set = set()
    stats = info.get("statistics") or {}
    mn = stats.get("min")
    mx = stats.get("max")
    last = _latest_vital_value(info)
    unit = info.get("unit", "")

    def fval(v: Any) -> Optional[float]:
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    mn_f, mx_f, last_f = fval(mn), fval(mx), fval(last)

    if feat == "spo2":
        low = min(v for v in (mn_f, last_f) if v is not None) if (mn_f is not None or last_f is not None) else None
        if low is not None and low < 88:
            _append_finding(
                findings, seen, severity=3, feat=feat,
                headline=f"Hypoxémie sévère (SpO₂ min. {low:.0f} %)",
                action_hint="Oxygénothérapie et évaluation urgente ; appeler le 15 si détresse respiratoire",
            )
        elif low is not None and low < 92:
            _append_finding(
                findings, seen, severity=2, feat=feat,
                headline=f"Hypoxémie modérée (SpO₂ min. {low:.0f} %)",
                action_hint="Surveillance rapprochée de la SpO₂ ; envisager oxygénothérapie selon le contexte clinique",
            )
    elif feat == "heart_rate":
        peak = max(v for v in (mx_f, last_f) if v is not None) if (mx_f is not None or last_f is not None) else None
        trough = min(v for v in (mn_f, last_f) if v is not None) if (mn_f is not None or last_f is not None) else None
        if peak is not None and peak > 150:
            _append_finding(
                findings, seen, severity=3, feat=feat,
                headline=f"Tachycardie sévère (FC max. {peak:.0f} bpm)",
                action_hint="Évaluation cardiaque urgente ; rechercher cause (douleur, sepsis, arythmie)",
            )
        elif peak is not None and peak > 120:
            _append_finding(
                findings, seen, severity=2, feat=feat,
                headline=f"Tachycardie (FC max. {peak:.0f} bpm)",
                action_hint="Surveillance cardiaque renforcée et recherche de symptômes associés",
            )
        if trough is not None and trough < 40:
            _append_finding(
                findings, seen, severity=3, feat=feat,
                headline=f"Bradycardie sévère (FC min. {trough:.0f} bpm)",
                action_hint="Évaluation cardiaque urgente ; vérifier traitements bradycardisants et état hémodynamique",
            )
        elif trough is not None and trough < 50:
            _append_finding(
                findings, seen, severity=2, feat=feat,
                headline=f"Bradycardie (FC min. {trough:.0f} bpm)",
                action_hint="Surveillance du rythme et du ressenti (lipothymie, fatigue)",
            )
    elif feat == "temperature":
        high = max(v for v in (mx_f, last_f) if v is not None) if (mx_f is not None or last_f is not None) else None
        low_t = min(v for v in (mn_f, last_f) if v is not None) if (mn_f is not None or last_f is not None) else None
        if high is not None and high > 39.5:
            _append_finding(
                findings, seen, severity=3, feat=feat,
                headline=f"Hyperthermie sévère (T° max. {high:.1f} {unit})",
                action_hint="Antipyrétiques, hydratation et bilan infectieux ; consulter si persistance ou frissons",
            )
        elif high is not None and high > 38.0:
            _append_finding(
                findings, seen, severity=2, feat=feat,
                headline=f"Fièvre (T° max. {high:.1f} {unit})",
                action_hint="Surveillance thermique renforcée et recherche de signes infectieux",
            )
        if low_t is not None and low_t < 35.0:
            _append_finding(
                findings, seen, severity=3, feat=feat,
                headline=f"Hypothermie (T° min. {low_t:.1f} {unit})",
                action_hint="Réchauffement actif et recherche de cause (exposition, sepsis, hypoglycémie)",
            )
        elif low_t is not None and low_t < 35.5:
            _append_finding(
                findings, seen, severity=2, feat=feat,
                headline=f"Hypothermie légère (T° min. {low_t:.1f} {unit})",
                action_hint="Surveillance thermique et réévaluation si baisse persistante",
            )

    return findings


def _collect_clinical_findings(analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    vitals = analysis.get("vitals") or {}

    for feat in _FEAT_ORDER:
        info = vitals.get(feat)
        if not info or info.get("status") != "ok":
            continue
        findings.extend(_collect_vital_extreme_findings(info, feat))
        for alert in info.get("clinical_alerts") or []:
            msg = (alert.get("message") or "").strip()
            if not msg:
                continue
            sev = _ALERT_SEVERITY.get(str(alert.get("severity", "warning")), 2)
            findings.append({
                "severity": sev,
                "headline": msg.rstrip("."),
                "action_hint": "Interpréter la dérive en cours avec le contexte clinique du patient",
                "feat": feat,
            })

    timeline = analysis.get("timeline") or []
    ml_crit = sum(1 for p in timeline if p.get("ml_level") == "critical")
    ml_warn = sum(1 for p in timeline if p.get("ml_level") == "warning")
    if ml_crit:
        findings.append({
            "severity": 3,
            "headline": f"{ml_crit} mesure(s) classée(s) critique(s) par le modèle d'analyse",
            "action_hint": "Corréler avec les valeurs brutes et les symptômes avant décision thérapeutique",
            "feat": "ml",
        })
    elif ml_warn:
        findings.append({
            "severity": 2,
            "headline": f"{ml_warn} mesure(s) en vigilance selon le modèle d'analyse",
            "action_hint": "Surveiller la trajectoire sur les prochaines mesures",
            "feat": "ml",
        })

    # Deduplicate by headline, keep highest severity
    by_headline: Dict[str, Dict[str, Any]] = {}
    for f in findings:
        key = f["headline"]
        if key not in by_headline or f["severity"] > by_headline[key]["severity"]:
            by_headline[key] = f
    return sorted(by_headline.values(), key=lambda x: (-x["severity"], x["headline"]))


def _build_clinical_recommendation(findings: List[Dict[str, Any]], max_severity: int) -> str:
    if not findings:
        _, action, _ = weekly_risk_bundle(max_severity)
        return action

    urgent = [f for f in findings if f["severity"] >= 3]
    moderate = [f for f in findings if f["severity"] == 2]

    parts: List[str] = []
    for group in (urgent, moderate):
        for f in group[:2]:
            hint = f.get("action_hint")
            if hint and hint not in parts:
                parts.append(hint)

    if not parts:
        _, action, _ = weekly_risk_bundle(max_severity)
        return action

    suffix = ""
    if urgent:
        suffix = " Recontacter le patient rapidement."
    elif moderate:
        suffix = " Réévaluer sous 24–48 h si persistance."

    return " · ".join(parts[:3]) + suffix


def _compact_vital_line(feat: str, info: Dict[str, Any], abnormal_feats: set) -> Optional[str]:
    """One-line detail for vitals that need attention (not already covered by synthesis)."""
    if feat not in abnormal_feats:
        return None
    stats = info.get("statistics") or {}
    trend = info.get("trend") or {}
    label = _LABELS_FR.get(feat, feat)
    unit = info.get("unit", "")
    mn, mx = stats.get("min"), stats.get("max")
    if mn is None or mx is None:
        return None

    if unit in ("bpm", "%"):
        line = f"{label} : {mn:.0f}–{mx:.0f} {unit}"
    else:
        line = f"{label} : {mn:.1f}–{mx:.1f} {unit}"

    extras: List[str] = []
    t_label = trend.get("label", "stable")
    t_strength = trend.get("strength", "negligible")
    t_sig = bool(trend.get("significant"))
    if t_label != "stable" and t_strength not in ("negligible", "normal") and t_sig:
        direction = "hausse" if t_label == "increasing" else "baisse"
        strength_fr = {"mild": "légère", "moderate": "modérée", "strong": "marquée"}.get(t_strength, t_strength)
        extras.append(f"tendance en {direction} {strength_fr}")

    n_anom = int(info.get("n_anomalies") or 0)
    if n_anom > 0:
        extras.append(f"{n_anom} mesure(s) atypique(s)")

    if extras:
        line += " (" + ", ".join(extras) + ")"
    return line + "."


def build_clinical_weekly_narrative(
    analysis: Dict[str, Any],
    max_severity: int,
    clinical_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Concise clinician-facing narrative: pathology detection, balanced length."""
    if analysis.get("status") == "insufficient_data":
        base = {
            "text": "Pas assez de données pour générer un résumé clinique sur la période.",
            "risk_level": "unknown",
            "recommended_action": "Encourager le patient à enregistrer davantage de mesures.",
        }
        return enrich_narrative_summary(base, analysis, clinical_context, audience="clinical")

    vitals = analysis.get("vitals") or {}
    paragraphs: List[str] = []
    findings = _collect_clinical_findings(analysis)
    abnormal_feats = {f["feat"] for f in findings if f.get("feat") in _FEAT_ORDER}

    intro = period_intro_phrase(analysis)
    if intro:
        n_meas, period_txt = intro
        paragraphs.append(f"Période analysée : {n_meas} mesure(s) sur {period_txt}.")

    urgent = [f for f in findings if f["severity"] >= 3]
    moderate = [f for f in findings if f["severity"] == 2]
    mild = [f for f in findings if f["severity"] == 1]

    if urgent:
        paragraphs.append(
            "Synthèse - urgence possible : "
            + " ; ".join(f["headline"] for f in urgent[:3])
            + "."
        )
    elif moderate:
        paragraphs.append(
            "Synthèse - vigilance : "
            + " ; ".join(f["headline"] for f in moderate[:3])
            + "."
        )
    elif mild:
        paragraphs.append(
            "Synthèse - points à surveiller : "
            + " ; ".join(f["headline"] for f in mild[:2])
            + "."
        )
    else:
        paragraphs.append(
            "Synthèse : profil global stable ; constantes dans les plages attendues sur la période."
        )

    for feat in _FEAT_ORDER:
        info = vitals.get(feat)
        if not info or info.get("status") != "ok":
            continue
        line = _compact_vital_line(feat, info, abnormal_feats)
        if line:
            paragraphs.append(line)

    correlations = analysis.get("correlations") or {}
    hr_spo2 = (correlations.get("heart_rate") or {}).get("spo2")
    if hr_spo2 is not None and abs(float(hr_spo2)) >= 0.45 and (abnormal_feats & {"heart_rate", "spo2"}):
        sense = "évoluent conjointement" if float(hr_spo2) > 0 else "évoluent en sens inverse"
        paragraphs.append(
            f"Fréquence cardiaque et SpO₂ {sense} sur la période (r = {float(hr_spo2):.2f}) - "
            "à interpréter avec le contexte clinique."
        )

    if not paragraphs:
        base = {
            "text": "Les constantes vitales du patient sont dans les plages habituelles sur la période.",
            "risk_level": "minimal",
            "recommended_action": "Poursuivre le suivi habituel ; pas d'action immédiate identifiée.",
        }
        return enrich_narrative_summary(base, analysis, clinical_context, audience="clinical")

    effective_severity = max(max_severity, max((f["severity"] for f in findings), default=0))
    risk, _, _ = weekly_risk_bundle(effective_severity)
    action_clin = _build_clinical_recommendation(findings, effective_severity)

    base = {"text": "\n\n".join(paragraphs), "risk_level": risk, "recommended_action": action_clin}
    return enrich_narrative_summary(base, analysis, clinical_context, audience="clinical")


def build_lay_patient_weekly_summary(
    analysis: Dict[str, Any],
    max_severity: int,
    clinical_context: Optional[Dict[str, Any]] = None,
    *,
    enrich: bool = True,
) -> Dict[str, Any]:
    """Short, accessible French summary for patients and non-specialists."""
    if analysis.get("status") == "insufficient_data":
        base = {
            "text": "Il nous manque encore des mesures pour parler de votre semaine avec précision. "
            "Continuez à enregistrer vos constantes comme d'habitude.",
            "risk_level": "unknown",
            "recommended_action": "Enregistrer un peu plus de mesures sur les prochains jours.",
        }
        if not enrich:
            return base
        return enrich_narrative_summary(base, analysis, clinical_context, audience="patient")
    vitals = analysis.get("vitals", {})
    labels_lay = {
        "heart_rate": "Votre pouls",
        "spo2": "L'oxygène dans votre sang",
        "temperature": "Votre température",
    }
    feat_order = ("heart_rate", "spo2", "temperature")
    paragraphs: List[str] = []
    vital_paragraph_count = 0

    intro = period_intro_phrase(analysis)
    if intro:
        n_meas, period_txt = intro
        paragraphs.append(
            f"Vous avez enregistré {n_meas} mesure(s) sur {period_txt}. "
            "Voici ce que l'on peut en dire, avec des mots simples. "
            "Ce résumé ne remplace pas l'avis d'un médecin ou d'une infirmière."
        )

    for feat in feat_order:
        info = vitals.get(feat)
        if not info or info.get("status") != "ok":
            continue
        stats = info.get("statistics") or {}
        trend = info.get("trend") or {}
        unit = info.get("unit", "")
        label = labels_lay.get(feat, feat)
        mean_val = stats.get("mean")
        if mean_val is None:
            continue

        mn = stats.get("min")
        mx = stats.get("max")
        med = stats.get("median")
        std = stats.get("std")
        cv = stats.get("cv")
        if mn is None or mx is None or med is None:
            continue

        parts: List[str] = []
        if feat == "heart_rate":
            parts.append(
                f"{label} : les relevés vont de {mn:.0f} à {mx:.0f} battements par minute. "
                f"La moyenne sur la période est d'environ {mean_val:.0f}, et en pratique vos mesures se situent souvent vers {med:.0f}."
            )
        elif feat == "spo2":
            parts.append(
                f"{label} : les taux vont de {mn:.0f} à {mx:.0f} pour cent. "
                f"La moyenne est d'environ {mean_val:.0f} pour cent, et le plus souvent autour de {med:.0f} pour cent."
            )
        else:
            parts.append(
                f"{label} : entre {mn:.1f} et {mx:.1f} °C, avec une moyenne d'environ {mean_val:.1f} °C."
            )

        if cv is not None and feat == "heart_rate" and cv >= 12:
            parts.append(
                "Les chiffres du pouls montent et descendent beaucoup d'une mesure à l'autre : "
                "une moyenne seule ne dit pas tout sur ce que vous avez vécu sur la période."
            )
        elif cv is not None and feat == "spo2" and cv >= 5:
            parts.append(
                "L'oxygène n'est pas resté strictement au même niveau tout le temps ; "
                "il est utile de regarder aussi vos dernières mesures."
            )

        series = info.get("series") or []
        if len(series) >= 3:
            last_vals = [float(series[i]["value"]) for i in range(-3, 0)]
            recent_mean = sum(last_vals) / len(last_vals)
            if med is not None and std is not None and float(std) > 1e-6:
                if recent_mean > float(med) + 0.8 * float(std):
                    parts.append("Vos toutes dernières mesures sont plutôt plus hautes que d'habitude pour vous sur cette période.")
                elif recent_mean < float(med) - 0.8 * float(std):
                    parts.append("Vos toutes dernières mesures sont plutôt plus basses que d'habitude pour vous sur cette période.")

        t_label = trend.get("label", "stable")
        t_strength = trend.get("strength", "negligible")
        t_sig = bool(trend.get("significant"))
        if t_label == "stable" or t_strength in ("negligible", "normal") or not t_sig:
            parts.append("Sur l'ensemble des jours, la tendance reste plutôt stable.")
        else:
            direction = "augmenter" if t_label == "increasing" else "diminuer"
            intens = {"mild": "un peu", "moderate": "modérément", "strong": "nettement"}.get(t_strength, "")
            phrase = f"Sur la période, les valeurs ont plutôt tendance à {direction}"
            if intens:
                phrase += f" {intens}"
            phrase += "."
            parts.append(phrase)

        n_anom = int(info.get("n_anomalies") or 0)
        if n_anom > 0:
            parts.append(
                f"{n_anom} mesure(s) ont été signalées comme inhabituelles par le système ; "
                "votre équipe soignante peut vous aider à comprendre si c'est normal dans votre situation."
            )

        if info.get("clinical_alerts"):
            parts.append(
                "Une alerte de suivi automatique signale une évolution à garder à l'œil ; "
                "parlez-en à votre médecin si vous ne savez pas quoi en penser."
            )

        paragraphs.append(" ".join(parts))
        vital_paragraph_count += 1

    correlations = analysis.get("correlations") or {}
    hr_spo2 = (correlations.get("heart_rate") or {}).get("spo2")
    if hr_spo2 is not None and abs(float(hr_spo2)) >= 0.45:
        together = "souvent monté ou baissé en même temps" if float(hr_spo2) > 0 else "souvent évolué en sens inverse"
        paragraphs.append(
            f"Votre pouls et votre taux d'oxygène ont {together} sur la période. "
            "En cas de doute, demandez l'avis d'un professionnel de santé."
        )

    timeline = analysis.get("timeline") or []
    ml_warn = sum(1 for p in timeline if p.get("ml_level") == "warning")
    ml_crit = sum(1 for p in timeline if p.get("ml_level") == "critical")
    if ml_crit or ml_warn:
        paragraphs.append(
            f"L'outil d'analyse a classé {ml_crit + ml_warn} de vos mesures comme devant être surveillées de plus près "
            f"({ml_crit} en niveau critique, {ml_warn} en niveau vigilance). "
            "Comparez cela avec ce que vous avez réellement ressenti."
        )

    if vital_paragraph_count == 0:
        if len(paragraphs) == 0:
            base = {
                "text": "Vos constantes semblent dans des fourchettes habituelles sur la période.",
                "risk_level": "minimal",
                "recommended_action": "Continuez à prendre vos mesures comme prévu.",
            }
        else:
            risk, _, action_patient = weekly_risk_bundle(max_severity)
            base = {"text": "\n\n".join(paragraphs), "risk_level": risk, "recommended_action": action_patient}
        if not enrich:
            return base
        return enrich_narrative_summary(base, analysis, clinical_context, audience="patient")

    risk, _, action_patient = weekly_risk_bundle(max_severity)
    base = {"text": "\n\n".join(paragraphs), "risk_level": risk, "recommended_action": action_patient}
    if not enrich:
        return base
    return enrich_narrative_summary(base, analysis, clinical_context, audience="patient")


_CAREGIVER_TEXT_REPLACEMENTS = (
    ("Vous avez enregistré", "Votre proche a enregistré"),
    ("Votre pouls et votre taux d'oxygène", "Son pouls et son taux d'oxygène"),
    ("Votre pouls", "Son pouls"),
    ("L'oxygène dans votre sang", "L'oxygène dans son sang"),
    ("Votre température", "Sa température"),
    ("Vos toutes dernières mesures", "Ses dernières mesures"),
    ("vos mesures", "ses mesures"),
    ("Vos mesures", "Ses mesures"),
    ("pour vous sur cette période", "sur cette période"),
    ("ce que vous avez réellement ressenti", "ce qu'il ou elle ressent"),
    ("Continuez vos mesures", "Encouragez votre proche à poursuivre les mesures"),
    ("Continuez à prendre vos mesures", "Encouragez votre proche à poursuivre les mesures"),
    ("Continuez à enregistrer vos constantes", "Encouragez votre proche à enregistrer ses constantes"),
    ("Enregistrer un peu plus de mesures", "Encourager quelques mesures supplémentaires"),
    ("Enregistrer des mesures", "Encourager des mesures"),
    ("Consultez votre médecin", "Contactez son médecin"),
    ("contactez votre médecin", "contactez son médecin"),
    ("Prévenez la personne qui s'occupe de vous", "Restez attentif et prévenez le médecin"),
    ("si vous ne savez pas quoi en penser", "en cas de doute"),
    ("si vous vous sentez bien", "si votre proche se sent bien"),
    ("Pour interpréter vos mesures", "Pour interpréter les mesures de votre proche"),
    ("Nous tenons compte des informations que vous avez renseignées", "Le dossier médical de votre proche est pris en compte"),
    ("Votre médecin vous a récemment conseillé", "Le médecin a récemment indiqué à votre proche"),
    ("Votre taux d'oxygène", "Son taux d'oxygène"),
    ("vous avez une", "votre proche a une"),
    ("Vous avez de la fièvre", "Votre proche a de la fièvre"),
    ("avec votre diabète", "avec son diabète"),
    ("avec votre arythmie", "avec son arythmie"),
    ("avec votre hypertension", "avec son hypertension"),
    ("avec votre insuffisance cardiaque", "avec son insuffisance cardiaque"),
    ("Rappel du suivi médical", "Rappel du suivi médical pour votre proche"),
)


def build_lay_caregiver_weekly_summary(
    analysis: Dict[str, Any],
    max_severity: int,
    clinical_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Accessible French summary for caregivers (non-clinical wording, third person)."""
    base = build_lay_patient_weekly_summary(
        analysis, max_severity, clinical_context=None, enrich=False,
    )
    text = base.get("text") or ""
    for old, new in _CAREGIVER_TEXT_REPLACEMENTS:
        text = text.replace(old, new)
    action = base.get("recommended_action") or ""
    for old, new in _CAREGIVER_TEXT_REPLACEMENTS:
        action = action.replace(old, new)
    caregiver_base = {**base, "text": text, "recommended_action": action}
    return enrich_narrative_summary(caregiver_base, analysis, clinical_context, audience="caregiver")
