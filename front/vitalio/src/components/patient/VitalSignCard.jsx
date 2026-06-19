import React from 'react'
import { TrendingDown, TrendingUp, Minus } from 'lucide-react'
import {
  VITAL_COLORS,
  VITAL_STATUS_LABELS,
  getVitalDisplayValue,
  getVitalStatus,
  getVitalTrend,
} from '../../utils/vitalStatus'

const TREND_ICONS = {
  up: TrendingUp,
  down: TrendingDown,
  stable: Minus,
}

export default function VitalSignCard({ vitalKey, label, value, previousValue, Icon }) {
  const status = getVitalStatus(vitalKey, value)
  const color = VITAL_COLORS[status]
  const statusLabel = VITAL_STATUS_LABELS[status]
  const displayValue = getVitalDisplayValue(vitalKey, value)
  const trend = getVitalTrend(vitalKey, value, previousValue)
  const TrendIcon = trend ? TREND_ICONS[trend.direction] : null

  return (
    <article
      className={`vital-card vital-card--${status}`}
      style={{ '--vital-accent': color }}
      aria-label={`${label} : ${displayValue}, ${statusLabel}${trend ? `, ${trend.label}` : ''}`}
    >
      <div className="vital-card__header">
        <Icon size={32} strokeWidth={2} aria-hidden className="vital-card__icon" />
        <span className="vital-card__label">{label}</span>
      </div>
      <p className="vital-card__value">{displayValue}</p>
      <div className="vital-card__status" aria-hidden="true">
        <span className="vital-card__dot" />
        <span className="vital-card__status-text">{statusLabel}</span>
      </div>
      {trend && TrendIcon && (
        <p className="vital-card__trend" aria-hidden="true">
          <TrendIcon size={16} strokeWidth={2.5} />
          <span>{trend.label}</span>
        </p>
      )}
    </article>
  )
}
