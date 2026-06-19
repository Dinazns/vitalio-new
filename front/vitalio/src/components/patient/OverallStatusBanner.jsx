import React from 'react'
import { CheckCircle2, AlertTriangle, XCircle, HelpCircle } from 'lucide-react'
import { VITAL_COLORS, getOverallVitalStatus } from '../../utils/vitalStatus'

const BANNER_CONFIG = {
  normal: {
    Icon: CheckCircle2,
    title: 'Tout va bien',
    message: 'Vos constantes sont dans les valeurs normales. Continuez vos mesures régulières.',
  },
  attention: {
    Icon: AlertTriangle,
    title: 'Surveillance recommandée',
    message: 'Une ou plusieurs constantes méritent votre attention. Restez vigilant et mesurez-vous à nouveau.',
  },
  abnormal: {
    Icon: XCircle,
    title: 'Constantes anormales',
    message: 'Des valeurs sont hors des plages normales. Contactez votre médecin ou votre aidant en cas de symptômes.',
  },
  unmeasured: {
    Icon: HelpCircle,
    title: 'En attente de mesures',
    message: 'Aucune mesure récente disponible. Lancez une prise de mesure avec votre boîtier.',
  },
}

export default function OverallStatusBanner({ statuses }) {
  const overall = getOverallVitalStatus(statuses)
  const cfg = BANNER_CONFIG[overall]
  const color = VITAL_COLORS[overall]
  const { Icon, title, message } = cfg

  return (
    <div
      className={`patient-status-banner patient-status-banner--${overall}`}
      style={{ '--banner-accent': color }}
      role="status"
      aria-live="polite"
    >
      <Icon size={28} strokeWidth={2} aria-hidden className="patient-status-banner__icon" />
      <div className="patient-status-banner__text">
        <strong>{title}</strong>
        <p>{message}</p>
      </div>
    </div>
  )
}
