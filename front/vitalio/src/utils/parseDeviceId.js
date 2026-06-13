import { DEVICE_WIFI_PORTAL_URL } from '../constants/deviceSetup'

/** true si le QR pointe vers le portail Wi-Fi ESP32. */
export function isWifiPortalQr(text) {
  if (!text || typeof text !== 'string') return false
  const t = text.trim().toLowerCase()
  return (
    t === DEVICE_WIFI_PORTAL_URL.toLowerCase()
    || t.includes('192.168.4.1')
    || t.startsWith('http://192.168.4.1')
  )
}

/** Extrait VITALIO-XXXXXXXX d'un QR ou saisie. */
export function parseDeviceIdFromQr(text) {
  if (!text || typeof text !== 'string') return null
  const trimmed = text.trim()
  if (/^VITALIO-[A-F0-9]+$/i.test(trimmed)) {
    return trimmed.toUpperCase()
  }
  try {
    const url = new URL(trimmed)
    const fromQuery = url.searchParams.get('device_id')
    if (fromQuery && /^VITALIO-/i.test(fromQuery)) {
      return fromQuery.trim().toUpperCase()
    }
  } catch {
    /* pas une URL */
  }
  const match = trimmed.match(/VITALIO-[A-F0-9]+/i)
  return match ? match[0].toUpperCase() : null
}
