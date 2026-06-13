import React, { useEffect, useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useAuth0 } from '@auth0/auth0-react'
import { ArrowLeft, Heart, TriangleAlert, Users } from 'lucide-react'
import { getCaregiverPatients, getCaregiverAlerts } from '../services/api'

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

  const hasNotifiedRef = React.useRef(false)
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
  }, [getAccessTokenSilently, navigate, base])

  // Notification navigateur au chargement si des alertes ouvertes
  useEffect(() => {
    if (loading || hasNotifiedRef.current) return
    const openCount = alerts.filter((a) => a.status === 'OPEN').length
    if (openCount > 0 && typeof window !== 'undefined' && 'Notification' in window) {
      hasNotifiedRef.current = true
      try {
        if (Notification.permission === 'granted') {
          new Notification('VitalIO - Alertes à surveiller', {
            body: `${openCount} alerte(s) ouverte(s) pour votre proche.`,
            icon: '/favicon.ico',
          })
        } else if (Notification.permission !== 'denied') {
          Notification.requestPermission().then((p) => {
            if (p === 'granted') {
              new Notification('VitalIO - Alertes à surveiller', {
                body: `${openCount} alerte(s) ouverte(s) pour votre proche.`,
                icon: '/favicon.ico',
              })
            }
          })
        }
      } catch (e) {
        console.warn('Notification non disponible:', e)
      }
    }
  }, [alerts, loading])

  const filteredPatients = patients

  const alertCount = Math.max(
    alerts.filter((a) => a.status === 'OPEN').length,
    filteredPatients.filter((p) => p.alert).length
  )

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
            <article
              className="caregiver-stat-card caregiver-stat-alerts"
              role="button"
              tabIndex={0}
              aria-label={`${alertCount} alerte${alertCount !== 1 ? 's' : ''} ouverte${alertCount !== 1 ? 's' : ''} — voir la liste des alertes`}
              onClick={() => navigate(`${base}/alertes`)}
              onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && navigate(`${base}/alertes`)}
              style={{ cursor: 'pointer' }}
            >
              <div className="caregiver-stat-icon">
                <TriangleAlert size={24} aria-hidden />
              </div>
              <div className="caregiver-stat-content">
                <span className="caregiver-stat-value caregiver-stat-value--critical">{alertCount}</span>
                <span className="caregiver-stat-label">Alertes ouvertes</span>
              </div>
            </article>
          </section>

          {alertCount > 0 && (
            <section className="caregiver-alerts-section" aria-label="Accès aux alertes ouvertes">
              <button
                type="button"
                className="caregiver-alert-view-btn"
                aria-label={`Voir toutes les alertes — ${alertCount} ouverte${alertCount > 1 ? 's' : ''}`}
                onClick={() => navigate(`${base}/alertes`)}
                style={{ width: '100%', justifyContent: 'center', padding: '0.75rem 1rem' }}
              >
                <TriangleAlert size={18} aria-hidden /> Voir toutes les alertes ({alertCount})
              </button>
            </section>
          )}

          <section className="caregiver-patients-section" aria-labelledby="family-patients-heading">
            <div className="section-header">
              <h3 id="family-patients-heading">Mon proche</h3>
            </div>

            {loading && (
              <div className="caregiver-loading" role="status" aria-live="polite">
                <div className="caregiver-loading-spinner" aria-hidden />
                <p>Chargement en cours...</p>
              </div>
            )}
            {!loading && error && <p className="caregiver-error" role="alert">{error}</p>}
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
