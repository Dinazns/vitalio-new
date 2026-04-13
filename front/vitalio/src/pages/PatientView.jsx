import React, { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth0 } from '@auth0/auth0-react'
import { Activity, Thermometer, HeartPulse, ShieldAlert, Siren } from 'lucide-react'
import {
  getLatestPatientFeedback,
  getPatientData,
  getPatientProfile,
  triggerManualAlert,
} from '../services/api'
import PatientLayout from '../components/PatientLayout'

const formatDateLabel = (isoValue) => {
  if (!isoValue) return ''
  const date = new Date(isoValue)
  return date.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit' })
}

const safeNumber = (value, fallback = 0) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

const MiniTrendChart = ({ points }) => {
  if (!points.length) {
    return <div className="empty-chart">Pas assez de mesures pour afficher une courbe.</div>
  }

  const width = 720
  const height = 220
  const padding = 20

  const values = points.map((point) => safeNumber(point.spo2))
  const minValue = Math.min(...values) - 1
  const maxValue = Math.max(...values) + 1
  const range = Math.max(maxValue - minValue, 1)

  const toX = (index) => {
    if (points.length === 1) return width / 2
    return padding + (index / (points.length - 1)) * (width - padding * 2)
  }

  const toY = (value) => {
    const normalized = (safeNumber(value) - minValue) / range
    return height - padding - normalized * (height - padding * 2)
  }

  const linePath = points
    .map((point, index) => `${index === 0 ? 'M' : 'L'} ${toX(index)} ${toY(point.spo2)}`)
    .join(' ')

  return (
    <div className="trend-chart">
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label="Courbe SpO2">
        <path d={linePath} className="line" />
        {points.map((point, index) => (
          <circle key={`${point.timestamp}-${index}`} cx={toX(index)} cy={toY(point.spo2)} r="3.5" className="dot" />
        ))}
      </svg>
      <div className="chart-labels">
        <span>{formatDateLabel(points[0].timestamp)}</span>
        <span>{formatDateLabel(points[points.length - 1].timestamp)}</span>
      </div>
    </div>
  )
}

