import React, { useEffect, useMemo, useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useAuth0 } from '@auth0/auth0-react'
import { ArrowLeft, CheckCircle2, Heart, TriangleAlert, Users } from 'lucide-react'
import { getCaregiverPatients, getCaregiverAlerts, patchCaregiverAlert } from '../services/api'

function formatLastTime(timestamp) {
  if (!timestamp) return 'Aucune mesure'
  return new Date(timestamp).toLocaleString('fr-FR')
}

export default function FamilyView() {
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const base = pathname.startsWith('/family') ? '/family' : '/caregiver'
  const { getAccessTokenSilently } = useAuth0()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [patients, setPatients] = useState([])
  const [alerts, setAlerts] = useState([])
  const [resolvingAlertId, setResolvingAlertId] = useState(null)
  const [resolutionComment, setResolutionComment] = useState('')
  const [resolutionError, setResolutionError] = useState('')

  useEffect(() => {
    let mounted = true
    const load = async () => {
      try {
        setLoading(true)
        setError('')
        const token = await getAccessTokenSilently()
        const [patientsRes, alertsRes] = await Promise.all([
          getCaregiverPatients(token),
          getCaregiverAlerts(token, { status: 'OPEN' }),
        ])
        if (mounted) {
          const pts = Array.isArray(patientsRes.patients) ? patientsRes.patients : []
          setPatients(pts)
          setAlerts(Array.isArray(alertsRes.alerts) ? alertsRes.alerts : [])
          if (pts.length === 1) {
            navigate(`${base}/patient/${encodeURIComponent(pts[0].id || pts[0].patient_id)}`, { replace: true })
          }
        }
      } catch (fetchError) {
        if (mounted) {
          setError(fetchError.message || 'Impossible de charger les données')
        }
      } finally {
        if (mounted) setLoading(false)
      }
    }
    load()
    return () => {
      mounted = false
    }
  }, [getAccessTokenSilently, navigate])

  const filteredPatients = patients

  const patientNames = useMemo(() => {
    const m = {}
    patients.forEach((p) => {
      const key = p.id || p.patient_id
      if (key) m[key] = p.display_name || p.patient_id
    })
    return m
  }, [patients])

  const alertCount = filteredPatients.filter((p) => p.alert).length

  const handleResolveAlert = async (alertId) => {
    const comment = resolutionComment.trim()
    if (!comment) {
      setResolutionError('Veuillez indiquer ce qui a été fait (ex. : vérification sur place, appel au médecin).')
      return
    }
    try {
      setResolutionError('')
      const token = await getAccessTokenSilently()
      const res = await patchCaregiverAlert(token, alertId, comment)
      setAlerts((prev) =>
        prev.map((a) =>
          (a.alert_id === alertId)
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

  return (
    <div className="caregiver-dashboard family-theme">
      <div className="main-content">
        <header className="caregiver-header">
          <div className="caregiver-header-left">
            <button
              className="caregiver-back-btn"
              onClick={() => navigate('/home')}
              aria-label="Retour à l'accueil"
            >
              <ArrowLeft size={20} />
            </button>
            <div>
              <h1 className="caregiver-title">Espace aidant</h1>
              <p className="caregiver-subtitle">Suivez les constantes vitales de votre proche</p>
            </div>
          </div>
        </header>

        <main className="caregiver-main">
          <section className="caregiver-stats">
            <article className="caregiver-stat-card caregiver-stat-patients">
              <div className="caregiver-stat-icon">
                <Users size={24} />
              </div>
              <div className="caregiver-stat-content">
                <span className="caregiver-stat-value">{patients.length}</span>
                <span className="caregiver-stat-label">Patients suivis</span>
              </div>
            </article>
            <article className="caregiver-stat-card caregiver-stat-alerts">
              <div className="caregiver-stat-icon">
                <TriangleAlert size={24} />
              </div>
              <div className="caregiver-stat-content">
                <span className="caregiver-stat-value">{alertCount}</span>
                <span className="caregiver-stat-label">Alertes actives</span>
              </div>
            </article>
          </section>

          {alerts.length > 0 && (
            <section className="caregiver-alerts-section">
              <h3><TriangleAlert size={20} /> Alertes à surveiller</h3>
              <div className="caregiver-alerts-list">
                {alerts.map((a, i) => (
                  <article key={a.alert_id || i} className="caregiver-alert-card">
                    <strong>{patientNames[a.patient_id] || a.patient_id}</strong>
                    <p className="caregiver-alert-summary">{a.summary}</p>
                    <p className="caregiver-alert-description">{a.lay_description}</p>
                    {a.caregiver_resolution_comment && (
                      <p className="caregiver-alert-resolution">
                        <CheckCircle2 size={14} /> {a.caregiver_resolution_comment}
                      </p>
                    )}
                    <div className="caregiver-alert-actions">
                      <button
                        type="button"
                        className="caregiver-alert-view-btn"
                        onClick={() => navigate(`${base}/patient/${encodeURIComponent(a.patient_id || '')}`)}
                      >
                        Voir le patient
                      </button>
                      {!a.caregiver_resolution_comment && a.status === 'OPEN' && (
                        <button
                          type="button"
                          className="caregiver-alert-resolve-btn"
                          onClick={() => setResolvingAlertId(resolvingAlertId === a.alert_id ? null : a.alert_id)}
                        >
                          <CheckCircle2 size={14} /> Urgence résolue
                        </button>
                      )}
                    </div>
                    {resolvingAlertId === a.alert_id && (
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
                            onClick={() => handleResolveAlert(a.alert_id)}
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

          <section className="caregiver-patients-section">
            <div className="section-header">
              <h3>Mon proche</h3>
            </div>

            {loading && (
              <div className="caregiver-loading">
                <div className="caregiver-loading-spinner" />
                <p>Chargement en cours...</p>
              </div>
            )}
            {!loading && error && <p className="caregiver-error">{error}</p>}
            {!loading && !error && filteredPatients.length === 0 && (
              <div className="caregiver-empty">
                <Users size={48} strokeWidth={1.5} />
                <p>Aucun proche associé</p>
                <span>Votre proche apparaîtra ici une fois l'invitation acceptée</span>
              </div>
            )}
            {!loading && !error && filteredPatients.length > 0 && (
              <div className="caregiver-table-wrap">
                <table className="caregiver-table">
                  <thead>
                    <tr>
                      <th>Patient</th>
                      <th>Dernière mesure</th>
                      <th>SpO2</th>
                      <th>FC</th>
                      <th>Température</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredPatients.map((patient) => {
                      const hasAlert = patient.alert
                      return (
                        <tr
                          key={patient.id || patient.patient_id}
                          className={`caregiver-patient-row ${hasAlert ? 'caregiver-patient-row--alert' : ''}`}
                          onClick={() => navigate(`${base}/patient/${encodeURIComponent(patient.id || patient.patient_id)}`)}
                        >
                          <td>
                            <span className="caregiver-table-name">{patient.display_name}</span>
                            {hasAlert && (
                              <span className="caregiver-alert-badge" title="Alerte sur les constantes vitales">
                                <TriangleAlert size={14} /> Alerte
                              </span>
                            )}
                          </td>
                          <td>{formatLastTime(patient.last_measurement?.timestamp)}</td>
                          <td>{patient.last_measurement?.spo2 ?? '-'}</td>
                          <td>{patient.last_measurement?.heart_rate ?? '-'}</td>
                          <td>{patient.last_measurement?.temperature ?? '-'}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </main>
      </div>
    </div>
  )
}
