import React, { useEffect, useState } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { CheckCircle, AlertCircle, Loader2 } from 'lucide-react'
import { confirmDeviceEnrollment } from '../services/api'

export default function DeviceConfirm() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const token = searchParams.get('token')?.trim() || ''
  const deviceId = searchParams.get('device_id')?.trim() || ''

  const [status, setStatus] = useState('loading')
  const [message, setMessage] = useState('')

  useEffect(() => {
    if (!token || !deviceId) {
      setStatus('error')
      setMessage('Lien incomplet : token ou identifiant du boîtier manquant.')
      return
    }

    let cancelled = false
    ;(async () => {
      try {
        await confirmDeviceEnrollment(token, deviceId)
        if (!cancelled) {
          setStatus('success')
          setMessage('Votre boîtier est enregistré. Vous pouvez commencer à prendre vos mesures.')
        }
      } catch (e) {
        if (!cancelled) {
          setStatus('error')
          setMessage(e.message || "Impossible de confirmer l'enregistrement.")
        }
      }
    })()

    return () => {
      cancelled = true
    }
  }, [token, deviceId])

  const icon =
    status === 'loading' ? (
      <Loader2 size={48} className="spin" style={{ color: '#2563eb', marginBottom: 16 }} aria-hidden />
    ) : status === 'success' ? (
      <CheckCircle size={48} style={{ color: '#059669', marginBottom: 16 }} aria-hidden />
    ) : (
      <AlertCircle size={48} style={{ color: '#dc2626', marginBottom: 16 }} aria-hidden />
    )

  const title =
    status === 'loading'
      ? 'Confirmation en cours…'
      : status === 'success'
        ? 'Boîtier enregistré'
        : 'Confirmation impossible'

  return (
    <div className="login-container">
      <div className="login-card animate-fade-in" style={{ maxWidth: 440, textAlign: 'center' }}>
        {icon}
        <h2 style={{ marginTop: 0 }}>{title}</h2>
        {deviceId && (
          <p style={{ fontFamily: 'monospace', letterSpacing: '0.04em', color: '#475569' }}>{deviceId}</p>
        )}
        {status === 'loading' ? (
          <p>Vérification du lien de confirmation…</p>
        ) : (
          <p>{message}</p>
        )}
        {status !== 'loading' && (
          <button type="button" className="login-button" onClick={() => navigate('/patient')}>
            Accéder à VitalIO
          </button>
        )}
      </div>
    </div>
  )
}
