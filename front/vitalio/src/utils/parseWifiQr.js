import { DEVICE_WIFI_PORTAL_URL } from '../constants/deviceSetup'

/** Décode les séquences échappées du format QR Wi-Fi (ZXing / WPA standard). */
function unescapeWifiField(value) {
  return String(value || '').replace(/\\(.)/g, (_, ch) => {
    if (ch === 'n') return '\n'
    if (ch === 'r') return '\r'
    if (ch === 't') return '\t'
    return ch
  })
}

/**
 * Parse un QR Wi-Fi standard : WIFI:T:WPA;S:MonReseau;P:motdepasse;;
 * @returns {{ ssid: string, password: string } | null}
 */
export function parseWifiCredentialsFromQr(text) {
  if (!text || typeof text !== 'string') return null
  const trimmed = text.trim()
  if (!/^WIFI:/i.test(trimmed)) return null

  const ssidMatch = trimmed.match(/(?:^|;)S:((?:\\.|[^;])*)/i)
  if (!ssidMatch) return null

  const pwdMatch = trimmed.match(/(?:^|;)P:((?:\\.|[^;])*)/i)
  const ssid = unescapeWifiField(ssidMatch[1]).trim()
  if (!ssid) return null

  return {
    ssid,
    password: pwdMatch ? unescapeWifiField(pwdMatch[1]) : '',
  }
}

export function isWifiCredentialsQr(text) {
  return parseWifiCredentialsFromQr(text) !== null
}

/** URL du portail ESP32 qui enregistre le Wi-Fi (handleConnect côté firmware). */
export function buildEspWifiConnectUrl(ssid, password, baseUrl = DEVICE_WIFI_PORTAL_URL) {
  const root = String(baseUrl || 'http://192.168.4.1/').replace(/\/$/, '')
  const params = new URLSearchParams()
  params.set('ssid', ssid)
  if (password) params.set('pwd', password)
  return `${root}/connect?${params.toString()}`
}
