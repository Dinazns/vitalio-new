import React, { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth0 } from '@auth0/auth0-react'
import {
  BrainCircuit,
  ShieldAlert,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Info,
  ThumbsUp,
  ThumbsDown,
  Stethoscope,
  Clock,
  ArrowRight,
  Heart,
  Phone,
} from 'lucide-react'
import { getMLModelInfo, getMLAnomalies, getDoctorAlerts, getDoctorPatients, patchDoctorAlert, apiRequest } from '../services/api'
import DoctorLayout from '../components/DoctorLayout'

const URGENCY_CONFIG = {
  immediate: { color: '#b91c1c', bg: '#fef2f2', label: 'Immédiat' },
  priority:  { color: '#b45309', bg: '#fffbeb', label: 'Prioritaire' },
  routine:   { color: '#047857', bg: '#ecfdf5', label: 'Routine' },
}

const LEVEL_CONFIG = {
  normal:   { color: '#047857', bg: '#ecfdf5', label: 'Normal',       Icon: CheckCircle2 },
  warning:  { color: '#b45309', bg: '#fffbeb', label: 'Surveillance', Icon: AlertTriangle },
  critical: { color: '#b91c1c', bg: '#fef2f2', label: 'Critique',     Icon: XCircle },
}

const STATUS_CONFIG = {
  pending:   { color: '#1d4ed8', bg: '#eff6ff', label: 'En attente' },
  validated: { color: '#047857', bg: '#ecfdf5', label: 'Validée' },
  rejected:  { color: '#94a3b8', bg: '#f8fafc', label: 'Rejetée' },
}

const DOCTOR_STATUS_CONFIG = {
  PENDING:   { color: '#1d4ed8', bg: '#eff6ff', label: 'En attente' },
  VALIDATED: { color: '#047857', bg: '#ecfdf5', label: 'Validée' },
  REJECTED:  { color: '#94a3b8', bg: '#f8fafc', label: 'Rejetée' },
}

