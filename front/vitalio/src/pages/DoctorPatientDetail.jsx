import React, { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth0 } from '@auth0/auth0-react'
import { ArrowLeft, BrainCircuit, Copy, Heart, Mail, PhoneCall, Thermometer, User, Users, Wind } from 'lucide-react'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import {
  createDoctorFeedback,
  getDoctorPatientMeasurements,
  getDoctorPatientTrends,
  getLatestPatientFeedback,
  getPatientCaregiverInfo,
  getPatientProfileForDoctor,
} from '../services/api'
import DoctorLayout from '../components/DoctorLayout'

function formatDay(timestamp) {
  if (!timestamp) return ''
  return new Date(timestamp).toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit' })
}

function formatPatientAddressLines(p) {
  if (!p) return []
  const line3 = [p.postal_code, p.city].filter(Boolean).join(' ').trim()
  return [p.address_line1, p.address_line2, line3, p.country].filter((x) => x && String(x).trim())
}

function computeAge(birthdate, ageFromProfile) {
  if (ageFromProfile != null && ageFromProfile !== '') return ageFromProfile
  if (!birthdate) return null
  try {
    const birth = new Date(birthdate)
    const today = new Date()
    let a = today.getFullYear() - birth.getFullYear()
    const m = today.getMonth() - birth.getMonth()
    if (m < 0 || (m === 0 && today.getDate() < birth.getDate())) a--
    return a >= 0 ? a : null
  } catch {
    return null
  }
}

function ProfileField({ label, value, link }) {
  const v = value ?? ''
  const display = String(v).trim() || '-'
  if (link && display !== '-') {
    return (
      <div>
        <span style={{ fontSize: '0.75rem', color: '#64748b', display: 'block', marginBottom: '0.25rem' }}>{label}</span>
        <a href={link} style={{ color: '#2563eb', textDecoration: 'none' }}>{display}</a>
      </div>
    )
  }
  return (
    <div>
      <span style={{ fontSize: '0.75rem', color: '#64748b', display: 'block', marginBottom: '0.25rem' }}>{label}</span>
      <strong>{display}</strong>
    </div>
  )
}

