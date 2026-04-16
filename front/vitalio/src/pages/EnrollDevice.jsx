import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth0 } from '@auth0/auth0-react'
import { CheckCircle2, Cpu } from 'lucide-react'
import { enrollPatientDevice, getPatientDevice } from '../services/api'
import PatientLayout from '../components/PatientLayout'

export default function EnrollDevice() {
  const navigate = useNavigate()
  const { getAccessTokenSilently } = useAuth0()
  const [code, setCode] = useState('')
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(false)
  const [associatedDeviceId, setAssociatedDeviceId] = useState(null)
  const [deviceInfoLoading, setDeviceInfoLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const token = await getAccessTokenSilently()
        const data = await getPatientDevice(token)
        if (!cancelled && data?.device_id) {
          setAssociatedDeviceId(String(data.device_id))
        }
      } catch {
        /* pas bloquant */
      } finally {
        if (!cancelled) setDeviceInfoLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [getAccessTokenSilently])

  const handleEnroll = async () => {
    if (code.length !== 6) return
    setLoading(true)
    setStatus(null)
    try {
      const token = await getAccessTokenSilently()
      const res = await enrollPatientDevice(token, code)
      if (res?.device_id) setAssociatedDeviceId(String(res.device_id))
      setStatus('success')
    } catch (e) {
      setStatus(e.message || 'Erreur')
    } finally {
      setLoading(false)
    }
  }

  const onCodeChange = (value) => {
    const digits = value.replace(/\D/g, '').slice(0, 6)
    setCode(digits)
    if (status && status !== 'success') setStatus(null)
  }

  if (status === 'success') {
    return (
      <PatientLayout>
        <div className="patient-container patient-theme">
          <main className="patient-dashboard">
            <section className="panel panel-success" style={{ textAlign: 'center', maxWidth: 480, margin: '0 auto' }}>
              <CheckCircle2 size={40} style={{ marginBottom: '1rem' }} aria-hidden />
              <h2 style={{ marginTop: 0 }}>Dispositif enregistré</h2>
              <p>Votre boîtier est maintenant lié à votre compte.</p>
              {associatedDeviceId && (
                <p style={{ fontSize: '1.05rem', margin: '0.75rem 0' }}>
                  Numéro du boîtier : <strong style={{ letterSpacing: '0.04em' }}>{associatedDeviceId}</strong>
                </p>
              )}
              <p>Vous pouvez commencer à prendre vos mesures.</p>
              <button type="button" className="primary-button" onClick={() => navigate('/patient')}>
                Retour au tableau de bord
              </button>
            </section>
          </main>
        </div>
      </PatientLayout>
    )
  }

  return (
    <PatientLayout>
      <div className="patient-container patient-theme">
        <main className="patient-dashboard" style={{ maxWidth: 440, margin: '0 auto' }}>
          <header className="patient-header">
            <h1>
              <Cpu size={28} style={{ verticalAlign: 'middle', marginRight: 8 }} aria-hidden />
              Enregistrer votre dispositif
            </h1>
            <p>Entrez le code à 6 chiffres affiché sur l&apos;écran de votre boîtier.</p>
          </header>

          {!deviceInfoLoading && associatedDeviceId && (
            <section
              className="panel"
              style={{
                marginBottom: '1.25rem',
                background: 'linear-gradient(135deg, #eff6ff 0%, #f8fafc 100%)',
                border: '1px solid #bfdbfe',
              }}
            >
              <p style={{ margin: 0, fontSize: '0.9rem', color: '#475569' }}>
                Boîtier associé à votre compte
              </p>
              <p style={{ margin: '0.5rem 0 0', fontSize: '1.25rem', fontWeight: 700, color: '#1e3a5f', letterSpacing: '0.03em' }}>
                {associatedDeviceId}
              </p>
              <p style={{ margin: '0.75rem 0 0', fontSize: '0.85rem', color: '#64748b', lineHeight: 1.45 }}>
                Si votre médecin vous a attribué ce matériel, saisissez ci-dessous le code à 6 chiffres affiché sur le boîtier pour terminer l&apos;appairage.
              </p>
            </section>
          )}

          <section className="panel">
            <label htmlFor="enroll-code" style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 600 }}>
              Code à 6 chiffres
            </label>
            <input
              id="enroll-code"
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              value={code}
              onChange={(e) => onCodeChange(e.target.value)}
              placeholder="000000"
              aria-label="Code à 6 chiffres affiché sur le boîtier"
              aria-describedby="enroll-hint"
              style={{
                width: '100%',
                padding: '1rem',
                fontSize: '2rem',
                textAlign: 'center',
                letterSpacing: '0.35em',
                border: '2px solid #2E75B6',
                borderRadius: 8,
                marginBottom: '1rem',
                fontVariantNumeric: 'tabular-nums',
              }}
            />
            <p id="enroll-hint" style={{ margin: '0 0 1rem', fontSize: '0.875rem', color: '#64748b' }}>
              Le code est valable environ 10 minutes après affichage sur le boîtier.
            </p>
            {status && <p className="error-text">{status}</p>}
            <button
              type="button"
              className="primary-button"
              style={{ width: '100%' }}
              onClick={handleEnroll}
              disabled={code.length !== 6 || loading}
            >
              {loading ? 'Vérification…' : 'Enregistrer'}
            </button>
          </section>
        </main>
      </div>
    </PatientLayout>
  )
}
