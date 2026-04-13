import React, { useEffect, useState } from 'react'
import { Bell, X, BellOff, Check, Loader } from 'lucide-react'
import { registerPushForAlerts } from '../utils/pushNotifications'

const DISMISSED_KEY = 'vitalio_push_dismissed'

export default function PushPermissionBanner({ getAccessTokenSilently }) {
  const [show, setShow] = useState(false)
  const [status, setStatus] = useState('idle') // idle | loading | success | denied | error

  useEffect(() => {
    if (
      !('Notification' in window) ||
      !('serviceWorker' in navigator) ||
      !('PushManager' in window)
    ) return

    if (Notification.permission === 'granted') {
      // Permission already granted — silently ensure subscription is registered
      registerPushForAlerts(getAccessTokenSilently).catch(() => {})
      return
    }

    if (Notification.permission !== 'default') return
    if (localStorage.getItem(DISMISSED_KEY)) return
    setShow(true)
  }, [getAccessTokenSilently])

  if (!show) return null

  const handleActivate = async () => {
    setStatus('loading')
    try {
      const result = await registerPushForAlerts(getAccessTokenSilently)
      if (result.ok) {
        setStatus('success')
        setTimeout(() => setShow(false), 2500)
      } else if (result.reason === 'denied') {
        setStatus('denied')
      } else {
        setStatus('error')
      }
    } catch {
      setStatus('error')
    }
  }

  const handleDismiss = () => {
    localStorage.setItem(DISMISSED_KEY, '1')
    setShow(false)
  }

  return (
    <div className={`push-banner push-banner--${status}`} role="banner" aria-live="polite">
      <div className="push-banner__icon">
        {status === 'loading' && <Loader size={18} className="push-banner__spin" />}
        {status === 'success' && <Check size={18} />}
        {status === 'denied' && <BellOff size={18} />}
        {(status === 'idle' || status === 'error') && <Bell size={18} />}
      </div>

      <div className="push-banner__content">
        {status === 'idle' && (
          <>
            <span className="push-banner__title">Activer les notifications d'alertes</span>
            <span className="push-banner__desc">
              Recevez une notification Chrome instantanée dès qu'une alerte patient se déclenche.
            </span>
          </>
        )}
        {status === 'loading' && <span className="push-banner__title">Activation en cours…</span>}
        {status === 'success' && (
          <span className="push-banner__title">Notifications activées - vous serez alerté en temps réel.</span>
        )}
        {status === 'denied' && (
          <span className="push-banner__title">
            Permission refusée. Autorisez les notifications dans les paramètres Chrome.
          </span>
        )}
        {status === 'error' && (
          <span className="push-banner__title">Erreur lors de l'activation. Réessayez plus tard.</span>
        )}
      </div>

      {status === 'idle' && (
        <div className="push-banner__actions">
          <button className="push-banner__btn push-banner__btn--primary" onClick={handleActivate}>
            Activer
          </button>
          <button
            className="push-banner__btn push-banner__btn--ghost"
            onClick={handleDismiss}
            aria-label="Plus tard"
          >
            Plus tard
          </button>
        </div>
      )}

      {(status === 'denied' || status === 'error') && (
        <button
          className="push-banner__close"
          onClick={handleDismiss}
          aria-label="Fermer"
        >
          <X size={16} />
        </button>
      )}
    </div>
  )
}
