import React, { useEffect, useMemo, useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useAuth0 } from '@auth0/auth0-react'
import {
  ArrowLeft,
  BrainCircuit,
  Activity,
  Heart,
  Thermometer,
  Wind,
  TrendingUp,
  TrendingDown,
  AlertTriangle,
  Gauge,
  Sparkles,
  ArrowRight,
  BarChart3,
  LineChart as LineChartIcon,
  ShieldAlert,
  CalendarDays,
  Info,
  Layers,
  Clock,
  Crosshair,
  CheckCircle,
  XCircle,
  ExternalLink,
} from 'lucide-react'
import {
  AreaChart, Area, BarChart, Bar, LineChart, Line,
  ComposedChart, ReferenceLine, ReferenceArea,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  Legend, Brush,
} from 'recharts'
import { getPatientMLAnalysis, patchDoctorAlert } from '../services/api'
import DoctorLayout from '../components/DoctorLayout'

const VITAL_CONFIG = {
  heart_rate: {
    label: 'Fréquence cardiaque',
    unit: 'bpm',
    color: '#b91c1c',
    gradient: ['#fecaca', '#b91c1c'],
    Icon: Heart,
  },
  spo2: {
    label: 'SpO₂',
    unit: '%',
    color: '#1d4ed8',
    gradient: ['#bfdbfe', '#1d4ed8'],
    Icon: Wind,
  },
  temperature: {
    label: 'Température',
    unit: '°C',
    color: '#047857',
    gradient: ['#bbf7d0', '#047857'],
    Icon: Thermometer,
  },
}

const LEVEL_COLORS = {
  normal: '#047857',
  warning: '#b45309',
  critical: '#b91c1c',
  threshold: '#b45309',
}

const RISK_CONFIG = {
  minimal:  { color: '#047857', bg: '#ecfdf5', label: 'Risque minimal' },
  low:      { color: '#1d4ed8', bg: '#eff6ff', label: 'Risque faible' },
  moderate: { color: '#b45309', bg: '#fffbeb', label: 'Risque modéré' },
  high:     { color: '#b91c1c', bg: '#fef2f2', label: 'Risque élevé' },
}

const formatTime = (iso) => {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

const formatDate = (iso) => {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit' })
}

/** LTTB (Largest-Triangle-Three-Buckets) - réduit les points tout en préservant la forme visuelle */
function downsampleLTTB(data, targetSize, xKey = 'index', yKey = 'value') {
  if (!data?.length || data.length <= targetSize) return data
  const n = data.length
  if (n <= 2) return data
  const sampled = [data[0]]
  const every = (n - 2) / (targetSize - 2)
  let a = 0
  for (let i = 0; i < targetSize - 2; i++) {
    const rangeStart = Math.floor(i * every) + 1
    const rangeEnd = Math.min(Math.floor((i + 1) * every) + 1, n)
    const avgRangeStart = Math.floor((i + 1) * every) + 1
    const avgRangeEnd = Math.min(Math.floor((i + 2) * every) + 1, n)
    let avgX = 0
    let avgY = 0
    for (let j = avgRangeStart; j < avgRangeEnd; j++) {
      avgX += (data[j][xKey] ?? j)
      avgY += (data[j][yKey] ?? 0)
    }
    const avgLen = avgRangeEnd - avgRangeStart || 1
    avgX /= avgLen
    avgY /= avgLen
    let maxArea = -1
    let maxIdx = rangeStart
    const prevX = data[a][xKey] ?? a
    const prevY = data[a][yKey] ?? 0
    for (let j = rangeStart; j < rangeEnd; j++) {
      const currX = data[j][xKey] ?? j
      const currY = data[j][yKey] ?? 0
      const area = 0.5 * Math.abs((prevX - avgX) * (currY - prevY) - (prevX - currX) * (avgY - prevY))
      if (area > maxArea) {
        maxArea = area
        maxIdx = j
      }
    }
    sampled.push(data[maxIdx])
    a = maxIdx
  }
  sampled.push(data[n - 1])
  return sampled
}

const CHART_DOWNSAMPLE_THRESHOLD = 800

function StatCard({ label, value, unit, icon: Icon, color, subtitle, variant }) {
  const isAlert = variant === 'alert'
  return (
    <article className={`pml-stat-card ${isAlert ? 'pml-stat-card--alert' : ''}`} style={{ '--stat-color': color || '#1d4ed8' }}>
      <div className="pml-stat-icon-wrap">
        <Icon size={22} strokeWidth={2} />
      </div>
      <div className="pml-stat-content">
        <span className="pml-stat-value">
          {value ?? '-'}<small>{unit}</small>
        </span>
        <span className="pml-stat-label">{label}</span>
        {subtitle && <span className="pml-stat-sub">{subtitle}</span>}
      </div>
    </article>
  )
}

function AnomalyDot(props) {
  const { cx, cy, payload, color } = props
  if (!payload?.is_anomaly) return <circle cx={cx} cy={cy} r={3} fill={color} />
  return (
    <g>
      <circle cx={cx} cy={cy} r={7} fill="#b91c1c" fillOpacity={0.2} />
      <circle cx={cx} cy={cy} r={4} fill="#b91c1c" stroke="#fff" strokeWidth={1.5} />
    </g>
  )
}

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div className="pml-tooltip">
      <p className="pml-tooltip-label">{label}</p>
      {payload.filter(p => p.value != null && !p.dataKey.includes('_area')).map((p, i) => (
        <p key={i} style={{ color: p.color || p.stroke }}>
          <strong>{p.name}:</strong> {typeof p.value === 'number' ? p.value.toFixed(2) : p.value}
        </p>
      ))}
    </div>
  )
}