export default function DoctorPatientDetail() {
  const { patientId } = useParams()
  const navigate = useNavigate()
  const { getAccessTokenSilently } = useAuth0()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [measurements, setMeasurements] = useState([])
  const [trends, setTrends] = useState(null)
  const [windowDays, setWindowDays] = useState(7)
  const [feedback, setFeedback] = useState([])
  const [feedbackMessage, setFeedbackMessage] = useState('')
  const [feedbackSeverity, setFeedbackSeverity] = useState('medium')
  const [feedbackSubmitting, setFeedbackSubmitting] = useState(false)
  const [feedbackError, setFeedbackError] = useState('')
  const [caregivers, setCaregivers] = useState([])
  const [patientProfile, setPatientProfile] = useState(null)

  useEffect(() => {
    let mounted = true

    const loadPatientDetail = async () => {
      try {
        setLoading(true)
        setError('')
        const token = await getAccessTokenSilently()
        const [measurementsRes, trendsRes, feedbackRes, caregiverRes, profileRes] = await Promise.all([
          getDoctorPatientMeasurements(token, patientId, 30),
          getDoctorPatientTrends(token, patientId),
          getLatestPatientFeedback(token, patientId, 5),
          getPatientCaregiverInfo(token, patientId).catch(() => ({ caregivers: [] })),
          getPatientProfileForDoctor(token, patientId).catch(() => ({ profile: null })),
        ])
        if (mounted) {
          const rows = Array.isArray(measurementsRes.measurements) ? measurementsRes.measurements : []
          setMeasurements(rows)
          setTrends(trendsRes.trends || null)
          setFeedback(Array.isArray(feedbackRes.feedback) ? feedbackRes.feedback : [])
          setCaregivers(Array.isArray(caregiverRes?.caregivers) ? caregiverRes.caregivers : [])
          setPatientProfile(profileRes?.profile || null)
        }
      } catch (fetchError) {
        if (mounted) {
          setError(fetchError.message || 'Erreur de chargement des données patient')
        }
      } finally {
        if (mounted) {
          setLoading(false)
        }
      }
    }

    loadPatientDetail()
    return () => {
      mounted = false
    }
  }, [getAccessTokenSilently, patientId])

  const selectedTrend = windowDays === 7 ? trends?.['7d'] : trends?.['30d']

  const chartData = useMemo(() => {
    const source = selectedTrend?.series || []
    return source.map((row) => ({
      date: formatDay(row.timestamp),
      spo2: row.spo2,
      heart_rate: row.heart_rate,
      temperature: row.temperature,
    }))
  }, [selectedTrend])

  const latest = measurements[0]

  const submitFeedback = async () => {
    const trimmedMessage = feedbackMessage.trim()
    if (!trimmedMessage) {
      setFeedbackError('Le message est obligatoire.')
      return
    }

    try {
      setFeedbackSubmitting(true)
      setFeedbackError('')
      const token = await getAccessTokenSilently()
      await createDoctorFeedback(token, patientId, {
        message: trimmedMessage,
        severity: feedbackSeverity,
        status: 'new',
      })
      const feedbackRes = await getLatestPatientFeedback(token, patientId, 5)
      setFeedback(Array.isArray(feedbackRes.feedback) ? feedbackRes.feedback : [])
      setFeedbackMessage('')
    } catch (submitError) {
      setFeedbackError(submitError.message || 'Impossible de publier le retour.')
    } finally {
      setFeedbackSubmitting(false)
    }
  }

  return (
    <DoctorLayout>
      <div className="doctor-container doctor-theme">
        <div className="main-content">
          <header className="doctor-header">
            <div className="doctor-header-left">
              <h1 className="doctor-title">Détail patient</h1>
              <p className="doctor-subtitle">Constantes vitales, tendances et commentaires</p>
            </div>
            <div className="header-actions">
              <button
                className="doctor-btn doctor-btn-primary"
                onClick={() => navigate(`/doctor/patient/${patientId}/ml`)}
              >
                <BrainCircuit size={18} /> Suivi avancé
              </button>
              <button className="bell-btn" onClick={() => navigate('/doctor')}>
                <ArrowLeft size={20} />
              </button>
            </div>
          </header>

          <main className="doctor-main">
          {loading && (
            <div className="doctor-loading">
              <div className="doctor-loading-spinner" />
              <p>Chargement des mesures...</p>
            </div>
          )}
          {!loading && error && <p className="doctor-error">{error}</p>}
          {!loading && !error && (
            <>
              {patientProfile && (
                <section className="doctor-patients-section">
                  <div className="doctor-patients-card">
                    <div className="section-header">
                      <h3><User size={20} /> Profil patient - données complètes</h3>
                    </div>
                    <div className="doctor-profile-sections" style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
                      <div>
                        <h4 style={{ fontSize: '0.875rem', fontWeight: 600, color: '#475569', marginBottom: '0.75rem' }}>Identité</h4>
                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: '1rem 2rem' }}>
                          <ProfileField label="Prénom" value={patientProfile.first_name} />
                          <ProfileField label="Nom" value={patientProfile.last_name} />
                          <ProfileField label="Date de naissance" value={patientProfile.birthdate ? new Date(patientProfile.birthdate).toLocaleDateString('fr-FR') : null} />
                          <ProfileField label="Âge" value={computeAge(patientProfile.birthdate, patientProfile.age) != null ? `${computeAge(patientProfile.birthdate, patientProfile.age)} ans` : null} />
                          <ProfileField label="Sexe" value={patientProfile.sex === 'm' ? 'Homme' : patientProfile.sex === 'f' ? 'Femme' : patientProfile.sex === 'o' ? 'Autre' : patientProfile.sex} />
                        </div>
                      </div>
                      <div>
                        <h4 style={{ fontSize: '0.875rem', fontWeight: 600, color: '#475569', marginBottom: '0.75rem' }}>Contact</h4>
                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: '1rem 2rem' }}>
                          <ProfileField label="Téléphone" value={patientProfile.phone} link={patientProfile.phone ? `tel:${patientProfile.phone.replace(/\s/g, '')}` : null} />
                          <ProfileField label="Email" value={patientProfile.email} link={patientProfile.email ? `mailto:${patientProfile.email}` : null} />
                        </div>
                      </div>
                      <div>
                        <h4 style={{ fontSize: '0.875rem', fontWeight: 600, color: '#475569', marginBottom: '0.75rem' }}>Urgences - adresse &amp; SAMU</h4>
                        <p style={{ margin: '0 0 0.5rem', fontSize: '0.8rem', color: '#64748b' }}>
                          À utiliser si vous devez orienter les secours vers le domicile du patient.
                        </p>
                        {formatPatientAddressLines(patientProfile).length > 0 ? (
                          <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '0.75rem' }}>
                            <p style={{ margin: 0, lineHeight: 1.5, flex: '1 1 200px' }}>
                              {formatPatientAddressLines(patientProfile).join(', ')}
                            </p>
                            <button
                              type="button"
                              className="doctor-btn doctor-btn-secondary"
                              style={{ display: 'inline-flex', alignItems: 'center', gap: '0.35rem' }}
                              onClick={() => {
                                const t = formatPatientAddressLines(patientProfile).join(', ')
                                navigator.clipboard.writeText(t).catch(() => {})
                              }}
                            >
                              <Copy size={16} /> Copier l&apos;adresse
                            </button>
                            <a href="tel:15" className="doctor-btn doctor-btn-primary" style={{ textDecoration: 'none' }}>
                              <PhoneCall size={16} /> 15 (SAMU)
                            </a>
                          </div>
                        ) : (
                          <p style={{ margin: 0, color: '#94a3b8', fontSize: '0.875rem' }}>Adresse non renseignée par le patient.</p>
                        )}
                      </div>
                      <div>
                        <h4 style={{ fontSize: '0.875rem', fontWeight: 600, color: '#475569', marginBottom: '0.75rem' }}>Antécédents médicaux</h4>
                        <p style={{ margin: 0, whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>{patientProfile.medical_history || 'Non renseigné'}</p>
                      </div>
                      <div>
                        <h4 style={{ fontSize: '0.875rem', fontWeight: 600, color: '#475569', marginBottom: '0.75rem' }}>Statut</h4>
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.5rem' }}>
                          <span style={{
                            width: 8,
                            height: 8,
                            borderRadius: '50%',
                            backgroundColor: patientProfile.onboarding_completed ? '#22c55e' : '#eab308',
                          }} />
                          {patientProfile.onboarding_completed ? 'Onboarding complété' : 'Onboarding en attente'}
                        </span>
                      </div>
                    </div>
                  </div>
                </section>
              )}
              {caregivers.length > 0 && (
                <section className="doctor-patients-section">
                  <div className="doctor-patients-card">
                    <div className="section-header">
                      <h3><Users size={20} /> Aidant du patient - contact</h3>
                    </div>
                    <div className="doctor-caregiver-cards" style={{ display: 'flex', flexWrap: 'wrap', gap: '1rem' }}>
                      {caregivers.map((cg) => {
                        const cgEmail = cg.email || (cg.contact?.includes?.('@') ? cg.contact : null)
                        const cgPhone = cg.phone || (cg.contact && !cg.contact?.includes?.('@') ? cg.contact : null)
                        return (
                          <article key={cg.id} className="doctor-caregiver-card" style={{
                            padding: '1.25rem',
                            border: '1px solid #e2e8f0',
                            borderRadius: '8px',
                            minWidth: '280px',
                            flex: '1 1 280px',
                          }}>
                            <div style={{ marginBottom: '0.75rem' }}>
                              <div style={{ fontSize: '0.75rem', color: '#64748b', marginBottom: '0.25rem' }}>Prénom</div>
                              <strong>{cg.first_name || '-'}</strong>
                            </div>
                            <div style={{ marginBottom: '0.75rem' }}>
                              <div style={{ fontSize: '0.75rem', color: '#64748b', marginBottom: '0.25rem' }}>Nom</div>
                              <strong>{cg.last_name || '-'}</strong>
                            </div>
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
                              {cgEmail && (
                                <a
                                  href={`mailto:${cgEmail}`}
                                  className="doctor-btn doctor-btn-primary"
                                  style={{ display: 'inline-flex', alignItems: 'center', gap: '0.5rem', textDecoration: 'none' }}
                                >
                                  <Mail size={16} />
                                  Contacter par email
                                </a>
                              )}
                            </div>
                          </article>
                        )
                      })}
                    </div>
                  </div>
                </section>
              )}

              <section className="doctor-stats">
                <article className="doctor-stat-card doctor-stat-spo2">
                  <div className="doctor-stat-icon">
                    <Wind size={24} />
                  </div>
                  <div className="doctor-stat-content">
                    <span className="doctor-stat-value">{latest?.spo2 ?? '-'}</span>
                    <span className="doctor-stat-label">SpO₂</span>
                  </div>
                </article>
                <article className="doctor-stat-card doctor-stat-fc">
                  <div className="doctor-stat-icon">
                    <Heart size={24} />
                  </div>
                  <div className="doctor-stat-content">
                    <span className="doctor-stat-value">{latest?.heart_rate ?? '-'}</span>
                    <span className="doctor-stat-label">Fréquence cardiaque</span>
                  </div>
                </article>
                <article className="doctor-stat-card doctor-stat-temp">
                  <div className="doctor-stat-icon">
                    <Thermometer size={24} />
                  </div>
                  <div className="doctor-stat-content">
                    <span className="doctor-stat-value">{latest?.temperature ?? '-'}</span>
                    <span className="doctor-stat-label">Température</span>
                  </div>
                </article>
              </section>


              <section className="doctor-patients-section">
              <div className="doctor-patients-card">
                <div className="section-header">
                  <h3>Historique des mesures</h3>
                </div>
                <div className="doctor-table-wrap">
                <table className="doctor-table">
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
                        <td>{measurement.spo2}</td>
                        <td>{measurement.heart_rate}</td>
                        <td>{measurement.temperature}</td>
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
              </div>
              </section>

              <section className="doctor-patients-section">
              <div className="doctor-patients-card">
                <div className="section-header">
                  <h3>Nouveau commentaire médecin</h3>
                </div>
                <div className="doctor-invite-form">
                  <textarea
                    className="doctor-invite-email"
                    value={feedbackMessage}
                    onChange={(event) => setFeedbackMessage(event.target.value)}
                    placeholder="Saisir un commentaire clinique..."
                    rows={4}
                    style={{ resize: 'vertical', minHeight: 80 }}
                  />
                  <div className="doctor-invite-actions" style={{ alignItems: 'center', flexWrap: 'wrap' }}>
                    <label htmlFor="severity" style={{ fontSize: '0.875rem', fontWeight: 500, color: '#475569', marginRight: '0.5rem' }}>
                      Sévérité :
                    </label>
                    <select
                      id="severity"
                      className="doctor-invite-email"
                      value={feedbackSeverity}
                      onChange={(event) => setFeedbackSeverity(event.target.value)}
                      style={{ maxWidth: 160 }}
                    >
                      <option value="low">Faible</option>
                      <option value="medium">Moyenne</option>
                      <option value="high">Haute</option>
                    </select>
                    <button
                      className="doctor-btn doctor-btn-primary"
                      onClick={submitFeedback}
                      disabled={feedbackSubmitting}
                    >
                      {feedbackSubmitting ? 'Envoi...' : 'Publier'}
                    </button>
                  </div>
                  {feedbackError && <p className="doctor-error">{feedbackError}</p>}
                </div>
              </div>
              </section>

              <section className="doctor-patients-section">
              <div className="doctor-patients-card">
                <div className="section-header">
                  <h3>Derniers commentaires médecin</h3>
                </div>
                <div className="doctor-table-wrap">
                <table className="doctor-table">
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th>Sévérité</th>
                      <th>Message</th>
                    </tr>
                  </thead>
                  <tbody>
                    {feedback.map((item, index) => (
                      <tr key={`${item.created_at || index}-${index}`}>
                        <td>{item.created_at ? new Date(item.created_at).toLocaleString('fr-FR') : '-'}</td>
                        <td>{item.severity || '-'}</td>
                        <td>{item.message || '-'}</td>
                      </tr>
                    ))}
                    {!feedback.length && (
                      <tr>
                        <td colSpan="4">Aucun commentaire médecin disponible.</td>
                      </tr>
                    )}
                  </tbody>
                </table>
                </div>
              </div>
              </section>
            </>
          )}
          </main>
        </div>
      </div>
    </DoctorLayout>
  )
}
