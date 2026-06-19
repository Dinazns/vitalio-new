import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth0 } from '@auth0/auth0-react'
import { Wind, Thermometer, HeartPulse, ShieldAlert, Siren, History, ChevronDown } from 'lucide-react'
import {
  getLatestPatientFeedback,
  getPatientData,
  getPatientDevice,
  getPatientProfile,
  triggerManualAlert,
} from '../services/api'
import { resolvePatientDisplayName } from '../utils/displayName'
import PatientLayout from '../components/PatientLayout'
import {
  isPatientWelcomeDone,
  markPatientWelcomeDone,
} from '../constants/patientWelcome'
import { getFeedbackSeverityLabel } from '../constants/feedbackSeverity'
import { formatMeasurementQualityHint, formatMeasurementQualityLabel } from '../utils/measurementStatus'
import {
  formatRelativeMeasurementTime,
  getVitalStatus,
  MEASUREMENT_DURATION_SEC,
} from '../utils/vitalStatus'
import VitalSignCard from '../components/patient/VitalSignCard'
import VitalTrendChart from '../components/patient/VitalTrendChart'
import OverallStatusBanner from '../components/patient/OverallStatusBanner'
import MeasurementGuide from '../components/patient/MeasurementGuide'

export default function PatientView() {
  const navigate = useNavigate()
  const { user, getAccessTokenSilently } = useAuth0()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [measurements, setMeasurements] = useState([])
  const [feedback, setFeedback] = useState([])
  const [profile, setProfile] = useState(null)
  const [hasDevice, setHasDevice] = useState(false)
  const [alertStep, setAlertStep] = useState('idle')
  const [alertMessage, setAlertMessage] = useState('')
  const [alertError, setAlertError] = useState('')
  const [historyExpanded, setHistoryExpanded] = useState(false)
  const [simulateUrgentAlert, setSimulateUrgentAlert] = useState(false)
  const [measuring, setMeasuring] = useState(false)
  const [secondsLeft, setSecondsLeft] = useState(MEASUREMENT_DURATION_SEC)
  const [measurementNotice, setMeasurementNotice] = useState('')
  const measurementBaselineRef = useRef(null)

  const refreshMeasurements = useCallback(async () => {
    const token = await getAccessTokenSilently()
    const data = await getPatientData(token)
    const rows = Array.isArray(data.measurements) ? data.measurements : []
    setMeasurements(rows)
    return rows
  }, [getAccessTokenSilently])

  useEffect(() => {
    let cancelled = false
    const userId = user?.sub
    if (isPatientWelcomeDone(userId)) return undefined
    ;(async () => {
      try {
        const token = await getAccessTokenSilently()
        const [profileRes, deviceRes] = await Promise.all([
          getPatientProfile(token).catch(() => ({ profile: null })),
          getPatientDevice(token).catch(() => ({ device_id: null })),
        ])
        if (cancelled) return
        const profileData = profileRes?.profile ?? profileRes
        const linked = Boolean(deviceRes?.device_enrolled)
        const onboarded = Boolean(profileData?.onboarding_completed)
        if (linked && onboarded) {
          markPatientWelcomeDone(userId)
          return
        }
        navigate('/patient/bienvenue', { replace: true })
      } catch {
        /* API indisponible : ne pas bloquer l'accès au tableau de bord */
      }
    })()
    return () => {
      cancelled = true
    }
  }, [getAccessTokenSilently, navigate, user?.sub])

  useEffect(() => {
    let mounted = true

    const fetchData = async () => {
      try {
        setLoading(true)
        setError('')
        const token = await getAccessTokenSilently()
        const feedbackPromise = user?.sub
          ? getLatestPatientFeedback(token, user.sub, 5)
          : Promise.resolve({ feedback: [] })
        const [data, feedbackRes, profileRes, deviceRes] = await Promise.all([
          getPatientData(token),
          feedbackPromise,
          getPatientProfile(token).catch(() => ({ profile: null, doctors: [], caregivers: [] })),
          getPatientDevice(token).catch(() => ({ device_id: null })),
        ])
        if (mounted) {
          setMeasurements(Array.isArray(data.measurements) ? data.measurements : [])
          setFeedback(Array.isArray(feedbackRes.feedback) ? feedbackRes.feedback : [])
          const profileData = profileRes?.profile ?? profileRes
          const doctors = profileRes?.doctors ?? profileData?.doctors ?? []
          const caregivers = profileRes?.caregivers ?? profileData?.caregivers ?? []
          setProfile(profileData ? { ...profileData, doctors, caregivers } : null)
          setHasDevice(Boolean(deviceRes?.device_enrolled))
        }
      } catch (fetchError) {
        if (mounted) {
          setError(fetchError.message || "Impossible de charger vos mesures")
        }
      } finally {
        if (mounted) {
          setLoading(false)
        }
      }
    }

    fetchData()
    return () => {
      mounted = false
    }
  }, [getAccessTokenSilently, user?.sub])

  useEffect(() => {
    if (!measuring) return undefined

    const pollId = window.setInterval(async () => {
      try {
        const rows = await refreshMeasurements()
        const baseline = measurementBaselineRef.current
        const newest = rows[0]?.timestamp
        if (baseline && newest && newest !== baseline) {
          setMeasuring(false)
          setSecondsLeft(MEASUREMENT_DURATION_SEC)
          setMeasurementNotice('Nouvelle mesure reçue.')
        }
      } catch {
        /* ignore polling errors */
      }
    }, 5000)

    const tickId = window.setInterval(() => {
      setSecondsLeft((prev) => prev - 1)
    }, 1000)

    return () => {
      window.clearInterval(pollId)
      window.clearInterval(tickId)
    }
  }, [measuring, refreshMeasurements])

  useEffect(() => {
    if (!measuring || secondsLeft > 0) return
    setMeasuring(false)
    setSecondsLeft(MEASUREMENT_DURATION_SEC)
    setMeasurementNotice('Mesure terminée. Consultez vos résultats ci-dessus.')
    refreshMeasurements().catch(() => {})
  }, [measuring, secondsLeft, refreshMeasurements])

  const handleStartMeasurement = () => {
    measurementBaselineRef.current = measurements[0]?.timestamp ?? null
    setMeasurementNotice('')
    setSecondsLeft(MEASUREMENT_DURATION_SEC)
    setMeasuring(true)
  }

  const handleSendAlert = async () => {
    setAlertStep('sending')
    setAlertError('')
    try {
      const token = await getAccessTokenSilently()
      const trimmed = alertMessage.trim()
      const message = simulateUrgentAlert
        ? (trimmed ? `[simulation] ${trimmed}` : '[simulation] Alerte urgente test')
        : trimmed
      await triggerManualAlert(token, message)
      setAlertStep('sent')
      setAlertMessage('')
      setSimulateUrgentAlert(false)
    } catch (e) {
      const waitMatch = (e.message || '').match(/(\d+)\s*secondes?/)
      if (waitMatch) {
        setAlertError(`Veuillez patienter ${parseInt(waitMatch[1], 10)} secondes avant de renvoyer une alerte.`)
      } else {
        setAlertError(e.message || "Erreur lors de l'envoi de l'alerte.")
      }
      setAlertStep('error')
    }
  }

  const latest = measurements[0]
  const previous = measurements[1]
  const displayName = resolvePatientDisplayName({ profile, user })

  const vitalStatuses = useMemo(
    () => [
      getVitalStatus('spo2', latest?.spo2),
      getVitalStatus('heart_rate', latest?.heart_rate),
      getVitalStatus('temperature', latest?.temperature),
    ],
    [latest],
  )

  const lastMeasurementLabel = formatRelativeMeasurementTime(latest?.timestamp)

  return (
    <PatientLayout>
      <div className="patient-container patient-theme">
        <main className="patient-dashboard">
          <header className="patient-header">
            <h1>{displayName ? `Bonjour ${displayName}` : 'Bonjour'}</h1>
            <p>Vos constantes vitales en un coup d&apos;œil.</p>
          </header>

          {loading && <div className="panel">Chargement des mesures…</div>}

          {!loading && error && (
            <div className="panel panel-error">
              <ShieldAlert size={20} />
              <span>{error}</span>
            </div>
          )}

          {!loading && !error && (
            <>
              <OverallStatusBanner statuses={vitalStatuses} />

              <section className="vital-cards" aria-label="Constantes vitales actuelles">
                <VitalSignCard
                  vitalKey="spo2"
                  label="SpO₂"
                  value={latest?.spo2}
                  previousValue={previous?.spo2}
                  Icon={Wind}
                />
                <VitalSignCard
                  vitalKey="heart_rate"
                  label="Fréquence cardiaque"
                  value={latest?.heart_rate}
                  previousValue={previous?.heart_rate}
                  Icon={HeartPulse}
                />
                <VitalSignCard
                  vitalKey="temperature"
                  label="Température"
                  value={latest?.temperature}
                  previousValue={previous?.temperature}
                  Icon={Thermometer}
                />
              </section>

              {lastMeasurementLabel && (
                <p className="vital-last-measurement" role="status">
                  Dernière mesure : {lastMeasurementLabel}
                </p>
              )}

              <section className="panel">
                <div className="panel-title">
                  <h2>Tendances - 7 derniers jours</h2>
                </div>
                <VitalTrendChart measurements={measurements} />
              </section>

              <MeasurementGuide
                measuring={measuring}
                secondsLeft={secondsLeft}
                onStart={handleStartMeasurement}
                disabled={!hasDevice || measuring}
              />

              {measurementNotice && (
                <p className="panel-measurement-notice" role="status">{measurementNotice}</p>
              )}

              {!hasDevice && (
                <p className="panel-measurement-warning">
                  Associez votre boîtier dans Mon boîtier pour lancer une mesure.
                </p>
              )}

              <section className={`panel panel--collapsible ${historyExpanded ? 'panel--open' : 'panel--collapsed'}`}>
                <button
                  type="button"
                  className="panel-collapsible-toggle"
                  onClick={() => setHistoryExpanded((open) => !open)}
                  aria-expanded={historyExpanded}
                  aria-controls="patient-measurements-history"
                >
                  <div className="panel-title">
                    <h2><History size={18} aria-hidden /> Historique de mes mesures</h2>
                    <span>{measurements.length} mesure(s)</span>
                  </div>
                  <ChevronDown
                    size={20}
                    className={`panel-collapsible-chevron ${historyExpanded ? 'panel-collapsible-chevron--open' : ''}`}
                    aria-hidden
                  />
                </button>
                {historyExpanded && (
                  <div id="patient-measurements-history" className="panel-collapsible-body">
                    <div className="patient-measurements-table-wrap">
                      <table className="patient-measurements-table">
                        <thead>
                          <tr>
                            <th>Date</th>
                            <th>SpO₂</th>
                            <th>FC</th>
                            <th>Température</th>
                            <th>Qualité</th>
                          </tr>
                        </thead>
                        <tbody>
                          {measurements.map((measurement, index) => (
                            <tr key={`${measurement.timestamp}-${index}`}>
                              <td>{measurement.timestamp ? new Date(measurement.timestamp).toLocaleString('fr-FR') : '-'}</td>
                              <td>{measurement.spo2 ?? '-'}</td>
                              <td>{measurement.heart_rate ?? '-'}</td>
                              <td>{measurement.temperature != null ? Number(measurement.temperature).toFixed(1) : '-'}</td>
                              <td title={formatMeasurementQualityHint(measurement)}>
                                {formatMeasurementQualityLabel(measurement.status)}
                              </td>
                            </tr>
                          ))}
                          {!measurements.length && (
                            <tr>
                              <td colSpan="5">Aucune mesure disponible.</td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </section>

              <section className="panel panel-alert-trigger">
                <div className="panel-title">
                  <h2><Siren size={18} /> Alerte urgente</h2>
                </div>
                <p className="panel-alert-trigger-desc">
                  Appuyez sur le bouton ci-dessous si vous avez besoin d&apos;aide immédiate.
                  Votre médecin et votre aidant seront notifiés.
                </p>
                {alertStep === 'idle' && (
                  <>
                    <label className="alert-simulate-toggle">
                      <input
                        type="checkbox"
                        checked={simulateUrgentAlert}
                        onChange={(e) => setSimulateUrgentAlert(e.target.checked)}
                      />
                      <span>Simuler une alerte urgente</span>
                    </label>
                    <button
                      type="button"
                      className="alert-trigger-btn"
                      onClick={() => setAlertStep('confirm')}
                      aria-label="Déclencher une alerte urgente : notifier médecin et aidant"
                    >
                      <Siren size={16} strokeWidth={2} aria-hidden />
                      Déclencher une alerte
                    </button>
                  </>
                )}
                {alertStep === 'confirm' && (
                  <div className="alert-trigger-confirm" role="region" aria-labelledby="alert-confirm-title">
                    <p id="alert-confirm-title" className="alert-trigger-confirm-msg">
                      Votre médecin et votre aidant seront immédiatement notifiés.
                      En cas de danger de mort, appelez le <strong>15</strong>.
                    </p>
                    <textarea
                      className="alert-trigger-input"
                      rows={2}
                      placeholder="Message optionnel (ex. : douleur thoracique, difficultés à respirer...)"
                      value={alertMessage}
                      onChange={(e) => setAlertMessage(e.target.value)}
                      maxLength={500}
                      aria-label="Message optionnel pour l'alerte urgente"
                    />
                    <div className="alert-trigger-btns">
                      <button
                        type="button"
                        className="alert-trigger-cancel"
                        aria-label="Annuler l'alerte urgente"
                        onClick={() => { setAlertStep('idle'); setAlertMessage(''); setSimulateUrgentAlert(false) }}
                      >
                        Annuler
                      </button>
                      <button
                        type="button"
                        className="alert-trigger-btn alert-trigger-btn--confirm"
                        aria-label="Confirmer et envoyer l'alerte urgente"
                        onClick={handleSendAlert}
                      >
                        <Siren size={16} strokeWidth={2} aria-hidden />
                        Confirmer l&apos;alerte
                      </button>
                    </div>
                  </div>
                )}
                {alertStep === 'sending' && (
                  <p className="alert-trigger-status">Envoi en cours…</p>
                )}
                {alertStep === 'sent' && (
                  <div className="alert-trigger-success">
                    <p>Alerte envoyée. Votre médecin et votre aidant ont été notifiés.</p>
                    <button
                      type="button"
                      className="alert-trigger-btn alert-trigger-btn--secondary alert-trigger-btn--narrow"
                      onClick={() => setAlertStep('idle')}
                    >
                      Fermer
                    </button>
                  </div>
                )}
                {alertStep === 'error' && (
                  <div className="alert-trigger-error">
                    <p>{alertError}</p>
                    <button
                      type="button"
                      className="alert-trigger-btn alert-trigger-btn--secondary alert-trigger-btn--narrow"
                      onClick={() => setAlertStep('idle')}
                    >
                      Fermer
                    </button>
                  </div>
                )}
              </section>

              <section className="panel">
                <div className="panel-title">
                  <h2>Derniers retours du médecin</h2>
                  <span>{feedback.length} retour(s)</span>
                </div>
                <div className="patient-feedback-table-wrap">
                  <table className="patient-feedback-table">
                    <thead>
                      <tr>
                        <th>Date</th>
                        <th>Sévérité</th>
                        <th>Message</th>
                      </tr>
                    </thead>
                    <tbody>
                      {feedback.map((item, index) => {
                        const severityKey = (item.severity || 'medium').toLowerCase()
                        const severityLabel = getFeedbackSeverityLabel(severityKey, 'Moyenne')
                        const severityClass = severityKey === 'high' ? 'feedback-severity--high' : severityKey === 'low' ? 'feedback-severity--low' : 'feedback-severity--medium'
                        return (
                          <tr key={`${item.created_at || index}-${index}`}>
                            <td>{item.created_at ? new Date(item.created_at).toLocaleString('fr-FR') : '-'}</td>
                            <td>
                              <span className={`feedback-severity-badge ${severityClass}`}>{severityLabel}</span>
                            </td>
                            <td>{item.message || '-'}</td>
                          </tr>
                        )
                      })}
                      {!feedback.length && (
                        <tr>
                          <td colSpan="3">Aucun retour médecin pour le moment.</td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </section>
            </>
          )}
        </main>
      </div>
    </PatientLayout>
  )
}
