/**
 * Web Push registration for doctors and caregivers.
 * Registers the service worker and subscribes to push notifications for alerts.
 */
import { getVapidPublicKey, registerPushSubscription } from '../services/api'

function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const rawData = window.atob(base64)
  const outputArray = new Uint8Array(rawData.length)
  for (let i = 0; i < rawData.length; ++i) {
    outputArray[i] = rawData.charCodeAt(i)
  }
  return outputArray
}

export async function registerPushForAlerts(getAccessTokenSilently) {
  if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) {
    return { ok: false, reason: 'unsupported' }
  }
  if (Notification.permission === 'denied') {
    return { ok: false, reason: 'denied' }
  }
  try {
    const reg = await navigator.serviceWorker.register('/sw.js')
    await reg.ready

    let subscription = await reg.pushManager.getSubscription()
    const vapidKey = await getVapidPublicKey()
    if (!vapidKey) {
      return { ok: false, reason: 'no_vapid' }
    }

    if (!subscription) {
      const perm = await Notification.requestPermission()
      if (perm !== 'granted') {
        return { ok: false, reason: 'denied' }
      }
      subscription = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(vapidKey),
      })
    }

    const sub = subscription.toJSON()
    const token = await getAccessTokenSilently()
    await registerPushSubscription(token, sub)
    return { ok: true }
  } catch (e) {
    console.warn('Push registration failed:', e)
    return { ok: false, reason: String(e?.message || e) }
  }
}
