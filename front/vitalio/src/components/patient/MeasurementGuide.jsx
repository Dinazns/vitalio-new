import React, { useEffect, useRef } from 'react'
import { Play, Loader2 } from 'lucide-react'
import { MEASUREMENT_DURATION_SEC } from '../../utils/vitalStatus'

export default function MeasurementGuide({
  measuring,
  secondsLeft,
  onStart,
  disabled,
}) {
  const progressRef = useRef(null)
  const progressPct = measuring
    ? Math.round(((MEASUREMENT_DURATION_SEC - secondsLeft) / MEASUREMENT_DURATION_SEC) * 100)
    : 0

  useEffect(() => {
    if (progressRef.current) {
      progressRef.current.style.width = `${progressPct}%`
    }
  }, [progressPct])

  return (
    <section className="panel panel-measurement" aria-labelledby="measurement-section-title">
      <div className="panel-title">
        <h2 id="measurement-section-title">Prise de mesure</h2>
      </div>

      {!measuring ? (
        <>
          <p className="panel-measurement-desc">
            Appuyez sur Démarrer, puis posez votre doigt sur le capteur du boîtier.
          </p>
          <button
            type="button"
            className="primary-button panel-measurement-btn"
            onClick={onStart}
            disabled={disabled}
            aria-label="Démarrer une prise de mesure"
          >
            <Play size={20} strokeWidth={2.5} aria-hidden />
            Démarrer
          </button>
          <p className="panel-measurement-hint">
            Posez votre doigt sur le capteur et ne bougez pas pendant 25 secondes.
          </p>
        </>
      ) : (
        <div className="panel-measurement-progress" role="timer" aria-live="polite">
          <div className="panel-measurement-progress__header">
            <Loader2 size={22} className="spin" aria-hidden />
            <strong>Mesure en cours…</strong>
          </div>
          <p className="panel-measurement-countdown" aria-label={`${secondsLeft} secondes restantes`}>
            {secondsLeft}
            <span>s</span>
          </p>
          <div className="panel-measurement-progress__track" aria-hidden>
            <div ref={progressRef} className="panel-measurement-progress__bar" />
          </div>
          <p className="panel-measurement-hint panel-measurement-hint--active">
            Gardez le doigt immobile sur le capteur. Vos résultats apparaîtront automatiquement.
          </p>
        </div>
      )}
    </section>
  )
}
