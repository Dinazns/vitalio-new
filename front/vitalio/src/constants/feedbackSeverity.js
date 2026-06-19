/** Libellés français pour la sévérité des commentaires médecin (valeurs API : low, medium, high). */
export const FEEDBACK_SEVERITY_LABELS = {
  low: 'Faible',
  medium: 'Moyenne',
  high: 'Haute',
}

export function getFeedbackSeverityLabel(severity, fallback = '-') {
  const key = String(severity || '').trim().toLowerCase()
  if (!key) return fallback
  return FEEDBACK_SEVERITY_LABELS[key] || fallback
}
