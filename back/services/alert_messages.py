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
    if metric == "heart_rate":
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

    if metric == "heart_rate":
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
