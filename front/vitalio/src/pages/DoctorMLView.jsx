import React, { useEffect, useState, useCallback, useRef } from 'react'
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
  Copy,
  Ambulance,
  UserCheck,
  Siren,
  Activity,
  ChevronDown,
  ChevronUp,
} from 'lucide-react'
import { getMLModelInfo, getMLAnomalies, getDoctorAlerts, getDoctorPatients, getPatientMLAnalysis, patchDoctorAlert, apiRequest } from '../services/api'
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

/** File « ouvertes » côté UI : exclut Validée/Rejetée même si status en base/API est encore OPEN. */
function isActionableOpenVitalAlert(a) {
  const st = String(a.status || 'OPEN').toUpperCase()
  if (st !== 'OPEN') return false
  const ds = String(a.doctor_status || 'PENDING').toUpperCase()
  if (ds === 'VALIDATED' || ds === 'REJECTED') return false
  return true
}

function formatPostalAddress(addr) {
  if (!addr || typeof addr !== 'object') return ''
  const parts = [
    addr.address_line1,
    addr.address_line2,
    [addr.postal_code, addr.city].filter(Boolean).join(' ').trim(),
    addr.country,
  ].filter((p) => p && String(p).trim())
  return parts.join(', ')
}

function VitalEmergencyActions({ alert, patientName, tokenGetter, onEscalated, onNotify }) {
  const addr = alert.patient_address
  const addressText = formatPostalAddress(addr)
  const copyAddress = async () => {
    if (!addressText) {
      onNotify?.({ message: 'Aucune adresse enregistrée pour ce patient', type: 'error' })
      return
    }
    try {
      await navigator.clipboard.writeText(addressText)
      onNotify?.({ message: 'Adresse copiée', type: 'success' })
    } catch {
      onNotify?.({ message: 'Copie impossible', type: 'error' })
    }
  }
  const logSamu = async () => {
    if (!alert.alert_id) return
    try {
      const token = await tokenGetter()
      await patchDoctorAlert(token, alert.alert_id, { emergency_escalation: { type: 'samu' } })
      onNotify?.({ message: 'Escalade SAMU enregistrée dans le dossier', type: 'success' })
      onEscalated?.()
    } catch (e) {
      onNotify?.({ message: e.message || 'Échec enregistrement', type: 'error' })
    }
  }
  return (
    <div className="ml-emergency-actions">
      <a className="ml-emergency-tel" href="tel:15">
        <Phone size={14} /> 15 (SAMU)
      </a>
      {addressText ? (
        <>
          <span className="ml-emergency-address" title={addressText}>
            {patientName ? `${patientName} - ` : ''}
            {addressText}
          </span>
          <button type="button" className="ml-filter-btn" onClick={copyAddress} title="Copier l'adresse">
            <Copy size={12} /> Copier
          </button>
        </>
      ) : (
        <span className="ml-emergency-address ml-emergency-address--empty">Adresse non renseignée</span>
      )}
      <button type="button" className="ml-retrain-btn" style={{ fontSize: '0.8rem', padding: '0.35rem 0.6rem' }} onClick={logSamu}>
        <Ambulance size={14} /> Journaliser appel urgences
      </button>
    </div>
  )
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
  const [expandedAnomaly, setExpandedAnomaly] = useState(null)
  const [expandedMeasurement, setExpandedMeasurement] = useState(null)
  const [toast, setToast] = useState(null)
  const [vitalAlertNarratives, setVitalAlertNarratives] = useState({})
  const narrativeCacheRef = useRef({})
  const narrativeInflightRef = useRef(new Set())

  const patientNames = React.useMemo(() => {
    const m = {}
    patients.forEach((p) => {
      const key = p.id || p.patient_id
      if (key) m[key] = p.display_name || p.patient_id
      if (p.patient_id && p.patient_id !== key) m[p.patient_id] = p.display_name || p.patient_id
    })
    return m
  }, [patients])

  const openVitalCount = React.useMemo(
    () => vitalAlerts.filter(isActionableOpenVitalAlert).length,
    [vitalAlerts],
  )

  const displayedVitalAlerts = React.useMemo(() => {
    if (vitalStatusFilter === 'OPEN') {
      return vitalAlerts.filter(isActionableOpenVitalAlert)
    }
    return vitalAlerts
  }, [vitalAlerts, vitalStatusFilter])

  useEffect(() => {
    let cancelled = false
    if (activeTab !== 'vital') return undefined
    const ids = [...new Set(displayedVitalAlerts.map((a) => a.patient_id).filter(Boolean))]
    for (const pid of ids) {
      if (narrativeCacheRef.current[pid] !== undefined) {
        const cached = narrativeCacheRef.current[pid]
        setVitalAlertNarratives((prev) => {
          if (prev[pid]?.error && cached === null) return prev
          if (prev[pid] && !prev[pid].loading && prev[pid].summary === cached) return prev
          return {
            ...prev,
            [pid]: { loading: false, summary: cached, error: null },
          }
        })
        continue
      }
      if (narrativeInflightRef.current.has(pid)) continue
      narrativeInflightRef.current.add(pid)
      setVitalAlertNarratives((prev) => ({ ...prev, [pid]: { loading: true, summary: prev[pid]?.summary, error: null } }))
      ;(async () => {
        try {
          const token = await getAccessTokenSilently()
          const data = await getPatientMLAnalysis(token, pid, { days: 7, include_forecast: false })
          if (cancelled) return
          const s = data?.clinical_narrative_summary ?? null
          narrativeCacheRef.current[pid] = s
          narrativeInflightRef.current.delete(pid)
          setVitalAlertNarratives((prev) => ({ ...prev, [pid]: { loading: false, summary: s, error: null } }))
        } catch {
          narrativeInflightRef.current.delete(pid)
          narrativeCacheRef.current[pid] = null
          if (!cancelled) {
            setVitalAlertNarratives((prev) => ({
              ...prev,
              [pid]: { loading: false, summary: null, error: 'Synthèse 7 jours indisponible.' },
            }))
          }
        }
      })()
    }
    return () => {
      cancelled = true
    }
  }, [activeTab, displayedVitalAlerts, getAccessTokenSilently])

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

  // Rafraîchissement périodique pour afficher les nouvelles alertes (web push, MQTT, etc.)
  useEffect(() => {
    const interval = setInterval(loadData, 30000)
    return () => clearInterval(interval)
  }, [loadData])

  // Notification navigateur au chargement si des alertes ouvertes (une fois par montage)
  const hasNotifiedRef = React.useRef(false)
  useEffect(() => {
    if (loading || hasNotifiedRef.current) return
    if (openVitalCount > 0 && typeof window !== 'undefined' && 'Notification' in window) {
      hasNotifiedRef.current = true
      try {
        if (Notification.permission === 'granted') {
          new Notification('VitalIO - Alertes à traiter', {
            body: `${openVitalCount} alerte(s) vitale(s) ouverte(s) nécessitent votre attention.`,
            icon: '/favicon.ico',
          })
        } else if (Notification.permission !== 'denied') {
          Notification.requestPermission().then((p) => {
            if (p === 'granted') {
              new Notification('VitalIO - Alertes à traiter', {
                body: `${openVitalCount} alerte(s) vitale(s) ouverte(s) nécessitent votre attention.`,
                icon: '/favicon.ico',
              })
            }
          })
        }
      } catch (e) {
        console.warn('Notification non disponible:', e)
      }
    }
  }, [openVitalCount, loading])

  const handleValidate = async (anomalyId, newStatus) => {
    try {
      setValidatingId(anomalyId)
      const token = await getAccessTokenSilently()
      const res = await apiRequest(`/api/doctor/ml-anomalies/${anomalyId}`, token, {
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
      const auditHint =
        newStatus === 'validated' && res?.audit_alert_id
          ? ` - dossier alerte #${String(res.audit_alert_id).slice(-6)}`
          : ''
      setToast({
        message:
          (newStatus === 'validated' ? 'Alerte confirmée avec succès' : 'Alerte classée comme non pertinente') + auditHint,
        type: 'success',
      })
      if (newStatus === 'validated' && res?.audit_alert_id) {
        loadData()
      }
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
      await patchDoctorAlert(token, alertId, { doctor_status: doctorStatus })
      setVitalAlerts((prev) =>
        prev.map((a) =>
          (a.alert_id === alertId)
            ? {
                ...a,
                doctor_status: doctorStatus,
                status: 'RESOLVED',
                resolved_at: new Date().toISOString(),
              }
            : a,
        ),
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

  return (
    <DoctorLayout>
      <div className="doctor-ml">
        {toast && <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />}

        <header className="ml-header">
          <div>
            <h1><BrainCircuit size={28} /> Alertes</h1>
            <p>Alertes vitales et détection automatique. Validez ou rejetez les alertes, prenez contact avec l&apos;aidant ou le patient.</p>
          </div>
          <div className="ml-header-actions">
            {modelInfo && (
              <div className="ml-model-badge">
                <Info size={14} />
                <span>Version {modelInfo.version}{modelInfo.loaded ? '' : ' (indisponible)'}</span>
              </div>
            )}
          </div>
        </header>

        {loading && <div className="ml-panel">Chargement...</div>}
        {!loading && error && (
          <div className="ml-panel ml-panel--error"><ShieldAlert size={20} /> <span>{error}</span></div>
        )}

        {!loading && !error && (
          <>
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
                {displayedVitalAlerts.length === 0 ? (
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
                          <th>Type</th>
                          <th>Valeur / Seuil</th>
                          <th>Contexte mesure</th>
                          <th>Statut médecin</th>
                          <th>Aidant</th>
                          <th>Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {displayedVitalAlerts.map((a) => {
                          const docStatus = (a.doctor_status || 'PENDING').toUpperCase()
                          const dsCfg = DOCTOR_STATUS_CONFIG[docStatus] || DOCTOR_STATUS_CONFIG.PENDING
                          const patientName = patientNames[a.patient_id] || a.patient_id || '-'
                          const value = a.latest_value ?? a.value ?? '-'
                          const threshold = a.threshold ?? '-'
                          const rowKey = a.alert_id || `${a.device_id}-${a.metric}`
                          const isManual = a.alert_source === 'manual'
                          const snap = a.measurement_snapshot
                          const isMeasExpanded = expandedMeasurement === rowKey
                          return (
                            <React.Fragment key={rowKey}>
                              <tr className={isManual ? 'ml-vital-row--manual' : ''}>
                                <td>
                                  {formatTime(a.created_at || a.last_breach_at)}
                                  {isManual && (
                                    <span className="ml-source-badge ml-source-badge--manual" title="Déclenchée manuellement par le patient">
                                      <Siren size={12} /> Patient
                                    </span>
                                  )}
                                </td>
                                <td>{patientName}</td>
                                <td>
                                  {isManual
                                    ? <><Siren size={14} style={{ verticalAlign: 'middle' }} /> {a.medical_label || 'Alerte patient'}</>
                                    : (a.medical_label || a.metric)
                                  }
                                  {isManual && a.patient_message && (
                                    <p className="ml-patient-message">« {a.patient_message} »</p>
                                  )}
                                </td>
                                <td className="ml-table-mono">
                                  {isManual ? '-' : `${value} / ${threshold}`}
                                </td>
                                <td>
                                  {snap && !isManual ? (
                                    <button
                                      className="ml-filter-btn"
                                      style={{ fontSize: '0.75rem', padding: '0.2rem 0.5rem' }}
                                      onClick={() => setExpandedMeasurement(isMeasExpanded ? null : rowKey)}
                                      title="Voir contexte mesure déclenchante"
                                    >
                                      <Activity size={13} />
                                      {isMeasExpanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                                    </button>
                                  ) : <span style={{ color: '#94a3b8', fontSize: '0.8rem' }}>-</span>}
                                </td>
                                <td>
                                  <span className="ml-level-badge" style={{ background: dsCfg.bg, color: dsCfg.color }}>
                                    {dsCfg.label}
                                  </span>
                                  {a.doctor_note && (
                                    <p className="ml-doctor-note" title={a.doctor_note}>📝 {a.doctor_note.slice(0, 60)}{a.doctor_note.length > 60 ? '…' : ''}</p>
                                  )}
                                </td>
                                <td>
                                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.2rem' }}>
                                    <span
                                      className={`ml-aidant-badge ${a.caregiver_intervened ? 'ml-aidant-badge--yes' : 'ml-aidant-badge--no'}`}
                                      title={a.caregiver_intervened ? 'Aidant a laissé un commentaire' : "Pas d'intervention aidant enregistrée"}
                                    >
                                      <UserCheck size={15} />
                                      {a.caregiver_intervened ? 'Intervenu' : 'En attente'}
                                    </span>
                                    {a.caregiver_seen_patient != null && (
                                      <span
                                        className={`ml-aidant-badge ${a.caregiver_seen_patient ? 'ml-aidant-badge--yes' : 'ml-aidant-badge--no'}`}
                                        title="Aidant a-t-il vu le patient en personne depuis l'alerte ?"
                                      >
                                        {a.caregiver_seen_patient ? '👁 Vu en personne' : '👁 Pas vu en personne'}
                                      </span>
                                    )}
                                    {a.caregiver_resolution_comment && (
                                      <p className="ml-alert-comment">{a.caregiver_resolution_comment}</p>
                                    )}
                                  </div>
                                </td>
                                <td>
                                  <div className="ml-action-btns" style={{ flexWrap: 'wrap', gap: '0.35rem' }}>
                                    {(docStatus === 'PENDING') && (
                                      <>
                                        <button
                                          className="ml-action-btn ml-action-btn--validate"
                                          onClick={() => handleValidateVital(a.alert_id, 'VALIDATED')}
                                          disabled={validatingVitalId === a.alert_id}
                                          title="Valider - alerte cliniquement retenue"
                                        >
                                          <ThumbsUp size={15} />
                                        </button>
                                        <button
                                          className="ml-action-btn ml-action-btn--reject"
                                          onClick={() => handleValidateVital(a.alert_id, 'REJECTED')}
                                          disabled={validatingVitalId === a.alert_id}
                                          title="Rejeter - faux positif / artefact"
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
                              {isMeasExpanded && snap && (
                                <tr className="ml-measurement-context-row">
                                  <td colSpan={8}>
                                    <div className="ml-measurement-context">
                                      <strong><Activity size={14} /> Mesure déclenchante</strong>
                                      <span className="ml-meas-ts">{formatTime(snap.measured_at)}</span>
                                      <span className="ml-meas-item">FC : <strong>{snap.heart_rate ?? '-'} bpm</strong></span>
                                      <span className="ml-meas-item">SpO₂ : <strong>{snap.spo2 ?? '-'} %</strong></span>
                                      <span className="ml-meas-item">Temp. : <strong>{snap.temperature ?? '-'} °C</strong></span>
                                      <span className="ml-meas-item">Qualité signal : <strong>{snap.signal_quality ?? '-'}</strong></span>
                                      {snap.status && snap.status !== 'VALID' && (
                                        <span className="ml-meas-item ml-meas-item--warn">Statut mesure : {snap.status}</span>
                                      )}
                                    </div>
                                  </td>
                                </tr>
                              )}
                              {a.status === 'OPEN' && (
                                <tr className="ml-vital-emergency-row">
                                  <td colSpan={8}>
                                    <VitalEmergencyActions
                                      alert={a}
                                      patientName={patientName}
                                      tokenGetter={getAccessTokenSilently}
                                      onEscalated={loadData}
                                      onNotify={setToast}
                                    />
                                    {Array.isArray(a.emergency_escalations) && a.emergency_escalations.length > 0 && (
                                      <div className="ml-escalation-log">
                                        <strong>Escalades :</strong>
                                        {' '}
                                        {a.emergency_escalations.map((e, i) => (
                                          <span key={i}>
                                            {e.type} ({e.at ? formatTime(e.at) : '?'})
                                            {i < a.emergency_escalations.length - 1 ? ' · ' : ''}
                                          </span>
                                        ))}
                                      </div>
                                    )}
                                  </td>
                                </tr>
                              )}
                              {a.patient_id && (
                                <tr className="ml-vital-context-summary-row">
                                  <td colSpan={8}>
                                    <div className="ml-alert-context-stack">
                                      <div className="ml-alert-context-section">
                                        <strong>Synthèse liée à cette alerte</strong>
                                        {a.medical_label && (
                                          <p style={{ fontWeight: 600, marginBottom: '0.35rem', color: '#0f172a' }}>{a.medical_label}</p>
                                        )}
                                        <p>{a.medical_description || '—'}</p>
                                        {a.alert_source === 'manual' && a.patient_message && (
                                          <p style={{ marginTop: '0.5rem', fontStyle: 'italic', color: '#475569' }}>
                                            Message patient : « {a.patient_message} »
                                          </p>
                                        )}
                                      </div>
                                      <div className="ml-alert-context-section ml-alert-context-section--weekly">
                                        <strong>Historique des constantes (7 derniers jours)</strong>
                                        {vitalAlertNarratives[a.patient_id]?.loading && (
                                          <p className="ml-weekly-narrative-pre" style={{ color: '#64748b' }}>Chargement de la synthèse…</p>
                                        )}
                                        {vitalAlertNarratives[a.patient_id]?.error && !vitalAlertNarratives[a.patient_id]?.loading && (
                                          <p className="ml-weekly-narrative-pre" style={{ color: '#b45309' }}>
                                            {vitalAlertNarratives[a.patient_id].error}
                                          </p>
                                        )}
                                        {!vitalAlertNarratives[a.patient_id]?.loading && vitalAlertNarratives[a.patient_id]?.summary?.text && (
                                          <>
                                            <p className="ml-weekly-narrative-pre">{vitalAlertNarratives[a.patient_id].summary.text}</p>
                                            {vitalAlertNarratives[a.patient_id].summary.recommended_action && (
                                              <p className="ml-weekly-narrative-foot">
                                                {vitalAlertNarratives[a.patient_id].summary.recommended_action}
                                              </p>
                                            )}
                                          </>
                                        )}
                                        {!vitalAlertNarratives[a.patient_id]?.loading
                                          && !vitalAlertNarratives[a.patient_id]?.error
                                          && !vitalAlertNarratives[a.patient_id]?.summary?.text && (
                                          <p className="ml-weekly-narrative-pre" style={{ color: '#94a3b8' }}>
                                            Pas assez de données sur 7 jours pour générer la synthèse narrative.
                                          </p>
                                        )}
                                      </div>
                                    </div>
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