export default function DoctorPatientML() {
  const { patientId } = useParams()
  const navigate = useNavigate()
  const { getAccessTokenSilently } = useAuth0()

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [analysis, setAnalysis] = useState(null)
  const [days, setDays] = useState(30)
  const [activeVital, setActiveVital] = useState('heart_rate')
  const [showMA, setShowMA] = useState(true)
  const [showAnomalies, setShowAnomalies] = useState(true)
  const [variabilityWindow, setVariabilityWindow] = useState(6)
  const [patchingAlerts, setPatchingAlerts] = useState({})

  const loadAnalysis = useCallback(async () => {
    try {
      setLoading(true)
      setError('')
      const token = await getAccessTokenSilently()
      const data = await getPatientMLAnalysis(token, patientId, {
        days,
        include_forecast: true,
        forecast_horizon: 24,
      })
      setAnalysis(data)
    } catch (e) {
      setError(e.message || 'Erreur de chargement')
    } finally {
      setLoading(false)
    }
  }, [getAccessTokenSilently, patientId, days])

  const handleAlertAction = useCallback(async (alertId, action) => {
    setPatchingAlerts(prev => ({ ...prev, [alertId]: true }))
    try {
      const token = await getAccessTokenSilently()
      await patchDoctorAlert(token, alertId, { action })
      await loadAnalysis()
    } catch (e) {
      console.error('Patch alert error:', e)
    } finally {
      setPatchingAlerts(prev => ({ ...prev, [alertId]: false }))
    }
  }, [getAccessTokenSilently, loadAnalysis])

  useEffect(() => { loadAnalysis() }, [loadAnalysis])

  const { vitalData, vitalDataIsDownsampled } = useMemo(() => {
    if (!analysis?.vitals?.[activeVital]?.series) return { vitalData: [], vitalDataIsDownsampled: false }
    const raw = analysis.vitals[activeVital].series.map((pt, i) => ({
      ...pt,
      label: formatTime(pt.timestamp),
      index: i,
    }))
    const isDownsampled = raw.length > CHART_DOWNSAMPLE_THRESHOLD
    const data = isDownsampled
      ? downsampleLTTB(raw, CHART_DOWNSAMPLE_THRESHOLD, 'index', 'value')
      : raw
    return { vitalData: data, vitalDataIsDownsampled: isDownsampled }
  }, [analysis, activeVital])

  const mlScoreData = useMemo(() => {
    if (!analysis?.ml_score_timeline?.length) return []
    return analysis.ml_score_timeline.slice().reverse().map((d, i) => ({
      timestamp: formatTime(d.timestamp),
      score: Number((d.score ?? 0).toFixed(3)),
      level: d.level,
      index: i,
    }))
  }, [analysis])

  const dailyData = useMemo(() => {
    if (!analysis?.vitals?.[activeVital]?.daily_segments) return []
    return analysis.vitals[activeVital].daily_segments.map((s, i) => ({
      ...s,
      label: `J${i + 1}`,
      range: s.max - s.min,
    }))
  }, [analysis, activeVital])

  const forecastData = useMemo(() => {
    if (!analysis?.forecast) return []
    const hist = (analysis.forecast.history || []).map((p, i) => ({
      index: i,
      label: formatTime(p.timestamp),
      type: 'history',
      heart_rate: p.heart_rate,
      spo2: p.spo2,
      temperature: p.temperature,
    }))
    const lastIdx = hist.length
    const preds = (analysis.forecast.predictions || []).map((p, i) => ({
      index: lastIdx + i,
      label: p.timestamp ? formatTime(p.timestamp) : `+${i + 1}`,
      type: 'prediction',
      heart_rate: p.heart_rate,
      spo2: p.spo2,
      temperature: p.temperature,
      heart_rate_upper: p.heart_rate_upper,
      heart_rate_lower: p.heart_rate_lower,
      spo2_upper: p.spo2_upper,
      spo2_lower: p.spo2_lower,
      temperature_upper: p.temperature_upper,
      temperature_lower: p.temperature_lower,
    }))
    return [...hist, ...preds]
  }, [analysis])

  const forecastSplit = analysis?.forecast?.history?.length ?? 0

  const correlations = analysis?.correlations || {}

  const latestValues = useMemo(() => {
    if (!analysis?.vitals) return []
    return Object.entries(VITAL_CONFIG).map(([feat, vc]) => {
      const info = analysis.vitals[feat]
      const series = info?.series || []
      const last = series.length > 0 ? series[series.length - 1] : null
      const value = last?.value ?? last?.[feat]
      const range = info?.physiological_range
      let status = 'ok'
      if (value != null && range && range.length >= 2) {
        const [lo, hi] = range
        if (value < lo || value > hi) status = 'alerte'
        else if (feat === 'spo2' && value < 95) status = 'attention'
        else if (feat === 'heart_rate' && (value < lo + 5 || value > hi - 5)) status = 'attention'
      }
      return { feat, label: vc.label, unit: vc.unit, value, status, color: vc.color, Icon: vc.Icon }
    }).filter((v) => v.value != null)
  }, [analysis])

  const hourlyDistributionByDay = useMemo(() => {
    if (!analysis?.vitals) return { rows: [], maxCount: 0 }
    const seen = new Set()
    const byDayHour = {}
    const dayOrder = []
    const daySet = new Set()
    Object.values(analysis.vitals).forEach((info) => {
      (info?.series || []).forEach((pt) => {
        const ts = pt.timestamp ? new Date(pt.timestamp) : null
        if (ts) {
          const key = `${ts.getTime()}`
          if (!seen.has(key)) {
            seen.add(key)
            const dayKey = ts.toISOString().slice(0, 10)
            const hour = ts.getHours()
            if (!daySet.has(dayKey)) {
              daySet.add(dayKey)
              dayOrder.push(dayKey)
            }
            const k = `${dayKey}|${hour}`
            byDayHour[k] = (byDayHour[k] || 0) + 1
          }
        }
      })
    })
    dayOrder.sort((a, b) => new Date(b) - new Date(a))
    let maxCount = 0
    const rows = dayOrder.map((dayKey) => {
      const row = { day: dayKey, label: formatDate(dayKey), hours: {} }
      for (let h = 0; h < 24; h++) {
        const count = byDayHour[`${dayKey}|${h}`] || 0
        row.hours[h] = count
        if (count > maxCount) maxCount = count
      }
      return row
    })
    return { rows, maxCount }
  }, [analysis])

  const variabilityData = useMemo(() => {
    if (!analysis?.vitals) return []
    const FEATS = [
      { feat: 'heart_rate', label: 'FC', color: '#b91c1c', dataKey: 'fc_std' },
      { feat: 'spo2', label: 'SpO₂', color: '#1d4ed8', dataKey: 'spo2_std' },
      { feat: 'temperature', label: 'Temp', color: '#047857', dataKey: 'temp_std' },
    ]
    const windowMs = variabilityWindow * 60 * 60 * 1000
    const allPoints = []
    for (const { feat } of FEATS) {
      const series = analysis.vitals[feat]?.series || []
      for (const pt of series) {
        const ts = pt.timestamp
        if (!ts) continue
        const val = pt.value ?? pt[feat]
        if (val == null || isNaN(Number(val))) continue
        allPoints.push({ feat, ts: new Date(ts).getTime(), val: Number(val) })
      }
    }
    const uniqueTs = [...new Set(allPoints.map((p) => p.ts))].sort((a, b) => a - b)
    if (uniqueTs.length === 0) return []
    const std = (arr) => {
      if (arr.length < 2) return 0
      const m = arr.reduce((a, b) => a + b, 0) / arr.length
      const v = arr.reduce((s, x) => s + (x - m) ** 2, 0) / (arr.length - 1)
      return Math.sqrt(v)
    }
    const result = []
    const step = uniqueTs.length > 200 ? Math.max(1, Math.floor(uniqueTs.length / 200)) : 1
    for (let i = 0; i < uniqueTs.length; i += step) {
      const t = uniqueTs[i]
      const tStart = t - windowMs
      const row = {
        label: formatTime(new Date(t).toISOString()),
        timestamp: t,
        fc_std: null,
        spo2_std: null,
        temp_std: null,
      }
      for (const { feat, dataKey } of FEATS) {
        const inWindow = allPoints.filter((p) => p.feat === feat && p.ts >= tStart && p.ts <= t)
        const vals = inWindow.map((p) => p.val)
        if (vals.length >= 2) row[dataKey] = Number(std(vals).toFixed(3))
        else if (vals.length === 1) row[dataKey] = 0
      }
      result.push(row)
    }
    return result
  }, [analysis, variabilityWindow])

  const last24hMultiVital = useMemo(() => {
    if (!analysis?.vitals) return []
    const cutoff = Date.now() - 24 * 60 * 60 * 1000
    const points = {}
    ;['heart_rate', 'spo2', 'temperature'].forEach((feat) => {
      const series = analysis.vitals?.[feat]?.series || []
      series.forEach((pt) => {
        const ts = pt.timestamp ? new Date(pt.timestamp).getTime() : 0
        if (ts >= cutoff) {
          const key = Math.floor(ts / (30 * 60 * 1000)) * (30 * 60 * 1000)
          if (!points[key]) points[key] = { label: new Date(key).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' }) }
          points[key][feat] = pt.value ?? pt[feat]
        }
      })
    })
    return Object.entries(points).sort((a, b) => a[0] - b[0]).map(([, v]) => v)
  }, [analysis])

  const vitalInfo = analysis?.vitals?.[activeVital] || {}
  const stats = vitalInfo.statistics || {}
  const trend = vitalInfo.trend || {}
  const cfg = VITAL_CONFIG[activeVital]

  return (
    <DoctorLayout>
      <div className="pml-page">
        {}
        <header className="pml-header">
          <div className="pml-header-left">
            <button className="pml-back-btn" onClick={() => navigate(`/doctor/patient/${patientId}`)}>
              <ArrowLeft size={18} />
            </button>
            <div>
              <h1><BrainCircuit size={26} /> Suivi avancé - {analysis?.patient_display || patientId}</h1>
              <p>Tendances, détection des signes d'alerte et prévisions des constantes vitales</p>
            </div>
          </div>
          <div className="pml-header-actions">
            <div className="pml-period-selector">
              <CalendarDays size={15} />
              {[7, 14, 30, 90, 180, 365].map(d => (
                <button
                  key={d}
                  className={`pml-period-btn ${days === d ? 'pml-period-btn--active' : ''}`}
                  onClick={() => setDays(d)}
                >
                  {d}j
                </button>
              ))}
            </div>
          </div>
        </header>

        {loading && <div className="pml-panel pml-loading">Chargement de l'analyse...</div>}
        {!loading && error && (
          <div className="pml-panel pml-panel--error"><ShieldAlert size={20} /> {error}</div>
        )}

        {!loading && !error && analysis && (
          <>
            <section className="pml-stats-section">
              <div className="pml-stats-header">
                <h2 className="pml-stats-title">Indicateurs clés</h2>
                <p className="pml-stats-desc">Moyennes sur la période et tendances</p>
              </div>
              <div className="pml-stats-row">
                {Object.entries(VITAL_CONFIG).map(([feat, vc]) => {
                  const info = analysis.vitals?.[feat]
                  if (!info || info.status !== 'ok') return null
                  const s = info.statistics || {}
                  const t = info.trend || {}
                  const trendLabel = ({ negligible: 'Stable', mild: 'Légère variation', moderate: 'Variation modérée', strong: 'Variation marquée' })[t.strength] || t.strength
                  const trendIcon = t.label === 'increasing' ? '↗' : t.label === 'decreasing' ? '↘' : '→'
                  return (
                    <StatCard
                      key={feat}
                      label={vc.label}
                      value={s.mean}
                      unit={vc.unit}
                      icon={vc.Icon}
                      color={vc.color}
                      subtitle={`${trendIcon} ${trendLabel} · σ ${s.std}`}
                    />
                  )
                })}
                <StatCard
                  label="Alertes"
                  value={analysis.anomaly_summary?.total ?? 0}
                  unit=""
                  icon={AlertTriangle}
                  color="#b45309"
                  variant="alert"
                  subtitle={`${analysis.anomaly_summary?.by_status?.validated ?? 0} validées · ${analysis.anomaly_summary?.by_status?.pending ?? 0} en attente`}
                />
              </div>
            </section>

            {/* Répartition horaire des mesures (jour × heure) */}
            {hourlyDistributionByDay.rows.length > 0 && (
              <section className="pml-panel">
                <h2><Clock size={18} /> Répartition horaire des mesures (jour × heure)</h2>
                <div className="pml-chart-wrap">
                  <div className="pml-heatmap-wrap">
                    <table className="pml-heatmap">
                      <thead>
                        <tr className="pml-heatmap-hour-row">
                          <th className="pml-heatmap-day-label"></th>
                          {Array.from({ length: 24 }, (_, h) => (
                            <th key={h}>{h}h</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {hourlyDistributionByDay.rows.map((row) => (
                          <tr key={row.day}>
                            <td className="pml-heatmap-day-label">{row.label}</td>
                            {Array.from({ length: 24 }, (_, h) => {
                              const count = row.hours[h] || 0
                              const max = hourlyDistributionByDay.maxCount || 1
                              const intensity = max > 0 ? count / max : 0
                              const opacity = 0.12 + intensity * 0.88
                              const bg = `rgba(29, 78, 216, ${opacity})`
                              return (
                                <td key={h} className="pml-heatmap-cell" style={{ background: bg }} title={`${row.label} ${h}h–${h + 1}h : ${count} mesure(s)`} />
                              )
                            })}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <div className="pml-heatmap-legend">
                    <span>Intensité :</span>
                    <div className="pml-heatmap-legend-scale">
                      {[0, 0.25, 0.5, 0.75, 1].map((v) => (
                        <span key={v} style={{ background: `rgba(29, 78, 216, ${0.15 + v * 0.85})` }} title={`${Math.round(v * (hourlyDistributionByDay.maxCount || 0))} mesures`} />
                      ))}
                    </div>
                    <span>0 → {hourlyDistributionByDay.maxCount || 0} mesures</span>
                  </div>
                </div>
              </section>
            )}

            {/* Score de variabilité */}
            {variabilityData.length > 0 && (
              <section className="pml-panel pml-variability-section">
                <div className="pml-variability-header">
                  <div>
                    <h2><Activity size={18} /> Score de variabilité</h2>
                    <p className="pml-panel-sub">Écart-type glissant ({variabilityWindow}h) - FC, SpO₂, Temp</p>
                  </div>
                  <div className="pml-variability-toggles">
                    {[6, 12, 24].map((h) => (
                      <button
                        key={h}
                        type="button"
                        className={`pml-period-btn ${variabilityWindow === h ? 'pml-period-btn--active' : ''}`}
                        onClick={() => setVariabilityWindow(h)}
                      >
                        {h}h
                      </button>
                    ))}
                  </div>
                </div>
                <div className="pml-chart-wrap">
                  <ResponsiveContainer width="100%" height={220}>
                    <AreaChart data={variabilityData} margin={{ top: 10, right: 20, left: 0, bottom: 5 }}>
                      <defs>
                        <linearGradient id="pmlVarFc" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#b91c1c" stopOpacity={0.25} />
                          <stop offset="95%" stopColor="#b91c1c" stopOpacity={0} />
                        </linearGradient>
                        <linearGradient id="pmlVarSpo2" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#1d4ed8" stopOpacity={0.25} />
                          <stop offset="95%" stopColor="#1d4ed8" stopOpacity={0} />
                        </linearGradient>
                        <linearGradient id="pmlVarTemp" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#047857" stopOpacity={0.25} />
                          <stop offset="95%" stopColor="#047857" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                      <XAxis dataKey="label" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
                      <YAxis tick={{ fontSize: 11 }} domain={['auto', 'auto']} />
                      <Tooltip
                        formatter={(val, name) => [val != null ? Number(val).toFixed(3) : '-', name]}
                        contentStyle={{ borderRadius: '8px', fontSize: '0.8rem' }}
                      />
                      <Legend />
                      <Area type="monotone" dataKey="fc_std" name="FC (écart-type)" stroke="#b91c1c" fill="url(#pmlVarFc)" strokeWidth={1.5} dot={false} connectNulls />
                      <Area type="monotone" dataKey="spo2_std" name="SpO₂ (écart-type)" stroke="#1d4ed8" fill="url(#pmlVarSpo2)" strokeWidth={1.5} dot={false} connectNulls />
                      <Area type="monotone" dataKey="temp_std" name="Temp (écart-type)" stroke="#047857" fill="url(#pmlVarTemp)" strokeWidth={1.5} dot={false} connectNulls />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </section>
            )}

            <div className="pml-vital-tabs">
              {Object.entries(VITAL_CONFIG).map(([feat, vc]) => (
                <button
                  key={feat}
                  className={`pml-vital-tab ${activeVital === feat ? 'pml-vital-tab--active' : ''}`}
                  style={activeVital === feat ? { borderColor: vc.color, color: vc.color } : {}}
                  onClick={() => setActiveVital(feat)}
                >
                  <vc.Icon size={16} /> {vc.label}
                </button>
              ))}
            </div>

            {}
            {vitalInfo.status === 'ok' && (
              <section className="pml-panel pml-trend-panel">
                <div className="pml-panel-header">
                  <h2><Activity size={18} /> Tendance - {cfg.label}</h2>
                  <div className="pml-panel-controls">
                    <label className="pml-toggle">
                      <input type="checkbox" checked={showMA} onChange={() => setShowMA(!showMA)} />
                      <span>Courbes de tendance</span>
                    </label>
                    <label className="pml-toggle">
                      <input type="checkbox" checked={showAnomalies} onChange={() => setShowAnomalies(!showAnomalies)} />
                      <span>Valeurs anormales</span>
                    </label>
                  </div>
                </div>

                <div className="pml-chart-wrap">
                  {vitalDataIsDownsampled && (
                    <p className="pml-downsample-hint">
                      <Info size={12} /> Affichage de {CHART_DOWNSAMPLE_THRESHOLD} points pour une meilleure lisibilité ({analysis?.vitals?.[activeVital]?.series?.length ?? 0} mesures au total)
                    </p>
                  )}
                  <ResponsiveContainer width="100%" height={320}>
                    <ComposedChart data={vitalData} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                      <defs>
                        <linearGradient id={`grad_${activeVital}`} x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor={cfg.color} stopOpacity={0.15} />
                          <stop offset="95%" stopColor={cfg.color} stopOpacity={0.02} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                      <XAxis dataKey="label" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
                      <YAxis domain={['auto', 'auto']} tick={{ fontSize: 11 }} />
                      <Tooltip content={<CustomTooltip />} />

                      {vitalInfo.physiological_range && (
                        <ReferenceArea
                          y1={vitalInfo.physiological_range[0]}
                          y2={vitalInfo.physiological_range[1]}
                          fill={cfg.color}
                          fillOpacity={0.04}
                          label={{ value: 'Valeurs normales', fontSize: 10, fill: '#94a3b8' }}
                        />
                      )}
                      {vitalInfo.physiological_range && (
                        <ReferenceLine y={vitalInfo.physiological_range[0]} stroke="#94a3b8" strokeDasharray="4 4" />
                      )}
                      {vitalInfo.physiological_range && (
                        <ReferenceLine y={vitalInfo.physiological_range[1]} stroke="#94a3b8" strokeDasharray="4 4" />
                      )}

                      <Area
                        type="monotone"
                        dataKey="value"
                        fill={`url(#grad_${activeVital})`}
                        stroke="none"
                        dot={false}
                      />
                      <Line
                        type="monotone"
                        dataKey="value"
                        name={`${cfg.label} (mesures)`}
                        stroke={cfg.color}
                        strokeWidth={1.5}
                        dot={vitalDataIsDownsampled ? false : (showAnomalies ? (props) => <AnomalyDot {...props} color={cfg.color} /> : { r: 2, fill: cfg.color })}
                        connectNulls
                      />
                      <Line
                        type="monotone"
                        dataKey="ema"
                        name="Tendance lissée"
                        stroke={cfg.color}
                        strokeWidth={2.5}
                        strokeOpacity={0.7}
                        dot={false}
                        connectNulls
                      />

                      {showMA && (
                        <>
                          <Line type="monotone" dataKey="ma_6" name="Moyenne 6h" stroke="#a855f7" strokeWidth={1} strokeDasharray="4 2" dot={false} connectNulls />
                          <Line type="monotone" dataKey="ma_12" name="Moyenne 12h" stroke="#06b6d4" strokeWidth={1} strokeDasharray="6 3" dot={false} connectNulls />
                          <Line type="monotone" dataKey="ma_24" name="Moyenne 24h" stroke="#b45309" strokeWidth={1} strokeDasharray="8 4" dot={false} connectNulls />
                        </>
                      )}

                      <Legend />
                      <Brush dataKey="label" height={25} stroke={cfg.color} />
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>

                {}
                <div className="pml-trend-summary">
                  <div className="pml-trend-direction">
                    {trend.label === 'increasing' && <TrendingUp size={20} color="#b45309" />}
                    {trend.label === 'decreasing' && <TrendingDown size={20} color="#1d4ed8" />}
                    {trend.label === 'stable' && <Activity size={20} color="#047857" />}
                    <span>
                      {trend.label === 'stable' ? 'Stable' : trend.label === 'increasing' ? 'En hausse' : 'En baisse'}
                      {' '}({({ negligible: 'négligeable', mild: 'légère', moderate: 'modérée', strong: 'marquée' })[trend.strength] || trend.strength})
                      {trend.significant && <span className="pml-sig-badge">Significatif</span>}
                    </span>
                  </div>
                  <div className="pml-trend-stats">
                    <span>Moyenne : <strong>{stats.mean}</strong></span>
                    <span>Médiane : <strong>{stats.median}</strong></span>
                    <span>Écart-type : <strong>{stats.std}</strong></span>
                    <span>Dispersion : <strong>{stats.iqr}</strong></span>
                    <span>Variabilité : <strong>{stats.cv}%</strong></span>
                    <span>Min : <strong>{stats.min}</strong></span>
                    <span>Max : <strong>{stats.max}</strong></span>
                  </div>
                </div>

                {}
                {vitalInfo.clinical_alerts?.length > 0 && (
                  <div className="pml-clinical-alerts">
                    {vitalInfo.clinical_alerts.map((a, i) => (
                      <div key={i} className={`pml-alert pml-alert--${a.severity}`}>
                        <AlertTriangle size={15} />
                        <span>{a.message}</span>
                        <span className="pml-alert-eta">~{a.estimated_breach_hours}h</span>
                      </div>
                    ))}
                  </div>
                )}
              </section>
            )}

            {}
            {mlScoreData.length > 0 && (
              <section className="pml-panel">
                <h2><ShieldAlert size={18} /> Évolution de l'indice de risque</h2>
                <div className="pml-chart-wrap">
                  <ResponsiveContainer width="100%" height={240}>
                    <AreaChart data={mlScoreData} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                      <defs>
                        <linearGradient id="mlScoreGrad" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#1d4ed8" stopOpacity={0.25} />
                          <stop offset="95%" stopColor="#1d4ed8" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                      <XAxis dataKey="timestamp" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
                      <YAxis domain={[0, 1]} tick={{ fontSize: 11 }} />
                      <Tooltip content={<CustomTooltip />} />
                      <ReferenceArea y1={0} y2={0.45} fill="#047857" fillOpacity={0.06} />
                      <ReferenceArea y1={0.45} y2={0.70} fill="#b45309" fillOpacity={0.06} />
                      <ReferenceArea y1={0.70} y2={1} fill="#b91c1c" fillOpacity={0.06} />
                      <ReferenceLine y={0.45} stroke="#b45309" strokeDasharray="4 4" label={{ value: 'Surveillance', fontSize: 10, fill: '#b45309' }} />
                      <ReferenceLine y={0.70} stroke="#b91c1c" strokeDasharray="4 4" label={{ value: 'Critique', fontSize: 10, fill: '#b91c1c' }} />
                      <Area
                        type="monotone"
                        dataKey="score"
                        name="Indice de risque"
                        stroke="#1d4ed8"
                        fill="url(#mlScoreGrad)"
                        strokeWidth={2}
                        dot={(props) => {
                          const { cx, cy, payload } = props
                          const c = LEVEL_COLORS[payload?.level] || '#1d4ed8'
                          const r = payload?.level === 'critical' ? 5 : payload?.level === 'warning' ? 4 : 2
                          return <circle cx={cx} cy={cy} r={r} fill={c} stroke="#fff" strokeWidth={1} />
                        }}
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </section>
            )}

            {/* Anomaly points detail */}
            {vitalInfo.anomalous_points?.length > 0 && (
              <section className="pml-panel">
                <div className="pml-panel-header">
                  <h2><AlertTriangle size={18} /> Valeurs anormales détectées - {cfg.label}</h2>
                  <span className="pml-badge pml-badge--warning">{vitalInfo.n_anomalies} détectées</span>
                </div>
                <div className="pml-anomaly-list">
                  {vitalInfo.anomalous_points.slice(0, 20).map((a, i) => (
                    <div key={i} className={`pml-anomaly-item pml-anomaly-item--${a.severity}`}>
                      <span className="pml-anomaly-value">{a.value} {cfg.unit}</span>
                      <span className="pml-anomaly-time">t+{a.t_hours}h</span>
                      <div className="pml-anomaly-reasons">
                        {a.reasons.map((r, j) => (
                          <span key={j} className="pml-anomaly-reason">{r.replace(/_/g, ' ')}</span>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {/* Daily pattern */}
            {dailyData.length > 1 && (
              <section className="pml-panel">
                <h2><BarChart3 size={18} /> Profil journalier - {cfg.label}</h2>
                <div className="pml-chart-wrap">
                  <ResponsiveContainer width="100%" height={220}>
                    <BarChart data={dailyData} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                      <XAxis dataKey="label" tick={{ fontSize: 11 }} />
                      <YAxis tick={{ fontSize: 11 }} />
                      <Tooltip content={<CustomTooltip />} />
                      <Bar dataKey="mean" name="Moyenne" fill={cfg.color} radius={[4, 4, 0, 0]} fillOpacity={0.8} />
                      <Bar dataKey="range" name="Amplitude" fill={cfg.color} radius={[4, 4, 0, 0]} fillOpacity={0.3} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </section>
            )}

            {/* Forecast section */}
            {analysis.forecast && !analysis.forecast.error && forecastData.length > 0 && (
              <section className="pml-panel pml-forecast-section">
                <h2><LineChartIcon size={18} /> Prévisions</h2>

                {analysis.forecast.summary && (
                  <div className="pml-forecast-summary">
                    <div className="pml-forecast-summary-badges">
                      <span className="pml-badge" style={{
                        background: analysis.forecast.confidence_score >= 60 ? '#f0fdf4' : '#fffbeb',
                        color: analysis.forecast.confidence_score >= 60 ? '#047857' : '#b45309',
                      }}>
                        <Gauge size={13} /> {analysis.forecast.confidence_score}/100
                      </span>
                      {(() => {
                        const riskCfg = RISK_CONFIG[analysis.forecast.summary.risk_level] || RISK_CONFIG.minimal
                        return (
                          <span className="pml-badge" style={{ background: riskCfg.bg, color: riskCfg.color }}>
                            {riskCfg.label}
                          </span>
                        )
                      })()}
                    </div>
                    <div className="pml-forecast-text">
                      <Sparkles size={15} />
                      <div>
                        <p>{analysis.forecast.summary.text}</p>
                        <p className="pml-forecast-action"><ArrowRight size={13} /> {analysis.forecast.summary.recommended_action}</p>
                      </div>
                    </div>
                  </div>
                )}

                {['heart_rate', 'spo2', 'temperature'].map(feat => {
                  const fInfo = analysis.forecast?.vitals?.[feat]
                  if (!fInfo || fInfo.status !== 'ok') return null
                  const vc = VITAL_CONFIG[feat]
                  const ranges = fInfo.physiological_range
                  const hasData = forecastData.some(d => d[feat] != null)
                  if (!hasData) return null

                  return (
                    <div key={feat} className="pml-chart-wrap pml-forecast-chart">
                      <div className="pml-chart-header">
                        <h3><vc.Icon size={16} /> {vc.label} ({vc.unit})</h3>
                        <span className="pml-badge" style={{
                          background: fInfo.confidence_score >= 60 ? '#f0fdf4' : '#fffbeb',
                          color: fInfo.confidence_score >= 60 ? '#047857' : '#b45309',
                        }}>
                          {fInfo.confidence_score}/100
                        </span>
                      </div>
                      <ResponsiveContainer width="100%" height={220}>
                        <LineChart data={forecastData} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                          <XAxis dataKey="label" tick={{ fontSize: 10 }} />
                          <YAxis tick={{ fontSize: 11 }} domain={['auto', 'auto']} />
                          <Tooltip content={<CustomTooltip />} />
                          {ranges && <ReferenceLine y={ranges[0]} stroke="#94a3b8" strokeDasharray="4 4" label={{ value: 'Seuil bas', fontSize: 10, fill: '#94a3b8' }} />}
                          {ranges && <ReferenceLine y={ranges[1]} stroke="#94a3b8" strokeDasharray="4 4" label={{ value: 'Seuil haut', fontSize: 10, fill: '#94a3b8' }} />}
                          <ReferenceLine
                            x={forecastData[forecastSplit - 1]?.label}
                            stroke="#1d4ed8"
                            strokeDasharray="6 3"
                            label={{ value: 'Prévision →', fontSize: 10, fill: '#1d4ed8' }}
                          />
                          <Area
                            dataKey={`${feat}_upper`}
                            stroke="none"
                            fill={vc.color}
                            fillOpacity={0.1}
                            connectNulls={false}
                            dot={false}
                            activeDot={false}
                            legendType="none"
                            tooltipType="none"
                          />
                          <Area
                            dataKey={`${feat}_lower`}
                            stroke="none"
                            fill={vc.color}
                            fillOpacity={0.1}
                            connectNulls={false}
                            dot={false}
                            activeDot={false}
                            legendType="none"
                            tooltipType="none"
                          />
                          <Line
                            type="monotone"
                            dataKey={feat}
                            name={vc.label}
                            stroke={vc.color}
                            strokeWidth={2}
                            dot={(props) => {
                              const { cx, cy, index } = props
                              if (index >= forecastSplit) {
                                return <circle key={index} cx={cx} cy={cy} r={4} fill="#fff" stroke={vc.color} strokeWidth={2} strokeDasharray="3 2" />
                              }
                              return <circle key={index} cx={cx} cy={cy} r={3} fill={vc.color} />
                            }}
                            connectNulls
                          />
                        </LineChart>
                      </ResponsiveContainer>
                    </div>
                  )
                })}
              </section>
            )}

            {/* Correlations matrix */}
            {Object.keys(correlations).length > 0 && (
              <section className="pml-panel">
                <h2><Layers size={18} /> Corrélations entre signes vitaux</h2>
                <div className="pml-corr-matrix">
                  <table className="pml-corr-table">
                    <thead>
                      <tr>
                        <th></th>
                        {Object.keys(correlations).map(f => (
                          <th key={f}>{VITAL_CONFIG[f]?.label || f}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(correlations).map(([f1, row]) => (
                        <tr key={f1}>
                          <td className="pml-corr-label">{VITAL_CONFIG[f1]?.label || f1}</td>
                          {Object.entries(row).map(([f2, val]) => {
                            const abs = Math.abs(val)
                            const bg = f1 === f2 ? '#e2e8f0'
                              : abs > 0.7 ? '#fecaca'
                              : abs > 0.4 ? '#fef3c7'
                              : abs > 0.2 ? '#e0f2fe'
                              : '#f8fafc'
                            return (
                              <td key={f2} style={{ background: bg, fontWeight: abs > 0.5 ? 600 : 400 }}>
                                {val.toFixed(2)}
                              </td>
                            )
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}

            {/* Anomaly summary */}
            {analysis.anomaly_summary?.total > 0 && (
              <section className="pml-panel">
                <h2><ShieldAlert size={18} /> Historique des alertes</h2>
                <div className="pml-anomaly-summary-grid">
                  <div className="pml-anomaly-count-card" style={{ borderColor: '#b45309' }}>
                    <span className="pml-count">{analysis.anomaly_summary.total}</span>
                    <span>Total</span>
                  </div>
                  <div className="pml-anomaly-count-card" style={{ borderColor: '#1d4ed8' }}>
                    <span className="pml-count">{analysis.anomaly_summary.by_status?.pending ?? 0}</span>
                    <span>En attente</span>
                  </div>
                  <div className="pml-anomaly-count-card" style={{ borderColor: '#047857' }}>
                    <span className="pml-count">{analysis.anomaly_summary.by_status?.validated ?? 0}</span>
                    <span>Validées</span>
                  </div>
                  <div className="pml-anomaly-count-card" style={{ borderColor: '#94a3b8' }}>
                    <span className="pml-count">{analysis.anomaly_summary.by_status?.rejected ?? 0}</span>
                    <span>Rejetées</span>
                  </div>
                </div>

                {analysis.anomaly_summary.recent?.length > 0 && (
                  <div className="pml-anomaly-recent">
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                      <h3 style={{ margin: 0 }}>Alertes récentes</h3>
                      <button
                        onClick={() => navigate('/doctor/alertes')}
                        style={{
                          display: 'flex', alignItems: 'center', gap: 4,
                          background: 'none', border: '1px solid #cbd5e1', borderRadius: 6,
                          padding: '4px 10px', cursor: 'pointer', fontSize: 12, color: '#1d4ed8',
                        }}
                      >
                        <ExternalLink size={13} /> Voir la file d'alertes
                      </button>
                    </div>
                    <div className="pml-anomaly-table-wrap">
                      <table className="pml-table">
                        <thead>
                          <tr>
                            <th>Date</th>
                            <th>Niveau</th>
                            <th>Statut</th>
                            <th>Paramètres impliqués</th>
                            <th>Actions</th>
                          </tr>
                        </thead>
                        <tbody>
                          {analysis.anomaly_summary.recent.map((a, i) => {
                            const isPending = (a.status_raw || a.status || '').toUpperCase() === 'PENDING'
                            const isPatching = patchingAlerts[a.alert_id]
                            return (
                              <tr key={i}>
                                <td>{formatTime(a.timestamp)}</td>
                                <td>
                                  <span className="pml-level-dot" style={{ background: LEVEL_COLORS[a.level] || '#1d4ed8' }} />
                                  {a.level}
                                </td>
                                <td>
                                  <span style={{
                                    padding: '2px 8px', borderRadius: 12, fontSize: 11, fontWeight: 600,
                                    background: a.status === 'pending' ? '#fef3c7' : a.status === 'validated' ? '#dcfce7' : '#fee2e2',
                                    color: a.status === 'pending' ? '#92400e' : a.status === 'validated' ? '#166534' : '#991b1b',
                                  }}>
                                    {a.status === 'pending' ? 'En attente' : a.status === 'validated' ? 'Validée' : 'Rejetée'}
                                  </span>
                                </td>
                                <td>
                                  {(a.contributing_variables || []).slice(0, 3).map((cv, j) => (
                                    <span key={j} className="pml-contrib-tag">
                                      {cv.variable} ({(cv.contribution_weight * 100).toFixed(0)}%)
                                    </span>
                                  ))}
                                  {a.value != null && a.threshold != null && (
                                    <span style={{ fontSize: 11, color: '#64748b', marginLeft: 6 }}>
                                      {a.value} {a.operator} {a.threshold}
                                    </span>
                                  )}
                                </td>
                                <td>
                                  {a.alert_id && isPending ? (
                                    <div style={{ display: 'flex', gap: 6 }}>
                                      <button
                                        disabled={isPatching}
                                        onClick={() => handleAlertAction(a.alert_id, 'validate')}
                                        title="Valider l'alerte"
                                        style={{
                                          display: 'flex', alignItems: 'center', gap: 3,
                                          background: '#dcfce7', border: '1px solid #86efac',
                                          borderRadius: 6, padding: '3px 8px', cursor: 'pointer',
                                          fontSize: 11, color: '#166534', fontWeight: 600,
                                          opacity: isPatching ? 0.5 : 1,
                                        }}
                                      >
                                        <CheckCircle size={13} /> Valider
                                      </button>
                                      <button
                                        disabled={isPatching}
                                        onClick={() => handleAlertAction(a.alert_id, 'reject')}
                                        title="Rejeter l'alerte"
                                        style={{
                                          display: 'flex', alignItems: 'center', gap: 3,
                                          background: '#fee2e2', border: '1px solid #fca5a5',
                                          borderRadius: 6, padding: '3px 8px', cursor: 'pointer',
                                          fontSize: 11, color: '#991b1b', fontWeight: 600,
                                          opacity: isPatching ? 0.5 : 1,
                                        }}
                                      >
                                        <XCircle size={13} /> Rejeter
                                      </button>
                                    </div>
                                  ) : a.alert_id && !isPending ? (
                                    <span style={{ fontSize: 11, color: '#94a3b8' }}>-</span>
                                  ) : (
                                    <span style={{ fontSize: 11, color: '#94a3b8' }}>ML</span>
                                  )}
                                </td>
                              </tr>
                            )
                          })}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </section>
            )}

            {/* Data quality info */}
            <section className="pml-panel pml-data-info">
              <Info size={15} />
              <span>
                {analysis.n_total_measurements ?? analysis.n_measurements} mesures pour ce patient analysées - {formatTime(analysis.generated_at)}
              </span>
            </section>
          </>
        )}
      </div>
    </DoctorLayout>
  )
}
