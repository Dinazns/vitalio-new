import React, { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth0 } from '@auth0/auth0-react'
import { ArrowLeft, BrainCircuit, Copy, Cpu, FileText, Heart, Mail, PhoneCall, Thermometer, Trash2, User, Users, Wind } from 'lucide-react'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import {
  assignDoctorPatientDevice,
  createDoctorFeedback,
  getDoctorPatientDevice,
  getDoctorPatientMeasurements,
  getDoctorPatientTrends,
  getLatestPatientFeedback,
  getPatientCaregiverInfo,
  getPatientProfileForDoctor,
  getPatientMLAnalysis,
  removeDoctorPatient,
} from '../services/api'
import { DEVICE_ID_PREFIX, isDeviceIdPrefixOnly, normalizeDeviceIdInput } from '../utils/parseDeviceId'
import DoctorLayout from '../components/DoctorLayout'
import { resolvePatientDisplayName, resolvePatientListDisplayName } from '../utils/displayName'

/** Message API quand aucun enregistrement users_devices n’expose encore de device_id mesurable. */
const NO_PATIENT_DEVICE_MESSAGE = 'No device record found for patient'

/** Aperçu tableau médecin ; chargement complet au clic. */
const DOCTOR_MEASUREMENTS_PREVIEW_LIMIT = 10
const DOCTOR_MEASUREMENTS_FULL_LIMIT = 500

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

const CLINICAL_RISK_BADGE = {
  minimal: { bg: '#ecfdf5', color: '#047857', label: 'Risque minimal' },
  low: { bg: '#eff6ff', color: '#1d4ed8', label: 'Risque faible' },
  moderate: { bg: '#fffbeb', color: '#b45309', label: 'Risque modéré' },
  high: { bg: '#fef2f2', color: '#b91c1c', label: 'Risque élevé' },
  unknown: { bg: '#f1f5f9', color: '#64748b', label: '—' },
}

