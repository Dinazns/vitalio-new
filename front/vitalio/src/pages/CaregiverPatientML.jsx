import React, { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams, useLocation } from 'react-router-dom'
import { useAuth0 } from '@auth0/auth0-react'
import {
  ArrowLeft,
  BrainCircuit,
  Wind,
  Thermometer,
  HeartPulse,
  ChevronDown,
  History,
  CalendarDays,
  Info,
  ShieldAlert,
} from 'lucide-react'
import {
  getPatientMeasurementsById,
  getPatientMLAnalysis,
  getPatientProfileForDoctor,
} from '../services/api'
import { resolvePatientFullName } from '../utils/displayName'
import { formatRelativeMeasurementTime, getVitalStatus } from '../utils/vitalStatus'
import VitalSignCard from '../components/patient/VitalSignCard'
import VitalTrendChart from '../components/patient/VitalTrendChart'
import OverallStatusBanner from '../components/patient/OverallStatusBanner'
import LayNarrativeSummary from '../components/caregiver/LayNarrativeSummary'

export default function CaregiverPatientML() {
  const { patientId } = useParams()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const base = pathname.startsWith('/family') ? '/family' : '/caregiver'
  const { getAccessTokenSilently } = useAuth0()

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [analysis, setAnalysis] = useState(null)
  const [measurements, setMeasurements] = useState([])
  const [patientProfile, setPatientProfile] = useState(null)
  const [days, setDays] = useState(7)
  const [historyExpanded, setHistoryExpanded] = useState(false)

  useEffect(() => {
    let mounted = true
    ;(async () => {
      try {
        setLoading(true)
        setError('')
        const token = await getAccessTokenSilently()
        const [analysisRes, measurementsRes, profileRes] = await Promise.all([
          getPatientMLAnalysis(token, patientId, { days, include_forecast: false }),
          getPatientMeasurementsById(token, patientId, { limit: 500 }),
          getPatientProfileForDoctor(token, patientId).catch(() => ({ profile: null })),
        ])
        if (!mounted) return
        setAnalysis(analysisRes)
        setMeasurements(Array.isArray(measurementsRes.measurements) ? measurementsRes.measurements : [])
        setPatientProfile(profileRes?.profile || null)
      } catch (e) {
        if (mounted) setError(e.message || 'Impossible de charger le suivi avancé')
      } finally {
        if (mounted) setLoading(false)
      }
    })()
    return () => { mounted = false }
  }, [getAccessTokenSilently, patientId, days])

  const patientName = resolvePatientFullName({ profile: patientProfile })
  const latest = measurements[0]
  const previous = measurements[1]
  const laySummary = analysis?.lay_narrative_summary

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
    <div className="caregiver-dashboard family-theme">
      <div className="main-content caregiver-detail-page">
        <header className="caregiver-header">
          <div className="caregiver-header-left">
            <button
              type="button"
              className="caregiver-back-btn"
              onClick={() => navigate(`${base}/patient/${encodeURIComponent(patientId)}`)}
              aria-label="Retour au tableau de bord du proche"
            >
              <ArrowLeft size={20} />
            </button>
            <div>
              <h1 className="caregiver-title">
                <BrainCircuit size={24} aria-hidden />
                Suivi avancé{patientName ? ` - ${patientName}` : ''}
              </h1>
              <p className="caregiver-subtitle">Tendances et résumé en langage simple</p>
            </div>
          </div>
        </header>

        <main className="caregiver-main caregiver-detail-main">
          <div className="caregiver-period-bar" role="group" aria-label="Période d'analyse">
            <CalendarDays size={18} aria-hidden />
            {[7, 14, 30].map((d) => (
              <button
                key={d}
                type="button"
                className={`caregiver-period-btn ${days === d ? 'caregiver-period-btn--active' : ''}`}
                onClick={() => setDays(d)}
              >
                {d} jours
              </button>
            ))}
          </div>

          {loading && (
            <div className="caregiver-panel" role="status">Chargement du suivi avancé…</div>
          )}

          {!loading && error && (
            <div className="caregiver-panel caregiver-panel--error" role="alert">
              <ShieldAlert size={20} aria-hidden />
              <span>{error}</span>
            </div>
          )}

          {!loading && !error && analysis?.code === 'insufficient_data' && (
            <div className="caregiver-panel caregiver-panel--notice" role="status">
              <Info size={20} aria-hidden />
              <div>
                <strong>Pas assez de mesures sur cette période</strong>
                <p>{analysis.message}</p>
                {analysis.suggested_days && analysis.suggested_days !== days && (
                  <button
                    type="button"
                    className="caregiver-period-btn caregiver-period-btn--active"
                    onClick={() => setDays(analysis.suggested_days)}
                  >
                    Essayer {analysis.suggested_days} jours
                  </button>
                )}
              </div>
            </div>
          )}

          {!loading && !error && (
            <>
              {laySummary && <LayNarrativeSummary summary={laySummary} />}

              <OverallStatusBanner statuses={vitalStatuses} />

              <section className="vital-cards" aria-label="Dernières constantes vitales">
                <VitalSignCard vitalKey="spo2" label="SpO₂" value={latest?.spo2} previousValue={previous?.spo2} Icon={Wind} />
                <VitalSignCard vitalKey="heart_rate" label="Fréquence cardiaque" value={latest?.heart_rate} previousValue={previous?.heart_rate} Icon={HeartPulse} />
                <VitalSignCard vitalKey="temperature" label="Température" value={latest?.temperature} previousValue={previous?.temperature} Icon={Thermometer} />
              </section>

              {lastMeasurementLabel && (
                <p className="vital-last-measurement" role="status">
                  Dernière mesure : {lastMeasurementLabel}
                </p>
              )}

              <section className="caregiver-panel">
                <h2 className="caregiver-panel__title">Courbes sur {days} jours</h2>
                <VitalTrendChart measurements={measurements} showDisclaimer />
              </section>

              <section className={`caregiver-panel caregiver-panel--collapsible ${historyExpanded ? 'caregiver-panel--open' : ''}`}>
                <button
                  type="button"
                  className="caregiver-panel__toggle"
                  onClick={() => setHistoryExpanded((open) => !open)}
                  aria-expanded={historyExpanded}
                  aria-controls="caregiver-ml-history"
                >
                  <span className="caregiver-panel__toggle-title">
                    <History size={18} aria-hidden /> Historique des mesures
                  </span>
                  <span className="caregiver-panel__toggle-meta">{measurements.length} mesure(s)</span>
                  <ChevronDown size={20} className={`caregiver-panel__chevron ${historyExpanded ? 'caregiver-panel__chevron--open' : ''}`} aria-hidden />
                </button>
                {historyExpanded && (
                  <div id="caregiver-ml-history" className="caregiver-panel__body">
                    <div className="caregiver-table-wrap">
                      <table className="caregiver-table">
                        <thead>
                          <tr>
                            <th>Date</th>
                            <th>SpO₂</th>
                            <th>FC</th>
                            <th>Temp.</th>
                          </tr>
                        </thead>
                        <tbody>
                          {measurements.map((m, index) => (
                            <tr key={`${m.timestamp}-${index}`}>
                              <td>{m.timestamp ? new Date(m.timestamp).toLocaleString('fr-FR') : '-'}</td>
                              <td>{m.spo2 ?? '-'}</td>
                              <td>{m.heart_rate ?? '-'}</td>
                              <td>{m.temperature != null ? Number(m.temperature).toFixed(1) : '-'}</td>
                            </tr>
                          ))}
                          {!measurements.length && (
                            <tr><td colSpan="4">Aucune mesure disponible.</td></tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </section>
            </>
          )}
        </main>
      </div>
    </div>
  )
}
