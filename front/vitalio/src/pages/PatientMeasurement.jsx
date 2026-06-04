import React, { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth0 } from '@auth0/auth0-react'
import { ArrowLeft, CheckCircle2, LoaderCircle } from 'lucide-react'
import { submitPatientMeasurement } from '../services/api'

const STEPS = [
  'Préparez le capteur',
  'Lancez la mesure',
  'Résultat',
]

const createSimulatedMeasurement = (simulateCritical = false) => {
  if (simulateCritical) {
    // Alerte critique FC : tachycardie sévère (165 bpm) ou bradycardie (35 bpm)
    return {
      source: 'simulation',
      measured_at: new Date().toISOString(),
      heart_rate: 165,
      spo2: 96,
      temperature: 36.5,
      signal_quality: 85,
    }
  }
  return {
    source: 'simulation',
    measured_at: new Date().toISOString(),
    heart_rate: 64 + Math.round(Math.random() * 30),
    spo2: 94 + Math.round(Math.random() * 5),
    temperature: Number((36 + Math.random() * 1.8).toFixed(1)),
    signal_quality: 75 + Math.round(Math.random() * 20),
  }
}

export default function PatientMeasurement() {
  const navigate = useNavigate()
  const { getAccessTokenSilently } = useAuth0()
  const [step, setStep] = useState(0)
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState(null)
  const [storedDeviceId, setStoredDeviceId] = useState(null)
  const [error, setError] = useState('')
  const [simulateCritical, setSimulateCritical] = useState(false)

  const progress = useMemo(() => ((step + 1) / STEPS.length) * 100, [step])

  const nextStep = () => setStep((prev) => Math.min(prev + 1, STEPS.length - 1))

  const runMeasurement = async () => {
    try {
      setSubmitting(true)
      setError('')
      const token = await getAccessTokenSilently()
      const payload = createSimulatedMeasurement(simulateCritical)
      const response = await submitPatientMeasurement(token, payload)
      setResult(response.measurement || payload)
      setStoredDeviceId(response.device_id ? String(response.device_id) : null)
      nextStep()
    } catch (submitError) {
        setError(submitError.message || "L'envoi a échoué.")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="patient-container patient-theme">
      <button onClick={() => navigate('/patient')} className="back-button">
        <ArrowLeft size={24} />
      </button>

      <main className="patient-measurement">
        <header className="patient-header">
          <h1>Prise de mesure</h1>
          <p>Suivez les étapes pour réaliser et envoyer votre mesure.</p>
        </header>

        <section className="panel">
          <div className="stepper">
            <div className="stepper-track">
              <div className="stepper-progress" style={{ width: `${progress}%` }} />
            </div>
            <div className="stepper-steps">
              {STEPS.map((title, index) => (
                <div key={title} className={`step ${index <= step ? 'active' : ''}`}>
                  <span>{index + 1}</span>
                  <small>{title}</small>
                </div>
              ))}
            </div>
          </div>
        </section>

        {step === 0 && (
          <section className="panel">
            <h2>Préparez le capteur</h2>
            <p>Placez le capteur correctement et restez assis pendant quelques secondes.</p>
            <button className="primary-button" onClick={nextStep}>Capteur prêt</button>
          </section>
        )}

        {step === 1 && (
          <section className="panel">
            <h2>Lancez la mesure</h2>
            <p>Appuyez pour simuler (ou transmettre) une mesure vers la plateforme.</p>
            <label className="simulate-critical-toggle" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '1rem' }}>
              <input
                type="checkbox"
                checked={simulateCritical}
                onChange={(e) => setSimulateCritical(e.target.checked)}
              />
              <span>Simuler une alerte critique (FC 165 bpm)</span>
            </label>
            <button className="primary-button" onClick={runMeasurement} disabled={submitting}>
              {submitting ? (
                <>
                  <LoaderCircle size={18} className="spin" /> Envoi en cours...
                </>
              ) : (
                'Lancer la mesure'
              )}
            </button>
            {error && <p className="error-text">{error}</p>}
          </section>
        )}

        {step === 2 && (
          <section className="panel panel-success">
            <h2>
              <CheckCircle2 size={20} /> Résultat
            </h2>
            <p>Mesure envoyée avec succès.</p>
            {storedDeviceId && (
              <p style={{ fontSize: '0.95rem', color: '#475569', marginBottom: '0.75rem' }}>
                Enregistrée pour votre boîtier&nbsp;:{' '}
                <strong style={{ letterSpacing: '0.03em' }}>{storedDeviceId}</strong>
              </p>
            )}
            {result && (
              <div className="result-grid">
                <span>SpO2: {result.spo2}%</span>
                <span>FC: {result.heart_rate} bpm</span>
                <span>Température : {result.temperature} °C</span>
              </div>
            )}
            <div className="actions-row">
              <button className="secondary-button" onClick={() => navigate('/patient')}>
                Retour à l'accueil
              </button>
              <button
                className="primary-button"
                onClick={() => {
                  setStep(0)
                  setResult(null)
                  setStoredDeviceId(null)
                  setError('')
                  setSimulateCritical(false)
                }}
              >
                Nouvelle mesure
              </button>
            </div>
          </section>
        )}
      </main>
    </div>
  )
}
