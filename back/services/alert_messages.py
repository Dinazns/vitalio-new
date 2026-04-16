"""
Formulation des messages d'alerte : version médicale (médecin) vs grand public (aidant).
"""
from typing import Dict, Any


def format_alert_for_doctor(alert: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enrichit une alerte avec une description médicale précise et réaliste.
    """
    out = dict(alert)
    metric = alert.get("metric", "")
    operator = alert.get("operator", "")
    value = alert.get("value") or alert.get("latest_value")
    threshold = alert.get("threshold")

    def _v(x):
        return f"{x:.1f}" if isinstance(x, (int, float)) else str(x)

    # Terminologie médicale, valeurs précises, recommandation clinique
    if metric == "ml_anomaly":
        out["medical_label"] = "Anomalie ML (validée)"
        ds = alert.get("dossier_summary") or ""
        sev = alert.get("ml_severity") or alert.get("severity") or ""
        out["medical_description"] = (
            (str(ds) + (" " if ds and sev else "")) + (f"Gravité : {sev}" if sev else "")
        ).strip() or "Anomalie détectée par le modèle, validée par le médecin."
    elif metric == "manual":
        out["medical_label"] = "Alerte déclenchée par le patient"
        msg = alert.get("patient_message") or ""
        out["medical_description"] = (
            "Le patient a déclenché manuellement une alerte via l'application."
            + (f" Message : {msg}" if msg else "")
            + " Vérifier l'état clinique, contacter le patient ou l'aidant."
        )
    elif metric == "heart_rate":
        if operator == "lt":
            out["medical_label"] = "Bradycardie"
            out["medical_description"] = (
                f"FC {_v(value)} bpm (seuil minimal {_v(threshold)} bpm). "
                "À confirmer cliniquement, vérifier médicaments (β-bloquants, digitaliques)."
            )
        else:  # gt
            out["medical_label"] = "Tachycardie"
            out["medical_description"] = (
                f"FC {_v(value)} bpm (seuil maximal {_v(threshold)} bpm). "
                "À confirmer cliniquement, rechercher fièvre, déshydratation, cause cardiaque."
            )
    elif metric == "spo2":
        out["medical_label"] = "Hypoxémie"
        out["medical_description"] = (
            f"SpO₂ {_v(value)} % (seuil minimal {_v(threshold)} %). "
            "Surveillance rapprochée recommandée. Évaluer cause respiratoire, positionnement."
        )
    elif metric == "temperature":
        if operator == "lt":
            out["medical_label"] = "Hypothermie"
            out["medical_description"] = (
                f"Température {_v(value)} °C (seuil minimal {_v(threshold)} °C). "
                "Exclure exposition au froid, défaillance circulatoire."
            )
        else:
            out["medical_label"] = "Hyperthermie / Fièvre"
            out["medical_description"] = (
                f"Température {_v(value)} °C (seuil maximal {_v(threshold)} °C). "
                "Rechercher infection, déshydratation. Antipyrétiques si indiqué."
            )
    else:
        out["medical_label"] = metric
        out["medical_description"] = f"Valeur {_v(value)} hors seuil ({_v(threshold)})."

    return out


def format_alert_for_caregiver(alert: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enrichit une alerte avec une formulation compréhensible pour un aidant non médical.
    """
    out = dict(alert)
    metric = alert.get("metric", "")
    operator = alert.get("operator", "")
    value = alert.get("value") or alert.get("latest_value")
    threshold = alert.get("threshold")

    def _v(x):
        return f"{x:.0f}" if isinstance(x, (int, float)) else str(x)

    if metric == "manual":
        msg = alert.get("patient_message") or ""
        out["summary"] = "Votre proche a demandé de l'aide"
        out["lay_description"] = (
            "La personne a appuyé sur le bouton d'alerte dans l'application."
            + (f" Son message : « {msg} »" if msg else "")
            + " Contactez-la dès que possible pour vérifier son état."
            " Si elle ne répond pas ou si vous êtes inquiet, appelez le 15."
        )
    elif metric == "ml_anomaly":
        out["summary"] = "Le système a détecté une anomalie sur les constantes"
        out["lay_description"] = (
            str(alert.get("dossier_summary") or "Les mesures semblent inhabituelles pour cette personne. ")
            + "Le médecin a confirmé le signalement. Si la personne va mal, appelez le 15. "
            "Sinon indiquez que la situation est résolue."
        )
    elif metric == "heart_rate":
        if operator == "lt":
            out["summary"] = "Le pouls (battements du cœur) est très bas"
            out["lay_description"] = (
                f"Le capteur indique {_v(value)} battements par minute. "
                "C'est en dessous de la normale. Si la personne se sent mal ou si vous êtes inquiet, "
                "Le médecin est déjà informé. Appelez le SAMU en composant le 15."
                "Sinon indiquez que la situation est résolue."
            )
        else:
            out["summary"] = "Le cœur bat très vite"
            out["lay_description"] = (
                f"Le capteur indique {_v(value)} battements par minute. "
                "C'est au-dessus de la normale. Demandez à la personne si elle ressent des palpitations ou un malaise."
                "Le médecin est déjà informé. Appelez le SAMU en composant le 15."
                "Sinon indiquez que la situation est résolue."
            )
    elif metric == "spo2":
        out["summary"] = "L'oxygénation du sang est basse"
        out["lay_description"] = (
            f"Le capteur indique {_v(value)} % d'oxygène dans le sang. "
            "C'est en dessous de la normale. Prévenez le médecin. "
            "Assurez-vous que la personne respire bien et n'est pas en position allongée trop longtemps."
            "Le médecin est déjà informé. Appelez le SAMU en composant le 15."
            "Sinon indiquez que la situation est résolue."
        )
    elif metric == "temperature":
        if operator == "lt":
            out["summary"] = "La température est trop basse"
            out["lay_description"] = (
                f"Le capteur indique {_v(value)} °C. "
                "Couvrez la personne et vérifiez qu'elle n'a pas froid. "
                "Si elle est confuse ou tremble beaucoup, appelez le SAMU en composant le 15."
                "Sinon indiquez que la situation est résolue."
            )
        else:
            out["summary"] = "La personne a de la fièvre"
            out["lay_description"] = (
                f"Le capteur indique {_v(value)} °C. "
                "Proposez à boire, déshabillez légèrement si besoin. "
                "Si la fièvre monte ou dure plus de 24 h, appelez le SAMU en composant le 15."
                "Sinon indiquez que la situation est résolue."
            )
    else:
        out["summary"] = "Une mesure est hors de la normale"
        out["lay_description"] = f"Valeur mesurée : {_v(value)}. Prévenez le médecin si vous êtes inquiet."

    return out
