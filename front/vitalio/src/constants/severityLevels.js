/** Unified alert severity taxonomy (evaluation grid). */
export const SEVERITY_LEVEL_CONFIG = {
  INFO: {
    color: '#0369a1',
    bg: '#e0f2fe',
    border: '#7dd3fc',
    label: 'Info',
  },
  WARNING: {
    color: '#b45309',
    bg: '#fffbeb',
    border: '#fcd34d',
    label: 'Attention',
  },
  CRITICAL: {
    color: '#b91c1c',
    bg: '#fef2f2',
    border: '#fca5a5',
    label: 'Critique',
  },
  URGENCY: {
    color: '#7f1d1d',
    bg: '#fecaca',
    border: '#f87171',
    label: 'Urgence',
  },
}

/** Map legacy ml_level to grid severity for measurement timeline. */
export function mlLevelToSeverityLevel(mlLevel) {
  const lvl = String(mlLevel || 'normal').toLowerCase()
  if (lvl === 'critical') return 'CRITICAL'
  if (lvl === 'warning') return 'WARNING'
  return 'INFO'
}

export function getSeverityConfig(level) {
  const key = String(level || 'INFO').toUpperCase()
  return SEVERITY_LEVEL_CONFIG[key] || SEVERITY_LEVEL_CONFIG.INFO
}