export default function PatientView() {
  const navigate = useNavigate()
  const { user, getAccessTokenSilently } = useAuth0()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [measurements, setMeasurements] = useState([])
  const [feedback, setFeedback] = useState([])
  const [profile, setProfile] = useState(null)
  const [alertStep, setAlertStep] = useState('idle') // 'idle' | 'confirm' | 'sending' | 'sent' | 'error'
  const [alertMessage, setAlertMessage] = useState('')
  const [alertError, setAlertError] = useState('')
  const [alertCooldown, setAlertCooldown] = useState(0)

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
        const [data, feedbackRes, profileRes] = await Promise.all([
          getPatientData(token),
          feedbackPromise,
          getPatientProfile(token).catch(() => ({ profile: null, doctors: [], caregivers: [] })),
        ])
        if (mounted) {
          setMeasurements(Array.isArray(data.measurements) ? data.measurements : [])
          setFeedback(Array.isArray(feedbackRes.feedback) ? feedbackRes.feedback : [])
          const profileData = profileRes?.profile ?? profileRes
          const doctors = profileRes?.doctors ?? profileData?.doctors ?? []
          const caregivers = profileRes?.caregivers ?? profileData?.caregivers ?? []
          setProfile(profileData ? { ...profileData, doctors, caregivers } : null)
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

  const handleSendAlert = async () => {
    setAlertStep('sending')
    setAlertError('')
    try {
      const token = await getAccessTokenSilently()
      await triggerManualAlert(token, alertMessage.trim())
      setAlertStep('sent')
      setAlertMessage('')
    } catch (e) {
      const waitMatch = (e.message || '').match(/(\d+)\s*secondes?/)
      if (waitMatch) {
        const secs = parseInt(waitMatch[1], 10)
        setAlertCooldown(secs)
        setAlertError(`Veuillez patienter ${secs} secondes avant de renvoyer une alerte.`)
      } else {
        setAlertError(e.message || "Erreur lors de l'envoi de l'alerte.")
      }
      setAlertStep('error')
    }
  }

  const latest = measurements[0]
  // Auth0 met souvent user.name = email quand aucun nom n'est défini ; on l'exclut du fallback
  const auth0Name = user?.name && !String(user.name).includes('@') ? user.name : null
  const profileFullName = profile?.first_name || profile?.last_name
    ? `${profile?.first_name || ''} ${profile?.last_name || ''}`.trim()
    : null
  const displayName = profile?.display_name ?? auth0Name ?? profileFullName ?? ''

  const chartPoints = useMemo(() => {
    if (!measurements.length) return []

    const sevenDaysAgo = Date.now() - 7 * 24 * 60 * 60 * 1000
    const recentByDate = measurements
      .filter((item) => {
        const ts = new Date(item.timestamp).getTime()
        return Number.isFinite(ts) && ts >= sevenDaysAgo
      })
      .slice()
      .reverse()

    if (recentByDate.length >= 2) return recentByDate
    return measurements.slice(0, 50).slice().reverse()
  }, [measurements])

  return (
    <PatientLayout>
      <div className="patient-container patient-theme">
      <main className="patient-dashboard">
        <header className="patient-header">
        <h1>Bonjour {displayName}</h1>
          <p>Voici vos dernières constantes vitales.</p>
        </header>

        {loading && <div className="panel">Chargement des mesures...</div>}

        {!loading && error && (
          <div className="panel panel-error">
            <ShieldAlert size={20} />
            <span>{error}</span>
          </div>
        )}

        {!loading && !error && (
          <>
            <section className="vital-cards">
              <article className="card">
                <span className="label">SpO₂</span>
                <div className="value-row">
                  <Activity size={18} />
                  <strong>{safeNumber(latest?.spo2, 0).toFixed(0)}%</strong>
                </div>
              </article>
              <article className="card">
                <span className="label">FC</span>
                <div className="value-row">
                  <HeartPulse size={18} />
                  <strong>{safeNumber(latest?.heart_rate, 0).toFixed(0)} bpm</strong>
                </div>
              </article>
              <article className="card">
                <span className="label">Température</span>
                <div className="value-row">
                  <Thermometer size={18} />
                  <strong>{safeNumber(latest?.temperature, 0).toFixed(1)} C</strong>
                </div>
              </article>
            </section>

            <section className="panel">
              <div className="panel-title">
                <h2>Tendance SpO₂</h2>
                <span>{chartPoints.length} mesures</span>
              </div>
              <MiniTrendChart points={chartPoints} />
            </section>

            <section className="panel panel-cta">
              <div>
                <h2>Prise de mesure</h2>
                <p>Lancez un parcours guidé en 3 étapes pour envoyer une nouvelle mesure.</p>
              </div>
              <button onClick={() => navigate('/patient/measure')} className="primary-button">
                Démarrer
              </button>
            </section>

            <section className="panel panel-alert-trigger">
              <div className="panel-title">
                <h2><Siren size={18} /> Alerte urgente</h2>
              </div>
              <p className="panel-alert-trigger-desc">
                Appuyez sur le bouton ci-dessous si vous avez besoin d'aide immédiate.
                Votre médecin et votre aidant seront notifiés.
              </p>
              {alertStep === 'idle' && (
                <button
                  type="button"
                  className="alert-trigger-btn"
                  onClick={() => setAlertStep('confirm')}
                >
                  <Siren size={18} /> Déclencher une alerte
                </button>
              )}
              {alertStep === 'confirm' && (
                <div className="alert-trigger-confirm">
                  <p className="alert-trigger-confirm-msg">
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
                  />
                  <div className="alert-trigger-btns">
                    <button
                      type="button"
                      className="alert-trigger-cancel"
                      onClick={() => { setAlertStep('idle'); setAlertMessage('') }}
                    >
                      Annuler
                    </button>
                    <button
                      type="button"
                      className="alert-trigger-btn alert-trigger-btn--confirm"
                      onClick={handleSendAlert}
                    >
                      <Siren size={16} /> Confirmer l'alerte
                    </button>
                  </div>
                </div>
              )}
              {alertStep === 'sending' && (
                <p className="alert-trigger-status">Envoi en cours...</p>
              )}
              {alertStep === 'sent' && (
                <div className="alert-trigger-success">
                  <p>Alerte envoyée. Votre médecin et votre aidant ont été notifiés.</p>
                  <button
                    type="button"
                    className="alert-trigger-btn"
                    style={{ marginTop: '0.5rem', background: '#475569' }}
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
                    className="alert-trigger-btn"
                    style={{ background: '#475569', marginTop: '0.5rem' }}
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
                      const severityLabels = { low: 'Faible', medium: 'Moyenne', high: 'Haute' }
                      const severityKey = (item.severity || 'medium').toLowerCase()
                      const severityLabel = severityLabels[severityKey] || severityLabels.medium
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
                        <td colSpan="4">Aucun retour médecin pour le moment.</td>
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
