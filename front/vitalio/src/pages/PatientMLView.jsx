import React, { useEffect, useMemo, useState } from 'react'
import { useAuth0 } from '@auth0/auth0-react'
import {
  BrainCircuit,
  ShieldAlert,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  TrendingUp,
  Activity,
  Info,
} from 'lucide-react'
import {
  LineChart, Line, AreaChart, Area, BarChart, Bar, Cell, LabelList,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts'
import { getPatientData, getMLModelInfo } from '../services/api'
import PatientLayout from '../components/PatientLayout'

const LEVEL_CONFIG = {
  normal:   { color: '#047857', bg: '#ecfdf5', label: 'Normal',   Icon: CheckCircle2 },
  warning:  { color: '#b45309', bg: '#fffbeb', label: 'Alerte',   Icon: AlertTriangle },
  critical: { color: '#b91c1c', bg: '#fef2f2', label: 'Critique', Icon: XCircle },
}

const formatTime = (iso) => {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

const formatShort = (iso) => {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleString('fr-FR', { day: '2-digit', month: '2-digit' })
}

export default function PatientMLView() {
  const { getAccessTokenSilently } = useAuth0()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [measurements, setMeasurements] = useState([])
  const [modelInfo, setModelInfo] = useState(null)

  useEffect(() => {
    let mounted = true
    const load = async () => {
      try {
        setLoading(true)
        setError('')
        const token = await getAccessTokenSilently()
        const [data, mlInfo] = await Promise.all([
          getPatientData(token),
          getMLModelInfo().catch(() => null),
        ])
        if (mounted) {
          setMeasurements(Array.isArray(data.measurements) ? data.measurements : [])
          setModelInfo(mlInfo)
        }
      } catch (e) {
        if (mounted) setError(e.message || 'Erreur de chargement')
      } finally {
        if (mounted) setLoading(false)
      }
    }
    load()
    return () => { mounted = false }
  }, [getAccessTokenSilently])

  const mlData = useMemo(() => {
    const withScore = measurements
      .filter((m) => m.ml_score != null)
      .slice()
      .reverse()

    const scoreSeries = withScore.map((m) => ({
      timestamp: formatShort(m.timestamp),
      fullTime: formatTime(m.timestamp),
      score: Number((m.ml_score ?? 0).toFixed(3)),
      level: m.ml_level || 'normal',
    }))

    const counts = { normal: 0, warning: 0, critical: 0 }
    withScore.forEach((m) => {
      const lvl = m.ml_level || 'normal'
      if (counts[lvl] !== undefined) counts[lvl]++
    })

    const vitalSeries = withScore.slice(-60).map((m) => ({
      timestamp: formatShort(m.timestamp),
      heart_rate: m.heart_rate,
      spo2: m.spo2,
      temperature: m.temperature,
      score: Number((m.ml_score ?? 0).toFixed(3)),
    }))

    const anomalies = withScore
      .filter((m) => m.ml_level === 'critical' || m.ml_level === 'warning')
      .slice(-20)
      .reverse()

    // Récapitulatif global : dernières mesures pour le graphique patient
    const recent = measurements
      .filter((m) => m.heart_rate != null || m.spo2 != null || m.temperature != null)
      .slice(-14)
      .reverse() // [0] = plus récent
    const latest = (key) => {
      const m = recent.find((x) => x[key] != null)
      return m ? Number(m[key]) : null
    }
    const summaryBars = [
      { nom: 'Fréquence cardiaque', valeur: latest('heart_rate'), unite: 'bpm', couleur: '#b91c1c', zoneNormale: [60, 100] },
      { nom: 'Oxygène dans le sang', valeur: latest('spo2'), unite: '%', couleur: '#1d4ed8', zoneNormale: [95, 100] },
      { nom: 'Température', valeur: latest('temperature'), unite: '°C', couleur: '#b45309', zoneNormale: [36.5, 37.5] },
    ]
      .filter((b) => b.valeur != null)
      .map((b) => ({ ...b, label: b.unite === '°C' ? `${Number(b.valeur).toFixed(1)} ${b.unite}` : `${b.valeur} ${b.unite}` }))

    return { scoreSeries, counts, vitalSeries, anomalies, total: withScore.length, summaryBars }
  }, [measurements])

  const CustomTooltip = ({ active, payload }) => {
    if (!active || !payload?.length) return null
    const d = payload[0].payload
    return (
      <div className="ml-chart-tooltip">
        <p className="ml-chart-tooltip-time">{d.fullTime || d.timestamp}</p>
        {payload.map((p) => (
          <p key={p.dataKey} style={{ color: p.color }}>
            {p.name}: <strong>{p.value}</strong>
          </p>
        ))}
      </div>
    )
  }

  return (
    <PatientLayout>
      <div className="patient-ml">
        <header className="ml-header">
          <div>
            <h1><BrainCircuit size={28} /> Analyse de mes mesures</h1>
            <p>Détection d'anomalies par Intelligence Artificielle sur vos constantes vitales.</p>
          </div>
          {modelInfo && (
            <div className="ml-model-badge">
              <Info size={14} />
              <span>Modèle {modelInfo.version}{modelInfo.loaded ? '' : ' (non chargé)'}</span>
            </div>
          )}
        </header>

        {loading && <div className="ml-panel">Chargement des données ML...</div>}
        {!loading && error && (
          <div className="ml-panel ml-panel--error">
            <ShieldAlert size={20} /> <span>{error}</span>
          </div>
        )}

        {!loading && !error && (
          <>
            {/* KPI cards */}
            <section className="ml-kpi-grid">
              {Object.entries(LEVEL_CONFIG).map(([level, cfg]) => {
                const count = mlData.counts[level] || 0
                const Icon = cfg.Icon
                return (
                  <article key={level} className="ml-kpi-card" style={{ borderColor: cfg.color, background: cfg.bg }}>
                    <Icon size={22} color={cfg.color} />
                    <div>
                      <span className="ml-kpi-value" style={{ color: cfg.color }}>{count}</span>
                      <span className="ml-kpi-label">{cfg.label}</span>
                    </div>
                  </article>
                )
              })}
              <article className="ml-kpi-card" style={{ borderColor: '#1d4ed8', background: '#eff6ff' }}>
                <TrendingUp size={22} color="#1d4ed8" />
                <div>
                  <span className="ml-kpi-value" style={{ color: '#1d4ed8' }}>{mlData.total}</span>
                  <span className="ml-kpi-label">Total analysé</span>
                </div>
              </article>
            </section>

            {mlData.summaryBars.length > 0 && (
              <section className="ml-panel ml-panel--summary">
                <h2><Activity size={18} /> Vue d'ensemble de mes dernières mesures</h2>
                <p className="ml-panel-sub">Valeurs les plus récentes de vos constantes vitales.</p>
                <div className="ml-chart-wrap ml-summary-chart">
                  <ResponsiveContainer width="100%" height={200}>
                    <BarChart
                      data={mlData.summaryBars}
                      layout="vertical"
                      margin={{ top: 10, right: 50, left: 0, bottom: 10 }}
                    >
                      <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
                      <XAxis type="number" tick={{ fontSize: 11 }} domain={[0, 'auto']} />
                      <YAxis type="category" dataKey="nom" width={160} tick={{ fontSize: 12 }} />
                      <Tooltip
                        content={({ active, payload }) => {
                          if (!active || !payload?.length) return null
                          const d = payload[0].payload
                          const afficher = d.unite === '°C' ? Number(d.valeur).toFixed(1) : d.valeur
                          return (
                            <div className="ml-chart-tooltip">
                              <p className="ml-chart-tooltip-time">{d.nom}</p>
                              <p><strong>{afficher} {d.unite}</strong></p>
                              <p style={{ fontSize: '0.75rem', color: '#64748b' }}>
                                Zone habituelle : {d.zoneNormale[0]}–{d.zoneNormale[1]} {d.unite}
                              </p>
                            </div>
                          )
                        }}
                      />
                      <Bar dataKey="valeur" radius={[0, 4, 4, 0]}>
                        {mlData.summaryBars.map((entry, i) => (
                          <Cell key={i} fill={entry.couleur} />
                        ))}
                        <LabelList dataKey="label" position="right" />
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </section>
            )}

            {mlData.scoreSeries.length === 0 && (
              <div className="ml-panel ml-panel--info">
                <Info size={20} />
                <span>Retrouvez ici résumés et analyses de vos mesures.</span>
              </div>
            )}

            {mlData.scoreSeries.length > 0 && (
              <>
                <section className="ml-panel">
                  <h2><Activity size={18} /> Score d'anomalie dans le temps</h2>
                  <p className="ml-panel-sub">Plus le score est élevé, plus la mesure est inhabituielle.</p>
                  <div className="ml-chart-wrap">
                    <ResponsiveContainer width="100%" height={280}>
                      <AreaChart data={mlData.scoreSeries} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                        <defs>
                          <linearGradient id="scoreGrad" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#1d4ed8" stopOpacity={0.25} />
                            <stop offset="95%" stopColor="#1d4ed8" stopOpacity={0} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                        <XAxis dataKey="timestamp" tick={{ fontSize: 11 }} />
                        <YAxis domain={[0, 1]} tick={{ fontSize: 11 }} />
                        <Tooltip content={<CustomTooltip />} />
                        <Area
                          type="monotone" dataKey="score" name="Score ML"
                          stroke="#1d4ed8" fill="url(#scoreGrad)" strokeWidth={2}
                          dot={false} activeDot={{ r: 4, fill: '#1d4ed8' }}
                        />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                </section>

                {/* Vitals overlay with ML score */}
                <section className="ml-panel">
                  <h2>Constantes vitales &amp; score ML</h2>
                  <p className="ml-panel-sub">Superposition des mesures physiologiques et du score d'anomalie.</p>
                  <div className="ml-chart-wrap">
                    <ResponsiveContainer width="100%" height={300}>
                      <LineChart data={mlData.vitalSeries} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                        <XAxis dataKey="timestamp" tick={{ fontSize: 11 }} />
                        <YAxis yAxisId="vitals" tick={{ fontSize: 11 }} />
                        <YAxis yAxisId="score" orientation="right" domain={[0, 1]} tick={{ fontSize: 11 }} />
                        <Tooltip content={<CustomTooltip />} />
                        <Legend />
                        <Line yAxisId="vitals" type="monotone" dataKey="heart_rate" name="FC (bpm)" stroke="#b91c1c" dot={false} strokeWidth={1.5} />
                        <Line yAxisId="vitals" type="monotone" dataKey="spo2" name="SpO2 (%)" stroke="#1d4ed8" dot={false} strokeWidth={1.5} />
                        <Line yAxisId="vitals" type="monotone" dataKey="temperature" name="Temp (°C)" stroke="#b45309" dot={false} strokeWidth={1.5} />
                        <Line yAxisId="score" type="monotone" dataKey="score" name="Score ML" stroke="#1d4ed8" dot={false} strokeWidth={2} strokeDasharray="5 3" />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                </section>

                {mlData.anomalies.length > 0 && (
                  <section className="ml-panel">
                    <h2><AlertTriangle size={18} /> Dernières anomalies détectées</h2>
                    <div className="ml-anomaly-table-wrap">
                      <table className="ml-anomaly-table">
                        <thead>
                          <tr>
                            <th>Date</th>
                            <th>Niveau</th>
                            <th>Score</th>
                            <th>FC</th>
                            <th>SpO2</th>
                            <th>Temp</th>
                          </tr>
                        </thead>
                        <tbody>
                          {mlData.anomalies.map((m, i) => {
                            const cfg = LEVEL_CONFIG[m.ml_level] || LEVEL_CONFIG.warning
                            return (
                              <tr key={`${m.timestamp}-${i}`}>
                                <td>{formatTime(m.timestamp)}</td>
                                <td>
                                  <span className="ml-level-badge" style={{ background: cfg.bg, color: cfg.color }}>
                                    {cfg.label}
                                  </span>
                                </td>
                                <td>{(m.ml_score ?? 0).toFixed(3)}</td>
                                <td>{m.heart_rate ?? '-'}</td>
                                <td>{m.spo2 ?? '-'}</td>
                                <td>{m.temperature != null ? Number(m.temperature).toFixed(1) : '-'}</td>
                              </tr>
                            )
                          })}
                        </tbody>
                      </table>
                    </div>
                  </section>
                )}
              </>
            )}
          </>
        )}
      </div>
    </PatientLayout>
  )
}