const formatTime = (iso) => {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function Toast({ message, type, onClose }) {
  useEffect(() => {
    const timer = setTimeout(onClose, 3500)
    return () => clearTimeout(timer)
  }, [onClose])
  const bg = type === 'success' ? '#ecfdf5' : '#fef2f2'
  const border = type === 'success' ? '#6ee7b7' : '#fecaca'
  const color = type === 'success' ? '#047857' : '#b91c1c'
  return (
    <div className="ml-toast" style={{ background: bg, borderColor: border, color }}>
      {type === 'success' ? <CheckCircle2 size={16} /> : <XCircle size={16} />}
      <span>{message}</span>
    </div>
  )
}

function SuggestionCard({ anomaly }) {
  const urgCfg = URGENCY_CONFIG[anomaly.urgency] || URGENCY_CONFIG.routine
  if (!anomaly.recommended_action && !anomaly.clinical_reasoning?.length) return null
  return (
    <div className="ml-suggestion-card">
      <div className="ml-suggestion-header">
        <Stethoscope size={15} />
        <span className="ml-suggestion-title">Recommandation clinique</span>
        <span className="ml-urgency-badge" style={{ background: urgCfg.bg, color: urgCfg.color, borderColor: urgCfg.color }}>
          {urgCfg.label}
        </span>
      </div>
      {anomaly.recommended_action && (
        <p className="ml-suggestion-action">
          <ArrowRight size={13} /> {anomaly.recommended_action}
        </p>
      )}
      {anomaly.clinical_reasoning?.length > 0 && (
        <ul className="ml-suggestion-reasoning">
          {anomaly.clinical_reasoning.map((r, i) => <li key={i}>{r}</li>)}
        </ul>
      )}
    </div>
  )
}

export default function DoctorMLView() {
  const navigate = useNavigate()
  const { getAccessTokenSilently } = useAuth0()
  const [activeTab, setActiveTab] = useState('vital') // 'vital' | 'ml'
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [modelInfo, setModelInfo] = useState(null)
  const [anomalies, setAnomalies] = useState([])
  const [vitalAlerts, setVitalAlerts] = useState([])
  const [patients, setPatients] = useState([])
  const [vitalStatusFilter, setVitalStatusFilter] = useState('OPEN')
  const [statusFilter, setStatusFilter] = useState('')
  const [severityFilter, setSeverityFilter] = useState('critical')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [validatingId, setValidatingId] = useState(null)
  const [validatingVitalId, setValidatingVitalId] = useState(null)
  const [retraining, setRetraining] = useState(false)
  const [retrainResult, setRetrainResult] = useState(null)
  const [expandedAnomaly, setExpandedAnomaly] = useState(null)
  const [toast, setToast] = useState(null)

  const patientNames = React.useMemo(() => {
    const m = {}
    patients.forEach((p) => {
      const key = p.id || p.patient_id
      if (key) m[key] = p.display_name || p.patient_id
      if (p.patient_id && p.patient_id !== key) m[p.patient_id] = p.display_name || p.patient_id
    })
    return m
  }, [patients])

  const loadData = useCallback(async () => {
    try {
      setLoading(true)
      setError('')
      const token = await getAccessTokenSilently()
      const anomalyParams = { limit: 100 }
      if (statusFilter) anomalyParams.status = statusFilter
      if (severityFilter) anomalyParams.severity = severityFilter
      if (dateFrom) anomalyParams.from_date = dateFrom
      if (dateTo) anomalyParams.to_date = dateTo

      const [mlInfo, anomalyRes, vitalRes, patientsRes] = await Promise.all([
        getMLModelInfo().catch(() => null),
        getMLAnomalies(token, anomalyParams).catch(() => ({ anomalies: [] })),
        getDoctorAlerts(token, { status: vitalStatusFilter, limit: 100 }).catch(() => ({ alerts: [] })),
        getDoctorPatients(token).catch(() => ({ patients: [] })),
      ])
      setModelInfo(mlInfo)
      setAnomalies(Array.isArray(anomalyRes.anomalies) ? anomalyRes.anomalies : [])
      setVitalAlerts(Array.isArray(vitalRes.alerts) ? vitalRes.alerts : [])
      setPatients(Array.isArray(patientsRes.patients) ? patientsRes.patients : [])
    } catch (e) {
      setError(e.message || 'Erreur de chargement')
    } finally {
      setLoading(false)
    }
  }, [getAccessTokenSilently, statusFilter, severityFilter, dateFrom, dateTo, vitalStatusFilter])

  useEffect(() => { loadData() }, [loadData])

  // Notification navigateur au chargement si des alertes ouvertes (une fois par montage)
  const hasNotifiedRef = React.useRef(false)
  useEffect(() => {
    if (loading || hasNotifiedRef.current) return
    const openCount = vitalAlerts.filter((a) => a.status === 'OPEN').length
    if (openCount > 0 && typeof window !== 'undefined' && 'Notification' in window) {
      hasNotifiedRef.current = true
      try {
        if (Notification.permission === 'granted') {
          new Notification('VitalIO - Alertes à traiter', {
            body: `${openCount} alerte(s) vitale(s) ouverte(s) nécessitent votre attention.`,
            icon: '/favicon.ico',
          })
        } else if (Notification.permission !== 'denied') {
          Notification.requestPermission().then((p) => {
            if (p === 'granted') {
              new Notification('VitalIO - Alertes à traiter', {
                body: `${openCount} alerte(s) vitale(s) ouverte(s) nécessitent votre attention.`,
                icon: '/favicon.ico',
              })
            }
          })
        }
      } catch (e) {
        console.warn('Notification non disponible:', e)
      }
    }
  }, [vitalAlerts, loading])

  const handleValidate = async (anomalyId, newStatus) => {
    try {
      setValidatingId(anomalyId)
      const token = await getAccessTokenSilently()
      await apiRequest(`/api/doctor/ml-anomalies/${anomalyId}`, token, {
        method: 'PATCH',
        body: JSON.stringify({ status: newStatus }),
      })
      setAnomalies((prev) =>
        prev.map((a) =>
          (a.anomaly_id === anomalyId)
            ? { ...a, status: newStatus }
            : a
        )
      )
      setToast({
        message: newStatus === 'validated' ? 'Alerte confirmée avec succès' : 'Alerte classée comme non pertinente',
        type: 'success',
      })
    } catch (e) {
      setToast({ message: e.message || 'Erreur lors du traitement', type: 'error' })
    } finally {
      setValidatingId(null)
    }
  }

  const handleValidateVital = async (alertId, doctorStatus) => {
    try {
      setValidatingVitalId(alertId)
      const token = await getAccessTokenSilently()
      await patchDoctorAlert(token, alertId, doctorStatus)
      setVitalAlerts((prev) =>
        prev.map((a) =>
          (a.alert_id === alertId) ? { ...a, doctor_status: doctorStatus } : a
        )
      )
      setToast({
        message: doctorStatus === 'VALIDATED' ? 'Alerte validée' : 'Alerte rejetée',
        type: 'success',
      })
    } catch (e) {
      setToast({ message: e.message || 'Erreur lors du traitement', type: 'error' })
    } finally {
      setValidatingVitalId(null)
    }
  }

  const handleRetrain = async () => {
    try {
      setRetraining(true)
      setRetrainResult(null)
      const token = await getAccessTokenSilently()
      const result = await apiRequest('/api/admin/ml/retrain', token, {
        method: 'POST',
        body: JSON.stringify({ days: 30 }),
      })
      setRetrainResult(result)
      const mlInfo = await getMLModelInfo().catch(() => null)
      setModelInfo(mlInfo)
    } catch (e) {
      setRetrainResult({ error: e.message })
    } finally {
      setRetraining(false)
    }
  }

  return (
    <DoctorLayout>
      <div className="doctor-ml">
        {toast && <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />}

        <header className="ml-header">
          <div>
            <h1><BrainCircuit size={28} /> Alertes</h1>
            <p>Alertes vitales (FC, SpO2, température) et détection IA. Validez ou rejetez les alertes, prenez contact avec l&apos;aidant ou le patient.</p>
          </div>
          <div className="ml-header-actions">
            {modelInfo && (
              <div className="ml-model-badge">
                <Info size={14} />
                <span>Version {modelInfo.version}{modelInfo.loaded ? '' : ' (indisponible)'}</span>
              </div>
            )}
            <button
              className="ml-retrain-btn"
              onClick={handleRetrain}
              disabled={retraining}
            >
              {retraining ? 'Mise à jour...' : 'Mettre à jour'}
            </button>
          </div>
        </header>

        {retrainResult && (
          <div className={`ml-panel ${retrainResult.error ? 'ml-panel--error' : 'ml-panel--success'}`}>
            {retrainResult.error
              ? <><ShieldAlert size={18} /> <span>{retrainResult.error}</span></>
              : <><CheckCircle2 size={18} /> <span>Système mis à jour (version {retrainResult.version}, {retrainResult.n_samples} mesures intégrées)</span></>
            }
          </div>
        )}

        {loading && <div className="ml-panel">Chargement...</div>}
        {!loading && error && (
          <div className="ml-panel ml-panel--error"><ShieldAlert size={20} /> <span>{error}</span></div>
        )}

        {!loading && !error && (
          <>
            <div className="ml-tabs">
              <button
                className={`ml-tab ${activeTab === 'vital' ? 'ml-tab--active' : ''}`}
                onClick={() => setActiveTab('vital')}
              >
                <Heart size={18} /> Alertes vitales
                {vitalAlerts.filter((a) => a.status === 'OPEN').length > 0 && (
                  <span className="ml-tab-badge">{vitalAlerts.filter((a) => a.status === 'OPEN').length}</span>
                )}
              </button>
              <button
                className={`ml-tab ${activeTab === 'ml' ? 'ml-tab--active' : ''}`}
                onClick={() => setActiveTab('ml')}
              >
                <BrainCircuit size={18} /> Alertes IA
              </button>
            </div>

            {activeTab === 'vital' && (
              <section className="ml-panel">
                <div className="ml-anomaly-header">
                  <h2><Heart size={18} /> Alertes vitales (seuils)</h2>
                  <div className="ml-anomaly-filters">
                    <div className="ml-filter-group">
                      {['OPEN', 'ALL'].map((val) => (
                        <button
                          key={val}
                          className={`ml-filter-btn ${vitalStatusFilter === val ? 'ml-filter-btn--active' : ''}`}
                          onClick={() => setVitalStatusFilter(val)}
                        >
                          {val === 'OPEN' ? 'Ouvertes' : 'Toutes'}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
                {vitalAlerts.length === 0 ? (
                  <div className="ml-empty">
                    <Info size={20} />
                    <span>Aucune alerte vitale {vitalStatusFilter === 'OPEN' ? 'ouverte' : ''}.</span>
                  </div>
                ) : (
                  <div className="ml-anomaly-table-wrap">
                    <table className="ml-anomaly-table">
                      <thead>
                        <tr>
                          <th>Date</th>
                          <th>Patient</th>
                          <th>Type de défaillance</th>
                          <th>Valeur / Seuil</th>
                          <th>Statut médecin</th>
                          <th>Commentaire aidant</th>
                          <th>Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {vitalAlerts.map((a) => {
                          const docStatus = (a.doctor_status || 'PENDING').toUpperCase()
                          const dsCfg = DOCTOR_STATUS_CONFIG[docStatus] || DOCTOR_STATUS_CONFIG.PENDING
                          const patientName = patientNames[a.patient_id] || a.patient_id || '-'
                          const value = a.latest_value ?? a.value ?? '-'
                          const threshold = a.threshold ?? '-'
                          return (
                            <tr key={a.alert_id || a.device_id + a.metric}>
                              <td>{formatTime(a.created_at || a.last_breach_at)}</td>
                              <td>{patientName}</td>
                              <td>{a.medical_label || a.metric}</td>
                              <td className="ml-table-mono">{value} / {threshold}</td>
                              <td>
                                <span className="ml-level-badge" style={{ background: dsCfg.bg, color: dsCfg.color }}>
                                  {dsCfg.label}
                                </span>
                              </td>
                              <td className="ml-alert-comment">
                                {a.caregiver_resolution_comment || '-'}
                              </td>
                              <td>
                                <div className="ml-action-btns" style={{ flexWrap: 'wrap', gap: '0.35rem' }}>
                                  {(docStatus === 'PENDING') && (
                                    <>
                                      <button
                                        className="ml-action-btn ml-action-btn--validate"
                                        onClick={() => handleValidateVital(a.alert_id, 'VALIDATED')}
                                        disabled={validatingVitalId === a.alert_id}
                                        title="Valider l'alerte"
                                      >
                                        <ThumbsUp size={15} />
                                      </button>
                                      <button
                                        className="ml-action-btn ml-action-btn--reject"
                                        onClick={() => handleValidateVital(a.alert_id, 'REJECTED')}
                                        disabled={validatingVitalId === a.alert_id}
                                        title="Rejeter l'alerte"
                                      >
                                        <ThumbsDown size={15} />
                                      </button>
                                    </>
                                  )}
                                  {docStatus === 'VALIDATED' && (
                                    <span className="ml-table-validated">Validée</span>
                                  )}
                                  {docStatus === 'REJECTED' && (
                                    <span className="ml-table-validated">Rejetée</span>
                                  )}
                                  {a.patient_id && (
                                    <button
                                      className="ml-action-btn ml-action-btn--contact"
                                      onClick={() => navigate(`/doctor/patient/${encodeURIComponent(a.patient_id)}`)}
                                      title="Prendre contact (voir patient, aidant)"
                                    >
                                      <Phone size={15} />
                                    </button>
                                  )}
                                </div>
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            )}

            {activeTab === 'ml' && (
            <section className="ml-panel">
              <div className="ml-anomaly-header">
                <h2><AlertTriangle size={18} /> Alertes (IA)</h2>
                <div className="ml-anomaly-filters">
                  <div className="ml-filter-group">
                    {['', 'pending', 'validated', 'rejected'].map((val) => (
                      <button
                        key={val}
                        className={`ml-filter-btn ${statusFilter === val ? 'ml-filter-btn--active' : ''}`}
                        onClick={() => setStatusFilter(val)}
                      >
                        {val === '' ? 'Toutes' : STATUS_CONFIG[val]?.label || val}
                      </button>
                    ))}
                  </div>
                  <div className="ml-filter-group">
                    <button
                      className={`ml-filter-btn ${severityFilter === '' ? 'ml-filter-btn--active' : ''}`}
                      onClick={() => setSeverityFilter('')}
                    >
                      Tous niveaux
                    </button>
                    <button
                      className={`ml-filter-btn ${severityFilter === 'critical' ? 'ml-filter-btn--active' : ''}`}
                      onClick={() => setSeverityFilter('critical')}
                    >
                      <XCircle size={12} /> Critiques uniquement
                    </button>
                  </div>
                  <div className="ml-date-filters">
                    <Clock size={14} />
                    <input
                      type="date"
                      className="ml-date-input"
                      value={dateFrom}
                      onChange={(e) => setDateFrom(e.target.value)}
                      placeholder="Du"
                    />
                    <span className="ml-date-sep">→</span>
                    <input
                      type="date"
                      className="ml-date-input"
                      value={dateTo}
                      onChange={(e) => setDateTo(e.target.value)}
                      placeholder="Au"
                    />
                    {(dateFrom || dateTo) && (
                      <button className="ml-filter-btn" onClick={() => { setDateFrom(''); setDateTo('') }}>
                        Réinitialiser
                      </button>
                    )}
                  </div>
                </div>
              </div>

              {anomalies.length === 0 ? (
                <div className="ml-empty">
                  <Info size={20} />
                  <span>
                    Aucune alerte
                    {severityFilter === 'critical' ? ' critique' : ''}
                    {statusFilter ? ` avec le statut « ${STATUS_CONFIG[statusFilter]?.label} »` : ' détectée'}.
                  </span>
                </div>
              ) : (
                <div className="ml-anomaly-table-wrap">
                  <table className="ml-anomaly-table">
                    <thead>
                      <tr>
                        <th>Date</th>
                        <th>Capteur</th>
                        <th>Indice de risque</th>
                        <th>Niveau</th>
                        <th>Statut</th>
                        <th>Recommandation</th>
                        <th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {anomalies.map((a, i) => {
                        const lvlCfg = LEVEL_CONFIG[a.anomaly_level] || LEVEL_CONFIG.warning
                        const stCfg = STATUS_CONFIG[a.status] || STATUS_CONFIG.pending
                        const id = a.anomaly_id || `row-${i}`
                        const isExpanded = expandedAnomaly === id
                        const hasSuggestion = a.recommended_action || a.clinical_reasoning?.length > 0
                        return (
                          <React.Fragment key={id}>
                            <tr className={isExpanded ? 'ml-row-expanded' : ''}>
                              <td>{formatTime(a.measured_at || a.created_at)}</td>
                              <td className="ml-table-mono">{a.device_id || '-'}</td>
                              <td>{(a.anomaly_score ?? 0).toFixed(3)}</td>
                              <td>
                                <span className="ml-level-badge" style={{ background: lvlCfg.bg, color: lvlCfg.color }}>
                                  {lvlCfg.label}
                                </span>
                              </td>
                              <td>
                                <span className="ml-level-badge" style={{ background: stCfg.bg, color: stCfg.color }}>
                                  {stCfg.label}
                                </span>
                              </td>
                              <td>
                                {hasSuggestion ? (
                                  <button
                                    className="ml-suggestion-toggle"
                                    onClick={() => setExpandedAnomaly(isExpanded ? null : id)}
                                  >
                                    <Stethoscope size={14} />
                                    {isExpanded ? 'Masquer' : 'Voir'}
                                  </button>
                                ) : (
                                  <span className="ml-table-mono" style={{ color: '#94a3b8' }}>-</span>
                                )}
                              </td>
                              <td>
                                {a.status === 'pending' && (
                                  <div className="ml-action-btns">
                                    <button
                                      className="ml-action-btn ml-action-btn--validate"
                                      onClick={() => handleValidate(id, 'validated')}
                                      disabled={validatingId === id}
                                      title="Confirmer l'alerte"
                                    >
                                      <ThumbsUp size={15} />
                                    </button>
                                    <button
                                      className="ml-action-btn ml-action-btn--reject"
                                      onClick={() => handleValidate(id, 'rejected')}
                                      disabled={validatingId === id}
                                      title="Classer comme non pertinente"
                                    >
                                      <ThumbsDown size={15} />
                                    </button>
                                  </div>
                                )}
                                {a.status !== 'pending' && (
                                  <span className="ml-table-validated">
                                    {a.status === 'validated' ? 'Confirmée' : 'Non pertinente'}
                                  </span>
                                )}
                              </td>
                            </tr>
                            {isExpanded && hasSuggestion && (
                              <tr className="ml-suggestion-row">
                                <td colSpan={7}>
                                  <SuggestionCard anomaly={a} />
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
            )}
          </>
        )}
      </div>
    </DoctorLayout>
  )
}