function ProfileField({ label, value, link }) {
  const v = value ?? ''
  const display = String(v).trim() || '-'
  if (link && display !== '-') {
    return (
      <div className="doctor-profile-field">
        <span className="doctor-profile-field__label">{label}</span>
        <a href={link} className="doctor-profile-field__link">{display}</a>
      </div>
    )
  }
  return (
    <div className="doctor-profile-field">
      <span className="doctor-profile-field__label">{label}</span>
      <strong className="doctor-profile-field__value">{display}</strong>
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
  const [measurementsShowAll, setMeasurementsShowAll] = useState(false)
  const [measurementsLoadingMore, setMeasurementsLoadingMore] = useState(false)
  const [trends, setTrends] = useState(null)
  const [windowDays, setWindowDays] = useState(7)
  const [feedback, setFeedback] = useState([])
  const [feedbackMessage, setFeedbackMessage] = useState('')
  const [feedbackSeverity, setFeedbackSeverity] = useState('medium')
  const [feedbackSubmitting, setFeedbackSubmitting] = useState(false)
  const [feedbackError, setFeedbackError] = useState('')
  const [caregivers, setCaregivers] = useState([])
  const [patientProfile, setPatientProfile] = useState(null)
  const [patientDevice, setPatientDevice] = useState(null)
  const [deviceIdInput, setDeviceIdInput] = useState(DEVICE_ID_PREFIX)
  const [deviceSaving, setDeviceSaving] = useState(false)
  const [removePatientSubmitting, setRemovePatientSubmitting] = useState(false)
  const [removePatientError, setRemovePatientError] = useState('')
  const [deviceError, setDeviceError] = useState('')
  const [deviceSuccess, setDeviceSuccess] = useState('')
  const [weeklyClinicalSummary, setWeeklyClinicalSummary] = useState(null)
  const [weeklySummaryLoading, setWeeklySummaryLoading] = useState(false)
  const [weeklySummaryError, setWeeklySummaryError] = useState('')

  useEffect(() => {
    let mounted = true

    const loadPatientDetail = async () => {
      try {
        setLoading(true)
        setError('')
        setMeasurementsShowAll(false)
        const token = await getAccessTokenSilently()
        const [measurementsRes, trendsRes, feedbackRes, caregiverRes, profileRes, deviceDoc] = await Promise.all([
          getDoctorPatientMeasurements(token, patientId, 30, DOCTOR_MEASUREMENTS_PREVIEW_LIMIT).catch((e) => {
            if (e.message && e.message.includes(NO_PATIENT_DEVICE_MESSAGE)) {
              return { measurements: [], device_id: null, patient_id: patientId }
            }
            throw e
          }),
          getDoctorPatientTrends(token, patientId).catch((e) => {
            if (e.message && e.message.includes(NO_PATIENT_DEVICE_MESSAGE)) {
              return { trends: null, patient_id: patientId }
            }
            throw e
          }),
          getLatestPatientFeedback(token, patientId, 5),
          getPatientCaregiverInfo(token, patientId).catch(() => ({ caregivers: [] })),
          getPatientProfileForDoctor(token, patientId).catch(() => ({ profile: null })),
          getDoctorPatientDevice(token, patientId),
        ])
        if (mounted) {
          const rows = Array.isArray(measurementsRes.measurements) ? measurementsRes.measurements : []
          setMeasurements(rows)
          setTrends(trendsRes.trends || null)
          setFeedback(Array.isArray(feedbackRes.feedback) ? feedbackRes.feedback : [])
          setCaregivers(Array.isArray(caregiverRes?.caregivers) ? caregiverRes.caregivers : [])
          setPatientProfile(profileRes?.profile || null)
          setPatientDevice(deviceDoc)
          setDeviceIdInput(deviceDoc?.device_id ? String(deviceDoc.device_id) : DEVICE_ID_PREFIX)
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

  useEffect(() => {
    if (!patientId || loading) return undefined
    let cancelled = false
    setWeeklySummaryLoading(true)
    setWeeklySummaryError('')
    ;(async () => {
      try {
        const token = await getAccessTokenSilently()
        const data = await getPatientMLAnalysis(token, patientId, { days: 7, include_forecast: false })
        if (cancelled) return
        setWeeklyClinicalSummary(data?.clinical_narrative_summary || null)
      } catch {
        if (!cancelled) {
          setWeeklyClinicalSummary(null)
          setWeeklySummaryError('Impossible de charger le résumé des 7 derniers jours.')
        }
      } finally {
        if (!cancelled) setWeeklySummaryLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [patientId, loading, getAccessTokenSilently])

  const submitPatientDevice = async () => {
    const trimmed = deviceIdInput.trim()
    if (!trimmed || isDeviceIdPrefixOnly(trimmed)) {
      setDeviceError('Indiquez l’identifiant complet inscrit sur le boîtier (ex. VITALIO-XXXXXXXX).')
      return
    }
    try {
      setDeviceSaving(true)
      setDeviceError('')
      setDeviceSuccess('')
      const token = await getAccessTokenSilently()
      await assignDoctorPatientDevice(token, patientId, trimmed)
      const deviceDoc = await getDoctorPatientDevice(token, patientId)
      setPatientDevice(deviceDoc)
      setDeviceSuccess('Boîtier associé. Le patient peut finaliser l’appairage chez lui.')
      try {
        setMeasurementsShowAll(false)
        const [measurementsRes, trendsRes] = await Promise.all([
          getDoctorPatientMeasurements(token, patientId, 30, DOCTOR_MEASUREMENTS_PREVIEW_LIMIT),
          getDoctorPatientTrends(token, patientId),
        ])
        setMeasurements(Array.isArray(measurementsRes.measurements) ? measurementsRes.measurements : [])
        setTrends(trendsRes.trends || null)
      } catch {
        /* mesures encore absentes tant que le boîtier n’envoie pas de données */
      }
    } catch (e) {
      setDeviceError(e.message || 'Association impossible.')
    } finally {
      setDeviceSaving(false)
    }
  }

  const loadAllMeasurements = async () => {
    try {
      setMeasurementsLoadingMore(true)
      setError('')
      const token = await getAccessTokenSilently()
      const measurementsRes = await getDoctorPatientMeasurements(
        token,
        patientId,
        30,
        DOCTOR_MEASUREMENTS_FULL_LIMIT,
      )
      setMeasurements(Array.isArray(measurementsRes.measurements) ? measurementsRes.measurements : [])
      setMeasurementsShowAll(true)
    } catch (e) {
      setError(e.message || 'Impossible de charger tout l’historique des mesures')
    } finally {
      setMeasurementsLoadingMore(false)
    }
  }

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
  const weeklyRiskForDisplay = weeklyClinicalSummary?.text
    ? CLINICAL_RISK_BADGE[weeklyClinicalSummary.risk_level] || CLINICAL_RISK_BADGE.unknown
    : null

  const handleRemovePatient = async () => {
    const patientName = resolvePatientDisplayName({ profile: patientProfile })
      || resolvePatientListDisplayName(patientProfile)
      || 'ce patient'
    const confirmed = window.confirm(
      `Retirer ${patientName} de votre liste de suivi ?\n\nLe patient sera averti par email. Ses données VitalIO restent sur son compte.`,
    )
    if (!confirmed) return

    try {
      setRemovePatientSubmitting(true)
      setRemovePatientError('')
      const token = await getAccessTokenSilently()
      await removeDoctorPatient(token, patientId)
      navigate('/doctor')
    } catch (e) {
      setRemovePatientError(e.message || 'Impossible de retirer ce patient.')
    } finally {
      setRemovePatientSubmitting(false)
    }
  }

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
                      <h3><User size={20} /> Profil patient</h3>
                    </div>
                    <div className="doctor-profile-sections">
                      <div>
                        <h4 className="doctor-profile-block__title">Identité</h4>
                        <div className="doctor-profile-grid">
                          <ProfileField label="Prénom" value={patientProfile.first_name} />
                          <ProfileField label="Nom" value={patientProfile.last_name} />
                          <ProfileField label="Date de naissance" value={patientProfile.birthdate ? new Date(patientProfile.birthdate).toLocaleDateString('fr-FR') : null} />
                          <ProfileField label="Âge" value={computeAge(patientProfile.birthdate, patientProfile.age) != null ? `${computeAge(patientProfile.birthdate, patientProfile.age)} ans` : null} />
                          <ProfileField label="Sexe" value={patientProfile.sex === 'm' ? 'Homme' : patientProfile.sex === 'f' ? 'Femme' : patientProfile.sex === 'o' ? 'Autre' : patientProfile.sex} />
                        </div>
                      </div>
                      <div>
                        <h4 className="doctor-profile-block__title">Contact</h4>
                        <div className="doctor-profile-grid">
                          <ProfileField label="Téléphone" value={patientProfile.phone} link={patientProfile.phone ? `tel:${patientProfile.phone.replace(/\s/g, '')}` : null} />
                          <ProfileField label="Email" value={patientProfile.email} link={patientProfile.email ? `mailto:${patientProfile.email}` : null} />
                        </div>
                      </div>
                      <div>
                        <h4 className="doctor-profile-block__title">Urgences — adresse &amp; SAMU</h4>
                        <p className="doctor-profile-note">
                          À utiliser si vous devez orienter les secours vers le domicile du patient.
                        </p>
                        {formatPatientAddressLines(patientProfile).length > 0 ? (
                          <div className="doctor-profile-address-row">
                            <p>
                              {formatPatientAddressLines(patientProfile).join(', ')}
                            </p>
                            <button
                              type="button"
                              className="doctor-btn doctor-btn-secondary"
                              onClick={() => {
                                const t = formatPatientAddressLines(patientProfile).join(', ')
                                navigator.clipboard.writeText(t).catch(() => {})
                              }}
                            >
                              <Copy size={16} /> Copier l&apos;adresse
                            </button>
                          </div>
                        ) : (
                          <p className="doctor-profile-empty">Adresse non renseignée par le patient.</p>
                        )}
                      </div>
                      <div>
                        <h4 className="doctor-profile-block__title">Antécédents médicaux</h4>
                        <p className="doctor-profile-text">{patientProfile.medical_history || 'Non renseigné'}</p>
                      </div>
                      <div>
                        <h4 className="doctor-profile-block__title">Statut</h4>
                        <span className="doctor-profile-status">
                          <span className={`doctor-profile-status__dot ${patientProfile.onboarding_completed ? 'doctor-profile-status__dot--ok' : 'doctor-profile-status__dot--pending'}`} />
                          {patientProfile.onboarding_completed ? 'Onboarding complété' : 'Onboarding en attente'}
                        </span>
                      </div>
                      <div className="doctor-profile-divider">
                        <h4 className="doctor-profile-block__title">Association</h4>
                        <p className="doctor-profile-note">
                          Retirer ce patient de votre liste de suivi. Il sera informé par email et conservera l&apos;accès à son compte VitalIO.
                        </p>
                        <button
                          type="button"
                          className="doctor-btn doctor-btn-danger-outline"
                          onClick={handleRemovePatient}
                          disabled={removePatientSubmitting}
                        >
                          <Trash2 size={16} />
                          {removePatientSubmitting ? 'Retrait en cours...' : 'Retirer ce patient'}
                        </button>
                        {removePatientError && <p className="doctor-error" style={{ marginTop: '0.75rem' }}>{removePatientError}</p>}
                      </div>
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
                {!measurementsShowAll && measurements.length === DOCTOR_MEASUREMENTS_PREVIEW_LIMIT && (
                  <div className="doctor-measurements-more">
                    <button
                      type="button"
                      className="doctor-btn doctor-btn-secondary"
                      onClick={loadAllMeasurements}
                      disabled={measurementsLoadingMore}
                    >
                      {measurementsLoadingMore ? 'Chargement…' : 'Afficher toutes les mesures'}
                    </button>
                  </div>
                )}
              </div>
              </section>
              {(weeklySummaryLoading || weeklySummaryError || weeklyClinicalSummary?.text) && (
                      <div className="doctor-weekly-narrative">
                        <h4 className="doctor-weekly-narrative__title">
                          <FileText size={18} /> Résumé des 7 derniers jours (mesures)
                        </h4>
                        <p className="doctor-weekly-narrative__sub">
                          Synthèse automatique basée sur les constantes enregistrées sur une semaine glissante (même source que le suivi avancé, période 7 jours).
                        </p>
                        {weeklySummaryLoading && (
                          <p className="doctor-weekly-narrative__body" style={{ color: '#64748b' }}>Chargement du résumé…</p>
                        )}
                        {weeklySummaryError && !weeklySummaryLoading && (
                          <p className="doctor-weekly-narrative__body" style={{ color: '#b91c1c' }}>{weeklySummaryError}</p>
                        )}
                        {!weeklySummaryLoading && weeklyClinicalSummary?.text && (
                          <>
                            <span
                              className="doctor-weekly-narrative__badge"
                              style={{
                                background: weeklyRiskForDisplay.bg,
                                color: weeklyRiskForDisplay.color,
                              }}
                            >
                              {weeklyRiskForDisplay.label}
                            </span>
                            <p className="doctor-weekly-narrative__body">{weeklyClinicalSummary.text}</p>
                            {weeklyClinicalSummary.recommended_action && (
                              <p className="doctor-weekly-narrative__action">{weeklyClinicalSummary.recommended_action}</p>
                            )}
                          </>
                        )}
                      </div>
                    )}
              <section className="doctor-patients-section">
                <div className="doctor-patients-card">
                  <div className="section-header">
                    <h3><Cpu size={20} /> Boîtier patient</h3>
                  </div>
                  <p style={{ margin: '0 0 1rem', fontSize: '0.875rem', color: '#64748b', lineHeight: 1.5 }}>
                    Saisissez ou scannez l’identifiant matériel affiché sur le boîtier.
                    Une fois enregistré, le patient peut terminer l’enrôlement à domicile.
                  </p>
                  {patientDevice?.assigned_at && (
                    <p style={{ margin: '0 0 0.75rem', fontSize: '0.8rem', color: '#94a3b8' }}>
                      Dernière association côté dossier&nbsp;:{' '}
                      {new Date(patientDevice.assigned_at).toLocaleString('fr-FR')}
                    </p>
                  )}
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.75rem', alignItems: 'flex-start' }}>
                    <label style={{ flex: '1 1 220px', display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
                      <span style={{ fontSize: '0.75rem', color: '#64748b' }}>Device ID</span>
                      <input
                        type="text"
                        style={{
                          width: '100%',
                          padding: '0.6rem 0.75rem',
                          borderRadius: '8px',
                          border: '1px solid #e2e8f0',
                          fontSize: '0.95rem',
                        }}
                        placeholder="VITALIO-XXXXXXXX"
                        value={deviceIdInput}
                        onChange={(ev) => setDeviceIdInput(normalizeDeviceIdInput(ev.target.value))}
                        autoComplete="off"
                        spellCheck="false"
                      />
                    </label>
                    <button
                      type="button"
                      className="doctor-btn doctor-btn-primary"
                      style={{ marginTop: '1.35rem' }}
                      disabled={deviceSaving}
                      onClick={submitPatientDevice}
                    >
                      {deviceSaving ? 'Enregistrement…' : 'Enregistrer le boîtier'}
                    </button>
                  </div>
                  {deviceError && <p className="doctor-error" style={{ marginTop: '0.75rem' }}>{deviceError}</p>}
                  {deviceSuccess && (
                    <p style={{ marginTop: '0.75rem', color: '#15803d', fontSize: '0.875rem' }}>{deviceSuccess}</p>
                  )}
                </div>
              </section>

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
