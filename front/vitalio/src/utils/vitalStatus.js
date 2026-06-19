export const VITAL_COLORS = {
  normal: '#10b981',
  attention: '#f59e0b',
  abnormal: '#ef4444',
  unmeasured: '#9ca3af',
}

export const VITAL_STATUS_LABELS = {
  normal: 'Normal',
  attention: 'Attention',
  abnormal: 'Anormal',
  unmeasured: 'Non mesuré',
}

const VITAL_CONFIG = {
  spo2: {
    label: 'SpO₂',
    unit: '%',
    normal: { min: 95, max: Infinity },
    attention: [
      { min: 92, max: 94.99 },
    ],
    abnormal: { below: 92 },
    format: (v) => `${Math.round(v)}%`,
  },
  heart_rate: {
    label: 'Fréquence cardiaque',
    unit: 'bpm',
    normal: { min: 60, max: 100 },
    attention: [
      { min: 50, max: 59.99 },
      { min: 101, max: 120 },
    ],
    abnormal: { below: 50, above: 120 },
    format: (v) => `${Math.round(v)} bpm`,
  },
  temperature: {
    label: 'Température',
    unit: '°C',
    normal: { min: 36.0, max: 37.5 },
    attention: [
      { min: 37.6, max: 38.5 },
    ],
    abnormal: { below: 35.5, above: 38.5 },
    format: (v) => `${Number(v).toFixed(1)} °C`,
  },
}

function isInRange(value, { min, max }) {
  return value >= min && value <= max
}

export function getVitalStatus(vitalKey, rawValue) {
  if (rawValue == null || rawValue === '' || Number.isNaN(Number(rawValue))) {
    return 'unmeasured'
  }
  const value = Number(rawValue)
  const cfg = VITAL_CONFIG[vitalKey]
  if (!cfg) return 'unmeasured'

  if (cfg.abnormal?.below != null && value < cfg.abnormal.below) return 'abnormal'
  if (cfg.abnormal?.above != null && value > cfg.abnormal.above) return 'abnormal'

  if (cfg.normal && isInRange(value, cfg.normal)) return 'normal'

  if (cfg.attention?.some((range) => isInRange(value, range))) return 'attention'

  return 'abnormal'
}

export function getVitalDisplayValue(vitalKey, rawValue) {
  if (rawValue == null || rawValue === '' || Number.isNaN(Number(rawValue))) return '-'
  return VITAL_CONFIG[vitalKey]?.format(Number(rawValue)) ?? String(rawValue)
}

export function getVitalTrend(vitalKey, current, previous) {
  const cur = Number(current)
  const prev = Number(previous)
  if (!Number.isFinite(cur) || !Number.isFinite(prev)) return null
  const delta = cur - prev
  const threshold = vitalKey === 'temperature' ? 0.2 : 1
  if (Math.abs(delta) < threshold) return { direction: 'stable', label: 'Stable', delta }
  if (delta > 0) return { direction: 'up', label: 'En hausse', delta }
  return { direction: 'down', label: 'En baisse', delta }
}

export function getOverallVitalStatus(statuses) {
  const list = statuses.filter(Boolean)
  if (!list.length || list.every((s) => s === 'unmeasured')) return 'unmeasured'
  if (list.some((s) => s === 'abnormal')) return 'abnormal'
  if (list.some((s) => s === 'attention')) return 'attention'
  if (list.every((s) => s === 'normal')) return 'normal'
  return 'unmeasured'
}

export function formatRelativeMeasurementTime(isoValue) {
  if (!isoValue) return null
  const ts = new Date(isoValue).getTime()
  if (!Number.isFinite(ts)) return null
  const diffMs = Date.now() - ts
  if (diffMs < 0) return "à l'instant"

  const minutes = Math.floor(diffMs / 60000)
  if (minutes < 1) return "à l'instant"
  if (minutes < 60) return `il y a ${minutes} min`

  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `il y a ${hours} h`

  const days = Math.floor(hours / 24)
  if (days === 1) return 'il y a 1 jour'
  return `il y a ${days} jours`
}

export function getChartNormalRange(vitalKey) {
  const cfg = VITAL_CONFIG[vitalKey]
  if (!cfg?.normal) return null
  return { min: cfg.normal.min, max: cfg.normal.max === Infinity ? null : cfg.normal.max }
}

export function getPointColor(vitalKey, value) {
  const status = getVitalStatus(vitalKey, value)
  return VITAL_COLORS[status] || VITAL_COLORS.unmeasured
}

export const VITAL_TREND_TABS = [
  { key: 'spo2', label: 'SpO₂' },
  { key: 'heart_rate', label: 'Fréquence cardiaque' },
  { key: 'temperature', label: 'Température' },
]

export const MEASUREMENT_DURATION_SEC = 25
