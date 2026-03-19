import React, { useEffect, useState } from 'react'
import { useNavigate, useParams, useLocation } from 'react-router-dom'
import { useAuth0 } from '@auth0/auth0-react'
import {
  BrainCircuit,
  CheckCircle2,
  Mail,
  MessageSquare,
  Phone,
  Stethoscope,
  PhoneCall,
  TriangleAlert,
} from 'lucide-react'
import {
  getLatestPatientFeedback,
  getPatientMeasurementsById,
  getPatientDoctorInfo,
  getCaregiverAlerts,
  getCaregiverPatients,
  patchCaregiverAlert,
} from '../services/api'

export default function CaregiverPatientDetail() {
  const { patientId } = useParams()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const base = pathname.startsWith('/family') ? '/family' : '/caregiver'
  const { getAccessTokenSilently } = useAuth0()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [measurements, setMeasurements] = useState([])
  const [feedback, setFeedback] = useState([])
  const [doctors, setDoctors] = useState([])
  const [alerts, setAlerts] = useState([])
  const [resolvingAlertId, setResolvingAlertId] = useState(null)
  const [resolutionComment, setResolutionComment] = useState('')
  const [resolutionError, setResolutionError] = useState('')

  useEffect(() => {
    let mounted = true
    const loadDetail = async () => {
      try {
        setLoading(true)
        setError('')
        const token = await getAccessTokenSilently()
        const [measurementsRes, feedbackRes, doctorRes, alertsRes, patientsRes] = await Promise.all([
          getPatientMeasurementsById(token, patientId, { limit: 200 }),
          getLatestPatientFeedback(token, patientId, 10),
          getPatientDoctorInfo(token, patientId),
          getCaregiverAlerts(token, { status: 'OPEN', limit: 100 }).catch(() => ({ alerts: [] })),
          getCaregiverPatients(token).catch(() => ({ patients: [] })),
        ])

        if (mounted) {
          setMeasurements(Array.isArray(measurementsRes.measurements) ? measurementsRes.measurements : [])
          setFeedback(Array.isArray(feedbackRes.feedback) ? feedbackRes.feedback : [])
          setDoctors(Array.isArray(doctorRes.doctors) ? doctorRes.doctors : [])
          const patients = patientsRes.patients || []
          const currentPatientIds = new Set([String(patientId)])
          patients.forEach((p) => {
            if (String(p.id) === String(patientId) || String(p.patient_id) === String(patientId)) {
              if (p.id) currentPatientIds.add(String(p.id))
              if (p.patient_id) currentPatientIds.add(String(p.patient_id))
            }
          })
          const patientAlerts = (alertsRes.alerts || []).filter(
            (a) => a.alert_id && currentPatientIds.has(String(a.patient_id))
          )
          setAlerts(patientAlerts)
        }
      } catch (fetchError) {
        if (mounted) {
          setError(fetchError.message || 'Erreur de chargement du détail patient')
        }
      } finally {
        if (mounted) setLoading(false)
      }
    }

    loadDetail()
    return () => {
      mounted = false
    }
  }, [getAccessTokenSilently, patientId])

  const handleResolveAlert = async (alertId) => {
    const id = alertId || (alerts.find((a) => a.alert_id)?.alert_id)
    if (!id) {
      setResolutionError('Identifiant d\'alerte manquant. Veuillez rafraîchir la page.')
      return
    }
    const comment = resolutionComment.trim()
    if (!comment) {
      setResolutionError('Veuillez indiquer ce qui a été fait (ex. : vérification sur place, appel au médecin).')
      return
    }
    try {
      setResolutionError('')
      const token = await getAccessTokenSilently()
      const res = await patchCaregiverAlert(token, id, comment)
      setAlerts((prev) =>
        prev.map((a) =>
          ((a.alert_id || a._id) === id)
            ? { ...a, caregiver_resolution_comment: res.caregiver_resolution_comment }
            : a
        )
      )
      setResolvingAlertId(null)
      setResolutionComment('')
    } catch (e) {
      setResolutionError(e.message || "Erreur lors de l'enregistrement")
    }
  }

  const getContactLink = (doc) => {
    if (!doc) return null
    const email = doc.email || (doc.contact?.includes('@') ? doc.contact : null)
    const phone = doc.phone || (doc.contact && !doc.contact.includes('@') ? doc.contact : null)
    if (email) return `mailto:${email}?subject=Urgence - VitalIO`
    if (phone) return `tel:${String(phone).replace(/\s/g, '')}`
    return null
  }

  return (
    <div className="caregiver-dashboard family-theme">
      <div className="main-content">
        <header className="caregiver-header">
          <div className="caregiver-header-left">
            <div>
              <h1 className="caregiver-title">Mon proche</h1>
              <p className="caregiver-subtitle">Constantes vitales et informations du médecin</p>
            </div>
          </div>
          <div className="caregiver-header-actions">
            <button
              type="button"
              className="caregiver-btn-analyses"
              onClick={() => navigate(`${base}/patient/${encodeURIComponent(patientId)}/ml`)}
            >
              <BrainCircuit size={18} />
              Voir les analyses
            </button>
          </div>
        </header>

        <main className="caregiver-main">
          {loading && (
            <div className="caregiver-loading">
              <div className="caregiver-loading-spinner" />
              <p>Chargement en cours...</p>
            </div>
          )}
          {!loading && error && <p className="caregiver-error">{error}</p>}
          {!loading && !error && (
            <>
              {alerts.length > 0 && (
                <section className="caregiver-alerts-section">
                  <h3><TriangleAlert size={20} /> Alertes à traiter</h3>
                  <p className="caregiver-alerts-intro">Prenez connaissance de l&apos;alerte et indiquez si l&apos;urgence est résolue.</p>
                  <div className="caregiver-alerts-list">
                    {alerts.map((a, i) => (
                      <article key={a.alert_id || a._id || i} className="caregiver-alert-card">
                        <p className="caregiver-alert-summary">{a.summary}</p>
                        <p className="caregiver-alert-description">{a.lay_description}</p>
                        {a.caregiver_resolution_comment && (
                          <p className="caregiver-alert-resolution">
                            <CheckCircle2 size={14} /> {a.caregiver_resolution_comment}
                          </p>
                        )}
                        <div className="caregiver-alert-actions">
                          {!a.caregiver_resolution_comment && a.status === 'OPEN' && (
                            <button
                              type="button"
                              className="caregiver-alert-resolve-btn"
                              onClick={() => setResolvingAlertId(resolvingAlertId === (a.alert_id || a._id) ? null : (a.alert_id || a._id))}
                            >
                              <CheckCircle2 size={14} /> J&apos;ai pris connaissance - Urgence résolue
                            </button>
                          )}
                        </div>
                        {resolvingAlertId === (a.alert_id || a._id) && (
                          <div className="caregiver-alert-resolve-form">
                            <p className="caregiver-alert-resolve-hint">
                              Indiquez ce que vous avez fait (ex. : vérification sur place, appel au médecin).
                            </p>
                            <textarea
                              className="caregiver-alert-resolve-input"
                              value={resolutionComment}
                              onChange={(e) => setResolutionComment(e.target.value)}
                              placeholder="Ex. : Vérification sur place, la personne va bien. J'ai appelé le médecin."
                              rows={3}
                            />
                            {resolutionError && <p className="caregiver-alert-error">{resolutionError}</p>}
                            <div className="caregiver-alert-resolve-btns">
                              <button
                                type="button"
                                className="caregiver-alert-view-btn"
                                onClick={() => { setResolvingAlertId(null); setResolutionComment(''); setResolutionError('') }}
                              >
                                Annuler
                              </button>
                              <button
                                type="button"
                                className="caregiver-alert-resolve-submit"
                                onClick={() => handleResolveAlert(a.alert_id || a._id)}
                              >
                                Enregistrer
                              </button>
                            </div>
                          </div>
                        )}
                      </article>
                    ))}
                  </div>
                </section>
              )}

              {doctors.length > 0 && (
                <section className="caregiver-doctor-section">
                  <h3><Stethoscope size={20} /> Médecin du patient</h3>
                  <div className="caregiver-doctor-cards">
                    {doctors.map((doc) => (
                      <article key={doc.id} className="caregiver-doctor-card">
                        <div className="caregiver-doctor-header">
                          <div className="caregiver-doctor-avatar">
                            {(doc.first_name || doc.display_name || 'M').charAt(0).toUpperCase()}
                          </div>
                          <div className="caregiver-doctor-info">
                            <strong className="caregiver-doctor-name">
                              {doc.display_name || `${doc.first_name} ${doc.last_name}`.trim() || 'Médecin'}
                            </strong>
                            {(doc.email || doc.phone || doc.contact) && (
                              <div className="caregiver-doctor-contact">
                                {doc.email && (
                                  <a href={`mailto:${doc.email}`} className="caregiver-contact-link">
                                    <Mail size={14} /> {doc.email}
                                  </a>
                                )}
                                {doc.phone && (
                                  <a href={`tel:${doc.phone.replace(/\s/g, '')}`} className="caregiver-contact-link">
                                    <Phone size={14} /> {doc.phone}
                                  </a>
                                )}
                                {!doc.email && !doc.phone && doc.contact && (
                                  <span className="caregiver-contact-text">
                                    {doc.contact.includes('@') ? (
                                      <a href={`mailto:${doc.contact}`} className="caregiver-contact-link">
                                        <Mail size={14} /> {doc.contact}
                                      </a>
                                    ) : (
                                      <a href={`tel:${doc.contact.replace(/\s/g, '')}`} className="caregiver-contact-link">
                                        <Phone size={14} /> {doc.contact}
                                      </a>
                                    )}
                                  </span>
                                )}
                              </div>
                            )}
                          </div>
                        </div>
                        {getContactLink(doc) && (
                          <a
                            href={getContactLink(doc)}
                            className="caregiver-contact-emergency-btn"
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            <PhoneCall size={18} />
                            Contacter en cas d'urgence
                          </a>
                        )}
                      </article>
                    ))}
                  </div>
                </section>
              )}

              {feedback.length > 0 && (
                <section className="caregiver-feedback-section">
                  <h3><MessageSquare size={20} /> Commentaires du médecin</h3>
                  <div className="caregiver-feedback-list">
                    {feedback.map((item, index) => (
                      <article key={`${item.created_at || index}-${index}`} className="caregiver-feedback-card">
                        <div className="caregiver-feedback-meta">
                          <span className="caregiver-feedback-date">
                            {item.created_at ? new Date(item.created_at).toLocaleString('fr-FR') : '-'}
                          </span>
                          {item.severity && (
                            <span className={`caregiver-feedback-severity caregiver-feedback-severity--${item.severity.toLowerCase()}`}>
                              {item.severity}
                            </span>
                          )}
                        </div>
                        <p className="caregiver-feedback-message">{item.message || '-'}</p>
                      </article>
                    ))}
                  </div>
                </section>
              )}

              <section className="caregiver-patients-section">
                <div className="section-header">
                  <h3>Historique des mesures</h3>
                </div>
                <div className="caregiver-table-wrap">
                  <table className="caregiver-table">
                    <thead>
                      <tr>
                        <th>Date</th>
                        <th>SpO2</th>
                        <th>FC</th>
                        <th>Température</th>
                        <th>Statut</th>
                      </tr>
                    </thead>
                    <tbody>
                      {measurements.map((measurement, index) => (
                        <tr key={`${measurement.timestamp}-${index}`}>
                          <td>{new Date(measurement.timestamp).toLocaleString('fr-FR')}</td>
                          <td>{measurement.spo2 ?? '-'}</td>
                          <td>{measurement.heart_rate ?? '-'}</td>
                          <td>{measurement.temperature ?? '-'}</td>
                          <td>{measurement.status || '-'}</td>
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
              </section>
            </>
          )}
        </main>
      </div>
    </div>
  )
}
