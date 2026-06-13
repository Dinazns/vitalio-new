import React, { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth0 } from '@auth0/auth0-react'
import {
  CheckCircle2,
  Cpu,
  Mail,
  QrCode,
  Download,
  Camera,
  Wifi,
  ChevronRight,
} from 'lucide-react'
import { Html5Qrcode } from 'html5-qrcode'
import {
  validateDeviceEnrollment,
  getPatientDevice,
  downloadDeviceQrcode,
} from '../services/api'
import { DEVICE_WIFI_PORTAL_URL, DEVICE_WIFI_AP_SSID } from '../constants/deviceSetup'
import { isWifiPortalQr, parseDeviceIdFromQr } from '../utils/parseDeviceId'
import PatientLayout from '../components/PatientLayout'

const SCANNER_ID = 'vitalio-qr-reader'

export default function EnrollDevice() {
  const navigate = useNavigate()
  const { getAccessTokenSilently } = useAuth0()
  const scannerRef = useRef(null)
  const validatingRef = useRef(false)

  const [step, setStep] = useState(1)
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(false)
  const [emailSent, setEmailSent] = useState(false)
  const [manualDeviceId, setManualDeviceId] = useState('')
  const [associatedDeviceId, setAssociatedDeviceId] = useState(null)
  const [doctorAssignedDevice, setDoctorAssignedDevice] = useState(false)
  const [deviceEnrolled, setDeviceEnrolled] = useState(false)
  const [deviceInfoLoading, setDeviceInfoLoading] = useState(true)
  const [scannerActive, setScannerActive] = useState(false)
  const [scannerError, setScannerError] = useState(null)
  const [downloadingQr, setDownloadingQr] = useState(false)

  const loadDeviceInfo = useCallback(async () => {
    const token = await getAccessTokenSilently()
    const data = await getPatientDevice(token)
    const did = data?.device_id ? String(data.device_id) : null
    setAssociatedDeviceId(did)
    setManualDeviceId((prev) => prev || did || '')
    setDoctorAssignedDevice(Boolean(data?.doctor_assigned_device))
    setDeviceEnrolled(Boolean(data?.device_enrolled))
  }, [getAccessTokenSilently])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        await loadDeviceInfo()
      } catch {
        /* pas bloquant */
      } finally {
        if (!cancelled) setDeviceInfoLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [loadDeviceInfo])

  const stopScanner = useCallback(async () => {
    if (scannerRef.current) {
      try {
        await scannerRef.current.stop()
        scannerRef.current.clear()
      } catch {
        /* déjà arrêté */
      }
      scannerRef.current = null
    }
    setScannerActive(false)
  }, [])

  useEffect(() => () => {
    stopScanner()
  }, [stopScanner])

  const openWifiPortal = useCallback(() => {
    window.open(DEVICE_WIFI_PORTAL_URL, '_blank', 'noopener,noreferrer')
    setStep(2)
  }, [])

  const handleQrScan = useCallback(
    async (raw) => {
      if (isWifiPortalQr(raw)) {
        await stopScanner()
        openWifiPortal()
        setStatus(null)
        return
      }
      const deviceId = parseDeviceIdFromQr(raw)
      if (deviceId) {
        setManualDeviceId(deviceId)
        setStep(2)
        await stopScanner()
        return
      }
      setStatus('QR code non reconnu. Scannez le QR Wi-Fi (192.168.4.1) ou saisissez votre identifiant boîtier.')
    },
    [openWifiPortal, stopScanner],
  )

  const submitValidation = useCallback(
    async (deviceId) => {
      const normalized = parseDeviceIdFromQr(deviceId) || String(deviceId || '').trim().toUpperCase()
      if (!normalized || !/^VITALIO-[A-F0-9]+$/i.test(normalized)) {
        setStatus('Identifiant invalide (format attendu : VITALIO-XXXXXXXX).')
        return
      }
      if (validatingRef.current) return
      validatingRef.current = true
      setLoading(true)
      setStatus(null)
      try {
        await stopScanner()
        const token = await getAccessTokenSilently()
        await validateDeviceEnrollment(token, normalized)
        setEmailSent(true)
        setManualDeviceId(normalized)
        await loadDeviceInfo()
      } catch (e) {
        setStatus(e.message || 'Erreur lors de la validation')
      } finally {
        setLoading(false)
        validatingRef.current = false
      }
    },
    [getAccessTokenSilently, loadDeviceInfo, stopScanner],
  )

  const startScanner = async () => {
    setScannerError(null)
    setStatus(null)
    try {
      if (scannerRef.current) await stopScanner()
      const scanner = new Html5Qrcode(SCANNER_ID)
      scannerRef.current = scanner
      await scanner.start(
        { facingMode: 'environment' },
        { fps: 10, qrbox: { width: 220, height: 220 } },
        (decoded) => handleQrScan(decoded),
        () => {},
      )
      setScannerActive(true)
    } catch (e) {
      setScannerError(
        String(e.message || e).includes('NotAllowed')
          ? "Autorisez l'accès à la caméra pour scanner le QR code."
          : "Impossible d'accéder à la caméra.",
      )
      setScannerActive(false)
    }
  }

  const handleDownloadWifiQr = async () => {
    setDownloadingQr(true)
    setStatus(null)
    try {
      const token = await getAccessTokenSilently()
      const { blob, filename } = await downloadDeviceQrcode(token, { type: 'wifi' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      setStatus(e.message || 'Téléchargement impossible')
    } finally {
      setDownloadingQr(false)
    }
  }

  const showPaired = deviceEnrolled
  const showFlow = doctorAssignedDevice && !deviceEnrolled

  if (deviceInfoLoading) {
    return (
      <PatientLayout>
        <div className="patient-container patient-theme">
          <main className="patient-dashboard" style={{ maxWidth: 480, margin: '0 auto' }}>
            <div className="panel">Chargement…</div>
          </main>
        </div>
      </PatientLayout>
    )
  }

  if (showPaired) {
    return (
      <PatientLayout>
        <div className="patient-container patient-theme">
          <main className="patient-dashboard">
            <section className="panel panel-success" style={{ textAlign: 'center', maxWidth: 480, margin: '0 auto' }}>
              <CheckCircle2 size={40} style={{ marginBottom: '1rem' }} aria-hidden />
              <h2 style={{ marginTop: 0 }}>Dispositif enregistré</h2>
              <p>Votre boîtier est lié à votre compte.</p>
              {associatedDeviceId && (
                <p style={{ fontSize: '1.05rem', margin: '0.75rem 0' }}>
                  Numéro du boîtier : <strong style={{ letterSpacing: '0.04em' }}>{associatedDeviceId}</strong>
                </p>
              )}
              <button type="button" className="primary-button" onClick={() => navigate('/patient')}>
                Retour au tableau de bord
              </button>
            </section>
          </main>
        </div>
      </PatientLayout>
    )
  }

  if (emailSent) {
    return (
      <PatientLayout>
        <div className="patient-container patient-theme">
          <main className="patient-dashboard" style={{ maxWidth: 480, margin: '0 auto' }}>
            <section className="panel" style={{ textAlign: 'center' }}>
              <Mail size={40} style={{ color: '#2563eb', marginBottom: '1rem' }} aria-hidden />
              <h2 style={{ marginTop: 0 }}>Email envoyé</h2>
              <p>
                Consultez votre boîte mail et cliquez sur le lien de confirmation pour finaliser
                l&apos;enregistrement du boîtier{' '}
                <strong style={{ letterSpacing: '0.03em' }}>{manualDeviceId}</strong>.
              </p>
              <p style={{ fontSize: '0.875rem', color: '#64748b' }}>
                Le lien est valable 24 h. Le boîtier affichera « Dispositif enregistré » une fois confirmé.
              </p>
            </section>
          </main>
        </div>
      </PatientLayout>
    )
  }

  return (
    <PatientLayout>
      <div className="patient-container patient-theme">
        <main className="patient-dashboard" style={{ maxWidth: 520, margin: '0 auto' }}>
          <header className="patient-header">
            <h1>
              <Cpu size={28} style={{ verticalAlign: 'middle', marginRight: 8 }} aria-hidden />
              Enregistrer votre dispositif
            </h1>
            {showFlow ? (
              <p>
                Scannez le QR code collé sur votre boîtier pour configurer le Wi-Fi, puis confirmez
                l&apos;enregistrement par email dans VitalIO.
              </p>
            ) : (
              <p>
                Votre médecin doit d&apos;abord associer l&apos;identifiant de votre boîtier à votre dossier.
              </p>
            )}
          </header>

          {showFlow && associatedDeviceId && (
            <section
              className="panel"
              style={{
                marginBottom: '1.25rem',
                background: 'linear-gradient(135deg, #eff6ff 0%, #f8fafc 100%)',
                border: '1px solid #bfdbfe',
              }}
            >
              <p style={{ margin: 0, fontSize: '0.9rem', color: '#475569' }}>Boîtier assigné par votre médecin</p>
              <p style={{ margin: '0.5rem 0 0', fontSize: '1.25rem', fontWeight: 700, letterSpacing: '0.03em' }}>
                {associatedDeviceId}
              </p>
            </section>
          )}

          {showFlow && (
            <>
              <section className="panel" style={{ marginBottom: '1.25rem' }}>
                <h2 style={{ marginTop: 0, fontSize: '1rem', display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span
                    style={{
                      width: 24,
                      height: 24,
                      borderRadius: '50%',
                      background: step >= 1 ? '#2563eb' : '#e2e8f0',
                      color: '#fff',
                      fontSize: 13,
                      display: 'grid',
                      placeItems: 'center',
                    }}
                  >
                    1
                  </span>
                  <Wifi size={18} aria-hidden />
                  Configurer le Wi-Fi
                </h2>
                <ol style={{ margin: '0 0 1rem', paddingLeft: '1.2rem', lineHeight: 1.55, color: '#475569' }}>
                  <li>
                    Connectez votre téléphone au Wi-Fi <strong>{DEVICE_WIFI_AP_SSID}</strong> (émis par le boîtier).
                  </li>
                  <li>
                    Scannez le QR code sur le boîtier (il ouvre{' '}
                    <strong>{DEVICE_WIFI_PORTAL_URL}</strong>) ou ouvrez ce lien manuellement.
                  </li>
                  <li>Choisissez votre réseau domestique et entrez le mot de passe.</li>
                </ol>
                <div
                  id={SCANNER_ID}
                  style={{
                    width: '100%',
                    minHeight: scannerActive ? 260 : 0,
                    overflow: 'hidden',
                    borderRadius: 12,
                    background: '#0f172a',
                  }}
                />
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: scannerActive ? 12 : 0 }}>
                  {!scannerActive && (
                    <button type="button" className="primary-button" onClick={startScanner} disabled={loading}>
                      <Camera size={18} aria-hidden />
                      Scanner le QR Wi-Fi
                    </button>
                  )}
                  {scannerActive && (
                    <button type="button" className="secondary-button" onClick={stopScanner}>
                      Arrêter le scan
                    </button>
                  )}
                  <button type="button" className="secondary-button" onClick={openWifiPortal}>
                    Ouvrir {DEVICE_WIFI_PORTAL_URL}
                  </button>
                  <button
                    type="button"
                    className="secondary-button"
                    onClick={handleDownloadWifiQr}
                    disabled={downloadingQr}
                    style={{ display: 'inline-flex', alignItems: 'center', gap: 8, justifyContent: 'center' }}
                  >
                    <Download size={16} aria-hidden />
                    {downloadingQr ? 'Téléchargement…' : 'Télécharger le QR Wi-Fi'}
                  </button>
                  <button
                    type="button"
                    className="secondary-button"
                    onClick={() => setStep(2)}
                    style={{ display: 'inline-flex', alignItems: 'center', gap: 8, justifyContent: 'center' }}
                  >
                    Wi-Fi configuré
                    <ChevronRight size={16} aria-hidden />
                  </button>
                </div>
                {scannerError && <p className="error-text" style={{ marginTop: '0.75rem' }}>{scannerError}</p>}
              </section>

              {step >= 2 && (
                <section className="panel">
                  <h2 style={{ marginTop: 0, fontSize: '1rem', display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span
                      style={{
                        width: 24,
                        height: 24,
                        borderRadius: '50%',
                        background: '#2563eb',
                        color: '#fff',
                        fontSize: 13,
                        display: 'grid',
                        placeItems: 'center',
                      }}
                    >
                      2
                    </span>
                    <QrCode size={18} aria-hidden />
                    Confirmer le boîtier par email
                  </h2>
                  <p style={{ color: '#64748b', fontSize: '0.9rem', lineHeight: 1.5 }}>
                    Vérifiez que l&apos;identifiant ci-dessous correspond à celui imprimé à côté du QR sur
                    votre boîtier, puis validez pour recevoir l&apos;email de confirmation.
                  </p>
                  <label htmlFor="manual-device-id" style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 600 }}>
                    Identifiant du boîtier
                  </label>
                  <input
                    id="manual-device-id"
                    type="text"
                    value={manualDeviceId}
                    onChange={(e) => {
                      setManualDeviceId(e.target.value.toUpperCase())
                      if (status) setStatus(null)
                    }}
                    placeholder="VITALIO-CA836AE4"
                    autoComplete="off"
                    spellCheck={false}
                    style={{
                      width: '100%',
                      padding: '0.875rem',
                      fontSize: '1rem',
                      fontFamily: 'monospace',
                      letterSpacing: '0.04em',
                      border: '2px solid #e2e8f0',
                      borderRadius: 8,
                      marginBottom: '1rem',
                    }}
                  />
                  {status && <p className="error-text">{status}</p>}
                  <button
                    type="button"
                    className="primary-button"
                    style={{ width: '100%' }}
                    onClick={() => submitValidation(manualDeviceId)}
                    disabled={!manualDeviceId.trim() || loading}
                  >
                    {loading ? 'Envoi…' : "Recevoir l'email de confirmation"}
                  </button>
                </section>
              )}
            </>
          )}
        </main>
      </div>
    </PatientLayout>
  )
}
