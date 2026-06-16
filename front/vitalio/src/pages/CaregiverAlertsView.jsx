import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useAuth0 } from '@auth0/auth0-react'
import {
  TriangleAlert,
  Siren,
  CheckCircle2,
  Eye,
  EyeOff,
  Info,
  ChevronDown,
  ChevronUp,
  Phone,
} from 'lucide-react'
import {
  getCaregiverAlerts,
  getCaregiverPatients,
  patchCaregiverAlert,
} from '../services/api'
import { resolvePatientListDisplayName } from '../utils/displayName'
import { getSeverityConfig, SEVERITY_LEVEL_CONFIG } from '../constants/severityLevels'

const formatTime = (iso) => {
  if (!iso) return '-'
  return new Date(iso).toLocaleString('fr-FR', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export default function CaregiverAlertsView() {
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const base = pathname.startsWith('/family') ? '/family' : '/caregiver'
  const { getAccessTokenSilently } = useAuth0()

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [alerts, setAlerts] = useState([])
  const [patients, setPatients] = useState([])
  const [statusFilter, setStatusFilter] = useState('OPEN')
  const [severityFilter, setSeverityFilter] = useState('')
  const [expandedId, setExpandedId] = useState(null)
  const [resolvingAlertId, setResolvingAlertId] = useState(null)
  const [resolutionComment, setResolutionComment] = useState('')
  const [resolutionError, setResolutionError] = useState('')
  const [seenAlertId, setSeenAlertId] = useState(null)
  const [seenComment, setSeenComment] = useState('')
  const [seenError, setSeenError] = useState('')

  const patientNames = useMemo(() => {
    const m = {}
    patients.forEach((p) => {
      const label = resolvePatientListDisplayName(p)
      if (!label) return
      const key = p.id || p.patient_id
      if (key) m[key] = label
      if (p.patient_id && p.patient_id !== key) m[p.patient_id] = label
    })
    return m
  }, [patients])

  const loadData = useCallback(async () => {
    try {
      setLoading(true)
      setError('')
      const token = await getAccessTokenSilently()
      const [alertsRes, patientsRes] = await Promise.all([
        getCaregiverAlerts(token, {
          status: statusFilter,
          limit: 200,
          severity_level: severityFilter || undefined,
        }),
        getCaregiverPatients(token),
      ])
      setAlerts(Array.isArray(alertsRes.alerts) ? alertsRes.alerts : [])
      setPatients(Array.isArray(patientsRes.patients) ? patientsRes.patients : [])
    } catch (e) {
      setError(e.message || 'Impossible de charger les alertes')
    } finally {
      setLoading(false)
    }
  }, [getAccessTokenSilently, statusFilter, severityFilter])

  useEffect(() => {
    loadData()
  }, [loadData])

  const openCount = alerts.filter((a) => String(a.status || '').toUpperCase() === 'OPEN').length

  const handleResolveAlert = async (alertId) => {
    const comment = resolutionComment.trim()
    if (!comment) {
      setResolutionError('Indiquez ce qui a été fait (ex. : vérification sur place, appel au médecin).')
      return
    }
    try {
      setResolutionError('')
      const token = await getAccessTokenSilently()
      const res = await patchCaregiverAlert(token, alertId, { resolution_comment: comment })
      setAlerts((prev) =>
        prev.map((a) =>
          (a.alert_id || a._id) === alertId
            ? { ...a, caregiver_resolution_comment: res.caregiver_resolution_comment }
            : a
        )
      )
      setResolvingAlertId(null)
      setResolutionComment('')
    } catch (e) {
      setResolutionError(e.message || 'Erreur lors de l\'enregistrement')
    }
  }

  const handleSeenPatient = async (alertId, seen) => {
    try {
      setSeenError('')
      const token = await getAccessTokenSilently()
      const res = await patchCaregiverAlert(token, alertId, {
        seen_patient_since_alert: seen,
        ...(seenComment.trim() ? { resolution_comment: seenComment.trim() } : {}),
      })
      setAlerts((prev) =>
        prev.map((a) =>
          (a.alert_id || a._id) === alertId
            ? {
                ...a,
                caregiver_seen_patient: res.caregiver_seen_patient,
                caregiver_seen_at: res.caregiver_seen_at,
                caregiver_resolution_comment: res.caregiver_resolution_comment ?? a.caregiver_resolution_comment,
              }
            : a
        )
      )
      setSeenAlertId(null)
      setSeenComment('')
    } catch (e) {
      setSeenError(e.message || 'Erreur lors de l\'enregistrement')
    }
  }

  return (
    <div className="caregiver-dashboard family-theme">
      <div className="main-content">
        <header className="caregiver-header">
          <div className="caregiver-header-left">
            <div>
              <h1 id="caregiver-alerts-title" className="caregiver-title">
                <TriangleAlert size={22} style={{ verticalAlign: 'middle', marginRight: '0.35rem' }} aria-hidden />
                Alertes
              </h1>
              <p className="caregiver-subtitle">
                Signalements à surveiller pour votre proche — le médecin est informé automatiquement.
              </p>
            </div>
          </div>
        </header>

        <section className="ml-panel" style={{ marginTop: '1rem' }} aria-labelledby="caregiver-alerts-title">
          <div className="ml-anomaly-header">
            <h2 id="caregiver-alerts-filters">Filtres</h2>
            <div className="ml-anomaly-filters">
              <div className="ml-filter-group" role="group" aria-label="Filtrer par statut">
                {['OPEN', 'ALL'].map((val) => (
                  <button
                    key={val}
                    type="button"
                    className={`ml-filter-btn ${statusFilter === val ? 'ml-filter-btn--active' : ''}`}
                    aria-pressed={statusFilter === val}
                    onClick={() => setStatusFilter(val)}
                  >
                    {val === 'OPEN' ? `Ouvertes${openCount ? ` (${openCount})` : ''}` : 'Toutes'}
                  </button>
                ))}
              </div>
              <div className="ml-filter-group" role="group" aria-label="Filtrer par niveau de gravité">
                <button
                  type="button"
                  className={`ml-filter-btn ${severityFilter === '' ? 'ml-filter-btn--active' : ''}`}
                  aria-pressed={severityFilter === ''}
                  onClick={() => setSeverityFilter('')}
                >
                  Tous niveaux
                </button>
                {Object.entries(SEVERITY_LEVEL_CONFIG).map(([key, cfg]) => (
                  <button
                    key={key}
                    type="button"
                    className={`ml-filter-btn ${severityFilter === key ? 'ml-filter-btn--active' : ''}`}
                    aria-pressed={severityFilter === key}
                    onClick={() => setSeverityFilter(key)}
                    style={severityFilter === key ? { borderColor: cfg.color, color: cfg.color } : undefined}
                  >
                    {cfg.label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {loading && (
            <p className="caregiver-loading" role="status" aria-live="polite">
              Chargement des alertes…
            </p>
          )}
          {!loading && error && (
            <p className="caregiver-error" role="alert">
              {error}
            </p>
          )}

          {!loading && !error && alerts.length === 0 && (
            <div className="ml-empty" role="status">
              <Info size={20} aria-hidden />
              <span>Aucune alerte {statusFilter === 'OPEN' ? 'ouverte' : ''} pour le moment.</span>
            </div>
          )}

          {!loading && !error && alerts.length > 0 && (
            <div className="ml-anomaly-table-wrap">
              <table className="ml-anomaly-table" aria-label="Liste des alertes pour votre proche">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Proche</th>
                    <th>Niveau</th>
                    <th>Résumé</th>
                    <th>Suivi</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {alerts.map((a) => {
                    const aid = a.alert_id || a._id
                    const isManual = a.alert_source === 'manual'
                    const sevCfg = getSeverityConfig(a.severity_level || (isManual ? 'URGENCY' : 'CRITICAL'))
                    const isExpanded = expandedId === aid
                    const patientName = patientNames[a.patient_id] || '-'
                    return (
                      <React.Fragment key={aid}>
                        <tr className={isManual ? 'ml-vital-row--manual' : ''}>
                          <td>{formatTime(a.created_at || a.last_breach_at)}</td>
                          <td>{patientName}</td>
                          <td>
                            <span
                              className="ml-level-badge"
                              style={{ background: sevCfg.bg, color: sevCfg.color, border: `1px solid ${sevCfg.border}` }}
                              aria-label={`Niveau ${sevCfg.label}`}
                            >
                              {sevCfg.label}
                            </span>
                            {isManual && (
                              <span className="ml-source-badge ml-source-badge--manual" title="Alerte patient" aria-label="Alerte déclenchée par le patient">
                                <Siren size={12} aria-hidden /> Patient
                              </span>
                            )}
                          </td>
                          <td>
                            <strong>{a.summary || 'Alerte'}</strong>
                            {isManual && a.patient_message && (
                              <p className="ml-patient-message">« {a.patient_message} »</p>
                            )}
                          </td>
                          <td>
                            {a.caregiver_seen_patient != null && (
                              <span className={`ml-aidant-badge ${a.caregiver_seen_patient ? 'ml-aidant-badge--yes' : 'ml-aidant-badge--no'}`}>
                                {a.caregiver_seen_patient ? 'Vu en personne' : 'Pas vu'}
                              </span>
                            )}
                            {a.caregiver_resolution_comment && (
                              <p className="ml-alert-comment">{a.caregiver_resolution_comment}</p>
                            )}
                          </td>
                          <td>
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.35rem' }}>
                              <button
                                type="button"
                                className="ml-filter-btn"
                                style={{ fontSize: '0.75rem' }}
                                aria-expanded={isExpanded}
                                aria-controls={`alert-detail-${aid}`}
                                aria-label={isExpanded ? 'Masquer le détail de l\'alerte' : 'Afficher le détail de l\'alerte'}
                                onClick={() => setExpandedId(isExpanded ? null : aid)}
                              >
                                {isExpanded ? <ChevronUp size={12} aria-hidden /> : <ChevronDown size={12} aria-hidden />}
                                Détail
                              </button>
                              <button
                                type="button"
                                className="ml-filter-btn"
                                style={{ fontSize: '0.75rem' }}
                                aria-label={`Ouvrir la fiche de ${patientName}`}
                                onClick={() => navigate(`${base}/patient/${encodeURIComponent(a.patient_id || '')}`)}
                              >
                                Fiche
                              </button>
                            </div>
                          </td>
                        </tr>
                        {isExpanded && (
                          <tr className="ml-row-expanded" id={`alert-detail-${aid}`}>
                            <td colSpan={6}>
                              <p style={{ margin: '0 0 0.75rem' }}>{a.lay_description}</p>
                              {(a.severity_level === 'URGENCY' || isManual) && (
                                <p style={{ color: '#b91c1c', fontSize: '0.875rem', marginBottom: '0.75rem' }}>
                                  <Phone size={14} style={{ verticalAlign: 'middle' }} /> En cas d&apos;urgence, composez le <strong>15</strong> (SAMU).
                                </p>
                              )}
                              <div className="caregiver-alert-actions">
                                {a.status === 'OPEN' && a.caregiver_seen_patient == null && (
                                  <button
                                    type="button"
                                    className="caregiver-alert-resolve-btn caregiver-alert-seen-btn"
                                    aria-expanded={seenAlertId === aid}
                                    onClick={() => setSeenAlertId(seenAlertId === aid ? null : aid)}
                                  >
                                    <Eye size={14} aria-hidden /> J&apos;ai vu le patient
                                  </button>
                                )}
                                {!a.caregiver_resolution_comment && a.status === 'OPEN' && (
                                  <button
                                    type="button"
                                    className="caregiver-alert-resolve-btn"
                                    aria-expanded={resolvingAlertId === aid}
                                    onClick={() => setResolvingAlertId(resolvingAlertId === aid ? null : aid)}
                                  >
                                    <CheckCircle2 size={14} aria-hidden /> Situation résolue
                                  </button>
                                )}
                              </div>
                              {seenAlertId === aid && (
                                <div className="caregiver-alert-resolve-form" role="group" aria-label="Confirmation de visite en personne">
                                  <p className="caregiver-alert-resolve-hint" id={`seen-hint-${aid}`}>Avez-vous vu votre proche en personne ?</p>
                                  <textarea
                                    className="caregiver-alert-resolve-input"
                                    value={seenComment}
                                    onChange={(e) => setSeenComment(e.target.value)}
                                    placeholder="Commentaire optionnel"
                                    rows={2}
                                    aria-labelledby={`seen-hint-${aid}`}
                                  />
                                  {seenError && <p className="caregiver-alert-error" role="alert">{seenError}</p>}
                                  <div className="caregiver-alert-resolve-btns">
                                    <button type="button" className="caregiver-alert-view-btn" onClick={() => handleSeenPatient(aid, true)}>
                                      <Eye size={14} /> Oui, vu
                                    </button>
                                    <button type="button" className="caregiver-alert-resolve-submit caregiver-alert-seen-no" onClick={() => handleSeenPatient(aid, false)}>
                                      <EyeOff size={14} /> Pas encore
                                    </button>
                                  </div>
                                </div>
                              )}
                              {resolvingAlertId === aid && (
                                <div className="caregiver-alert-resolve-form" role="group" aria-label="Résolution de l'alerte">
                                  <textarea
                                    className="caregiver-alert-resolve-input"
                                    value={resolutionComment}
                                    onChange={(e) => setResolutionComment(e.target.value)}
                                    placeholder="Que avez-vous fait ? (obligatoire)"
                                    rows={2}
                                    aria-label="Décrire les actions entreprises pour résoudre l'alerte"
                                    aria-required="true"
                                  />
                                  {resolutionError && <p className="caregiver-alert-error" role="alert">{resolutionError}</p>}
                                  <div className="caregiver-alert-resolve-btns">
                                    <button type="button" className="caregiver-alert-view-btn" onClick={() => { setResolvingAlertId(null); setResolutionComment('') }}>
                                      Annuler
                                    </button>
                                    <button type="button" className="caregiver-alert-resolve-submit" onClick={() => handleResolveAlert(aid)}>
                                      Enregistrer
                                    </button>
                                  </div>
                                </div>
                              )}
                            </td>
                          </tr>
                        )}
                      </React.Fragment>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
