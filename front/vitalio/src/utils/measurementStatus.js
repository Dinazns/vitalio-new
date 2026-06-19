const VALIDATION_REASON_LABELS = {
  heart_rate_out_of_range: 'fréquence cardiaque hors plage',
  spo2_out_of_range: 'SpO₂ hors plage',
  temperature_out_of_range: 'température hors plage',
  low_signal_quality: 'qualité du signal insuffisante',
}

function normalizeMeasurementStatus(status) {
  return String(status || '').trim().toUpperCase()
}

function formatValidationReasons(reasons) {
  if (!Array.isArray(reasons) || !reasons.length) return ''
  return reasons
    .map((code) => VALIDATION_REASON_LABELS[code] || code)
    .join(', ')
}

/**
 * Libellé court pour l’historique des mesures (vue médecin / aidant).
 */
export function formatMeasurementQualityLabel(status) {
  const normalized = normalizeMeasurementStatus(status)
  if (normalized === 'VALID') return 'Exploitable'
  if (normalized === 'INVALID') return 'Non exploitable'
  return '-'
}

/**
 * Infobulle décrivant la qualité technique de la mesure.
 */
export function formatMeasurementQualityHint(measurement = {}) {
  const normalized = normalizeMeasurementStatus(measurement.status)
  const reasons = formatValidationReasons(measurement.validation_reasons)

  if (normalized === 'VALID') {
    return 'Mesure retenue : signal et valeurs conformes aux critères de fiabilité.'
  }
  if (normalized === 'INVALID') {
    if (reasons) return `Mesure écartée : ${reasons}.`
    return 'Mesure écartée : signal ou valeurs hors critères de fiabilité.'
  }
  return ''
}
