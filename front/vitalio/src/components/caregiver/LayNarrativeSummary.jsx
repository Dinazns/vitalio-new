import React from 'react'
import { BookOpen, ArrowRight } from 'lucide-react'
import { LAY_RISK_CONFIG } from '../../constants/layRiskLabels'

export default function LayNarrativeSummary({ summary, title = 'Synthèse en mots simples' }) {
  if (!summary?.text) return null
  const risk = LAY_RISK_CONFIG[summary.risk_level] || LAY_RISK_CONFIG.unknown

  return (
    <section className="caregiver-lay-narrative" aria-labelledby="lay-narrative-title">
      <div className="caregiver-lay-narrative__head">
        <BookOpen size={24} aria-hidden />
        <div>
          <h2 id="lay-narrative-title">{title}</h2>
          <p className="caregiver-lay-narrative__lead">
            Résumé automatique sur la période choisie, rédigé pour vous aider à comprendre la situation sans jargon médical.
          </p>
        </div>
      </div>
      <div className="caregiver-lay-narrative__body">
        <span
          className="caregiver-lay-narrative__badge"
          style={{ background: risk.bg, color: risk.color }}
        >
          {risk.label}
        </span>
        <div className="caregiver-lay-narrative__text">
          {summary.text.split('\n\n').map((paragraph, index) => (
            <p key={index}>{paragraph}</p>
          ))}
        </div>
        {summary.recommended_action && (
          <p className="caregiver-lay-narrative__action">
            <ArrowRight size={16} aria-hidden />
            <span>{summary.recommended_action}</span>
          </p>
        )}
      </div>
    </section>
  )
}
