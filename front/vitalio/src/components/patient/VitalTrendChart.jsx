import React, { useMemo, useState } from 'react'
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceArea,
} from 'recharts'
import ChartDisclaimer from '../ChartDisclaimer'
import {
  VITAL_TREND_TABS,
  getChartNormalRange,
  getPointColor,
  getVitalDisplayValue,
} from '../../utils/vitalStatus'

function formatChartDate(isoValue) {
  if (!isoValue) return ''
  return new Date(isoValue).toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit' })
}

function ChartTooltip({ active, payload, vitalKey }) {
  if (!active || !payload?.length) return null
  const row = payload[0]?.payload
  if (!row) return null
  return (
    <div className="vital-trend-tooltip">
      <span className="vital-trend-tooltip__date">{formatChartDate(row.timestamp)}</span>
      <strong>{getVitalDisplayValue(vitalKey, row.value)}</strong>
    </div>
  )
}

export default function VitalTrendChart({ measurements, showDisclaimer = false }) {
  const [activeTab, setActiveTab] = useState('spo2')

  const chartDataByVital = useMemo(() => {
    const sevenDaysAgo = Date.now() - 7 * 24 * 60 * 60 * 1000
    const recent = measurements
      .filter((m) => {
        const ts = new Date(m.timestamp).getTime()
        return Number.isFinite(ts) && ts >= sevenDaysAgo
      })
      .slice()
      .reverse()

    const build = (key) => recent
      .filter((m) => m[key] != null && !Number.isNaN(Number(m[key])))
      .map((m) => ({
        timestamp: m.timestamp,
        value: Number(m[key]),
        fill: getPointColor(key, m[key]),
      }))

    return {
      spo2: build('spo2'),
      heart_rate: build('heart_rate'),
      temperature: build('temperature'),
    }
  }, [measurements])

  const points = chartDataByVital[activeTab] || []
  const normalRange = getChartNormalRange(activeTab)
  const activeLabel = VITAL_TREND_TABS.find((t) => t.key === activeTab)?.label ?? ''

  return (
    <div className="vital-trend-chart">
      <div className="vital-trend-tabs" role="tablist" aria-label="Constantes vitales">
        {VITAL_TREND_TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            role="tab"
            id={`vital-tab-${tab.key}`}
            aria-selected={activeTab === tab.key}
            aria-controls={`vital-panel-${tab.key}`}
            className={`vital-trend-tab ${activeTab === tab.key ? 'vital-trend-tab--active' : ''}`}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div
        id={`vital-panel-${activeTab}`}
        role="tabpanel"
        aria-labelledby={`vital-tab-${activeTab}`}
        className="vital-trend-panel"
      >
        {!points.length ? (
          <div className="empty-chart">Pas assez de mesures sur les 7 derniers jours.</div>
        ) : (
          <>
            {showDisclaimer && <ChartDisclaimer />}
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={points} margin={{ top: 12, right: 12, left: 0, bottom: 4 }}>
                <XAxis
                  dataKey="timestamp"
                  tickFormatter={formatChartDate}
                  tick={{ fontSize: 12, fill: '#64748b' }}
                  axisLine={false}
                  tickLine={false}
                  minTickGap={24}
                />
                <YAxis
                  domain={['auto', 'auto']}
                  tick={{ fontSize: 12, fill: '#64748b' }}
                  axisLine={false}
                  tickLine={false}
                  width={42}
                />
                {normalRange?.min != null && normalRange?.max != null && (
                  <ReferenceArea
                    y1={normalRange.min}
                    y2={normalRange.max}
                    fill="#10b981"
                    fillOpacity={0.12}
                    strokeOpacity={0}
                    aria-hidden
                  />
                )}
                <Tooltip content={<ChartTooltip vitalKey={activeTab} />} />
                <Line
                  type="monotone"
                  dataKey="value"
                  stroke="#2563eb"
                  strokeWidth={2.5}
                  dot={(props) => {
                    const { cx, cy, payload, index } = props
                    return (
                      <circle
                        key={`dot-${index}`}
                        cx={cx}
                        cy={cy}
                        r={5}
                        fill={payload.fill || '#2563eb'}
                        stroke="#fff"
                        strokeWidth={2}
                      />
                    )
                  }}
                  activeDot={{ r: 7, strokeWidth: 2 }}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
            <p className="vital-trend-legend">
              <span className="vital-trend-legend__band" aria-hidden /> Zone verte = plage normale
              {' · '}
              {points.length} mesure(s) - {activeLabel}
            </p>
          </>
        )}
      </div>
    </div>
  )
}
