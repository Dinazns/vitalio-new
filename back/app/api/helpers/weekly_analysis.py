"""Weekly vitals narrative helpers."""
from typing import Any, Dict, List, Optional, Tuple

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
            "Consultez votre médecin ou un professionnel de santé pour interpréter ces variations.",
            "Si vous ne vous sentez pas bien (douleur, essoufflement, malaise), appelez vite votre médecin ou le 15.",
        )
    if max_severity >= 2:
        return (
            "moderate",
            "Restez vigilant aux prochaines mesures ; en cas de symptômes ou persistance des alertes, demandez un avis médical.",
            "Poursuivez le suivi à domicile. Si l'inquiétude ou des symptômes durent plus de quelques jours, contactez votre médecin ou votre infirmier.",
        )
    if max_severity >= 1:
        return (
            "low",
            "Poursuivez la surveillance habituelle et signalez tout changement notable à votre soignant.",
            "Continuez vos mesures comme d'habitude. Prévenez la personne qui s'occupe de vous en cas de changement net.",
        )
    return (
        "minimal",
        "Pas d'action particulière nécessaire ; continuez vos mesures régulières.",
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


def build_clinical_weekly_narrative(analysis: Dict[str, Any], max_severity: int) -> Dict[str, Any]:
    """Detailed, statistical narrative for clinicians (médecin / équipe soignante)."""
    if analysis.get("status") == "insufficient_data":
        return {
            "text": "Pas assez de données pour générer un résumé. Continuez à enregistrer vos mesures.",
            "risk_level": "unknown",
            "recommended_action": "Enregistrer plus de mesures cette semaine.",
        }
    vitals = analysis.get("vitals", {})
    labels_fr = {"heart_rate": "Fréquence cardiaque", "spo2": "Oxygène dans le sang", "temperature": "Température"}
    feat_order = ("heart_rate", "spo2", "temperature")
    paragraphs: List[str] = []
    vital_paragraph_count = 0

    intro = period_intro_phrase(analysis)
    if intro:
        n_meas, period_txt = intro
        paragraphs.append(
            f"Analyse basée sur {n_meas} mesure(s) sur {period_txt}. "
            "Le détail ci-dessous complète les moyennes par la dispersion, la tendance globale et les points atypiques."
        )

    for feat in feat_order:
        info = vitals.get(feat)
        if not info or info.get("status") != "ok":
            continue
        stats = info.get("statistics") or {}
        trend = info.get("trend") or {}
        unit = info.get("unit", "")
        label = labels_fr.get(feat, feat)
        mean_val = stats.get("mean")
        if mean_val is None:
            continue

        mn = stats.get("min")
        mx = stats.get("max")
        med = stats.get("median")
        std = stats.get("std")
        cv = stats.get("cv")

        parts: List[str] = []
        if unit in ("bpm", "%"):
            parts.append(
                f"{label} : valeurs observées entre {mn:.0f} et {mx:.0f} {unit}, "
                f"médiane {med:.0f} {unit}, moyenne {mean_val:.0f} {unit}."
            )
        else:
            parts.append(
                f"{label} : valeurs entre {mn:.1f} et {mx:.1f} {unit}, "
                f"médiane {med:.1f} {unit}, moyenne {mean_val:.1f} {unit}."
            )

        if cv is not None and feat == "heart_rate" and cv >= 12:
            parts.append(
                "La variabilité est marquée : l'écart entre les mesures est important, "
                "donc la moyenne seule ne résume pas bien l'activité récente (pics et creux possibles)."
            )
        elif cv is not None and feat == "spo2" and cv >= 5:
            parts.append(
                "Des écarts notables autour de la moyenne sont visibles ; la série n'est pas strictement plate, "
                "ce qui mérite d'être regardé avec les mesures les plus récentes."
            )

        series = info.get("series") or []
        if len(series) >= 3:
            last_vals = [float(series[i]["value"]) for i in range(-3, 0)]
            recent_mean = sum(last_vals) / len(last_vals)
            if med is not None and std is not None and float(std) > 1e-6:
                if recent_mean > float(med) + 0.8 * float(std):
                    parts.append(
                        "Les toutes dernières mesures sont nettement plus hautes que le niveau médian de la semaine."
                    )
                elif recent_mean < float(med) - 0.8 * float(std):
                    parts.append(
                        "Les toutes dernières mesures sont nettement plus basses que le niveau médian de la semaine."
                    )

        t_label = trend.get("label", "stable")
        t_strength = trend.get("strength", "negligible")
        t_sig = bool(trend.get("significant"))
        spd = abs(float(trend.get("slope_per_day", 0) or 0))
        if t_label == "stable" or t_strength in ("negligible", "normal") or not t_sig:
            parts.append(
                "Tendance sur la période : globalement stable (pas de pente nette et statistiquement fiable sur l'ensemble des jours)."
            )
        else:
            direction_fr = "à la hausse" if t_label == "increasing" else "à la baisse"
            strength_fr = {"mild": "légère", "moderate": "modérée", "strong": "marquée"}.get(t_strength, t_strength)
            unit_day = unit if unit else "unité"
            parts.append(
                f"Tendance sur la période : évolution {direction_fr}, d'intensité {strength_fr} "
                f"(ordre de grandeur ~{spd:.1f} {unit_day} par jour)."
            )

        n_anom = int(info.get("n_anomalies") or 0)
        if n_anom > 0:
            parts.append(
                f"{n_anom} mesure(s) ressortent comme atypiques (hors plage attendue ou outlier statistique) sur cette série."
            )

        for alert in info.get("clinical_alerts") or []:
            msg = alert.get("message")
            if msg:
                parts.append(msg)

        paragraphs.append(" ".join(parts))
        vital_paragraph_count += 1

    correlations = analysis.get("correlations") or {}
    hr_spo2 = (correlations.get("heart_rate") or {}).get("spo2")
    if hr_spo2 is not None and abs(float(hr_spo2)) >= 0.45:
        sense = "varient souvent dans le même sens" if float(hr_spo2) > 0 else "varient souvent en sens opposé"
        paragraphs.append(
            f"Lien entre fréquence cardiaque et oxygénation : corrélation notable ({float(hr_spo2):.2f}) — les deux courbes {sense} "
            "sur la semaine, ce qui peut correspondre à des épisodes conjoints à interpréter avec un professionnel de santé si cela vous concerne."
        )

    timeline = analysis.get("timeline") or []
    ml_warn = sum(1 for p in timeline if p.get("ml_level") == "warning")
    ml_crit = sum(1 for p in timeline if p.get("ml_level") == "critical")
    if ml_crit or ml_warn:
        paragraphs.append(
            f"Modèle d'aide à l'analyse : {ml_crit + ml_warn} mesure(s) classées en vigilance ou alerte sur la période "
            f"({ml_crit} critique(s), {ml_warn} vigilance(s)) — à rapprocher des valeurs brutes et de votre ressenti."
        )

    if vital_paragraph_count == 0:
        if len(paragraphs) == 0:
            return {
                "text": "Vos constantes vitales de la semaine sont dans les plages habituelles.",
                "risk_level": "minimal",
                "recommended_action": "Continuez à surveiller vos mesures.",
            }
        risk, action_clin, _ = weekly_risk_bundle(max_severity)
        return {"text": "\n\n".join(paragraphs), "risk_level": risk, "recommended_action": action_clin}

    risk, action_clin, _ = weekly_risk_bundle(max_severity)
    return {"text": "\n\n".join(paragraphs), "risk_level": risk, "recommended_action": action_clin}


def build_lay_patient_weekly_summary(analysis: Dict[str, Any], max_severity: int) -> Dict[str, Any]:
    """Short, accessible French summary for patients and non-specialists."""
    if analysis.get("status") == "insufficient_data":
        return {
            "text": "Il nous manque encore des mesures pour parler de votre semaine avec précision. "
            "Continuez à enregistrer vos constantes comme d'habitude.",
            "risk_level": "unknown",
            "recommended_action": "Enregistrer un peu plus de mesures sur les prochains jours.",
        }
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
            return {
                "text": "Vos constantes semblent dans des fourchettes habituelles sur la période.",
                "risk_level": "minimal",
                "recommended_action": "Continuez à prendre vos mesures comme prévu.",
            }
        risk, _, action_patient = weekly_risk_bundle(max_severity)
        return {"text": "\n\n".join(paragraphs), "risk_level": risk, "recommended_action": action_patient}

    risk, _, action_patient = weekly_risk_bundle(max_severity)
    return {"text": "\n\n".join(paragraphs), "risk_level": risk, "recommended_action": action_patient}
