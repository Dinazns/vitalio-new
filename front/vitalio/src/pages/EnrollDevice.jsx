import React, { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth0 } from '@auth0/auth0-react'
import {
  CheckCircle2,
  Cpu,
  Mail,
  Wifi,
  ChevronRight,
  KeyRound,
  Monitor,
} from 'lucide-react'
import {
  enrollPatientDevice,
  getPatientDevice,
  requestEnrollmentCodeEmail,
} from '../services/api'
import { DEVICE_WIFI_PORTAL_URL, DEVICE_WIFI_AP_SSID } from '../constants/deviceSetup'
import PatientLayout from '../components/PatientLayout'

const CODE_SOURCE = {
  DEVICE: 'device',
  EMAIL: 'email',
}

function CodeSourceOption({ active, onClick, icon: Icon, title, description }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        flex: '1 1 200px',
        textAlign: 'left',
        padding: '1rem',
        borderRadius: 10,
        border: active ? '2px solid #2563eb' : '2px solid #e2e8f0',
        background: active ? '#eff6ff' : '#fff',
        cursor: 'pointer',
      }}
    >
      <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
        <Icon size={22} style={{ color: '#2563eb', flexShrink: 0, marginTop: 2 }} aria-hidden />
        <div>
          <strong style={{ display: 'block', marginBottom: 4 }}>{title}</strong>
          <span style={{ fontSize: '0.875rem', color: '#64748b', lineHeight: 1.45 }}>{description}</span>
        </div>
      </div>
    </button>
  )
}

export default function EnrollDevice() {
  const navigate = useNavigate()
  const { getAccessTokenSilently } = useAuth0()
  const enrollingRef = useRef(false)

  const [step, setStep] = useState(1)
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(false)
  const [enrollmentCode, setEnrollmentCode] = useState('')
  const [codeSource, setCodeSource] = useState(null)
  const [emailSending, setEmailSending] = useState(false)
  const [emailSent, setEmailSent] = useState(false)
  const [associatedDeviceId, setAssociatedDeviceId] = useState(null)
  const [doctorAssignedDevice, setDoctorAssignedDevice] = useState(false)
  const [deviceEnrolled, setDeviceEnrolled] = useState(false)
  const [deviceInfoLoading, setDeviceInfoLoading] = useState(true)

  const loadDeviceInfo = useCallback(async () => {
    const token = await getAccessTokenSilently()
    const data = await getPatientDevice(token)
    const did = data?.device_id ? String(data.device_id) : null
    setAssociatedDeviceId(did)
    setDoctorAssignedDevice(Boolean(data?.doctor_assigned_device))
    setDeviceEnrolled(Boolean(data?.device_enrolled))
    return data
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

  const openWifiPortal = useCallback(() => {
    window.open(DEVICE_WIFI_PORTAL_URL, '_blank', 'noopener,noreferrer')
    setStep(2)
  }, [])

  const submitEnrollmentCode = useCallback(async () => {
    const code = enrollmentCode.replace(/\D/g, '').slice(0, 6)
    if (code.length !== 6) {
      setStatus('Saisissez le code à 6 chiffres (écran du boîtier ou e-mail).')
      return
    }
    if (enrollingRef.current) return
    enrollingRef.current = true
    setLoading(true)
    setStatus(null)
    try {
      const token = await getAccessTokenSilently()
      await enrollPatientDevice(token, code)
      await loadDeviceInfo()
      setEnrollmentCode('')
    } catch (e) {
      setStatus(e.message || 'Code invalide ou expiré. Redémarrez le boîtier pour en recevoir un nouveau.')
    } finally {
      setLoading(false)
      enrollingRef.current = false
    }
  }, [enrollmentCode, getAccessTokenSilently, loadDeviceInfo])

  const handleSendCodeEmail = useCallback(async () => {
    setEmailSending(true)
    setStatus(null)
    try {
      const token = await getAccessTokenSilently()
      await requestEnrollmentCodeEmail(token)
      setEmailSent(true)
    } catch (e) {
      setEmailSent(false)
      setStatus(e.message || "Impossible d'envoyer le code par e-mail.")
    } finally {
      setEmailSending(false)
    }
  }, [getAccessTokenSilently])

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
                Connectez-vous au Wi-Fi du boîtier, configurez votre réseau domestique, puis saisissez le code à 6
                chiffres.
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
                    Cliquez sur <strong>Configurer votre boîtier</strong> et suivez les instructions pour connecter le
                    boîtier à votre réseau domestique.
                  </li>
                </ol>
                <p
                  style={{
                    margin: '0 0 1rem',
                    padding: '0.75rem',
                    fontSize: '0.85rem',
                    lineHeight: 1.45,
                    color: '#92400e',
                    background: '#fffbeb',
                    border: '1px solid #fde68a',
                    borderRadius: 8,
                  }}
                >
                  Important : votre téléphone doit être connecté à <strong>{DEVICE_WIFI_AP_SSID}</strong> pour
                  configurer le boîtier.
                </p>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  <button type="button" className="primary-button" onClick={openWifiPortal}>
                    Configurer votre boîtier
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
                    <KeyRound size={18} aria-hidden />
                    Saisir le code à 6 chiffres
                  </h2>

                  <p style={{ color: '#64748b', fontSize: '0.9rem', lineHeight: 1.5, marginBottom: '1rem' }}>
                    Choisissez comment récupérer votre code (valable environ 10 minutes) :
                  </p>
                  <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: '1.25rem' }}>
                    <CodeSourceOption
                      active={codeSource === CODE_SOURCE.DEVICE}
                      onClick={() => {
                        setCodeSource(CODE_SOURCE.DEVICE)
                        setEmailSent(false)
                        if (status) setStatus(null)
                      }}
                      icon={Monitor}
                      title="Sur l'écran du boîtier"
                      description="Le code s'affiche sur le dispositif une fois le Wi-Fi configuré."
                    />
                    <CodeSourceOption
                      active={codeSource === CODE_SOURCE.EMAIL}
                      onClick={() => {
                        setCodeSource(CODE_SOURCE.EMAIL)
                        setEmailSent(false)
                        if (status) setStatus(null)
                      }}
                      icon={Mail}
                      title="Par e-mail"
                      description="Recevez le code à l'adresse associée à votre compte VitalIO."
                    />
                  </div>

                  {codeSource === CODE_SOURCE.DEVICE && (
                    <p style={{ color: '#475569', fontSize: '0.9rem', lineHeight: 1.5, marginBottom: '1rem' }}>
                      Regardez l&apos;écran de votre boîtier et saisissez le code à 6 chiffres ci-dessous.
                    </p>
                  )}

                  {codeSource === CODE_SOURCE.EMAIL && (
                    <div style={{ marginBottom: '1rem' }}>
                      <p style={{ color: '#475569', fontSize: '0.9rem', lineHeight: 1.5, marginBottom: '0.75rem' }}>
                        Demandez l&apos;envoi du code, consultez votre boîte mail, puis saisissez-le ci-dessous.
                      </p>
                      <button
                        type="button"
                        className="secondary-button"
                        onClick={handleSendCodeEmail}
                        disabled={emailSending}
                        style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}
                      >
                        <Mail size={16} aria-hidden />
                        {emailSending ? 'Envoi…' : emailSent ? 'Renvoyer le code par e-mail' : 'Recevoir le code par e-mail'}
                      </button>
                      {emailSent && (
                        <p style={{ color: '#047857', fontSize: '0.875rem', marginTop: '0.75rem' }}>
                          E-mail envoyé. Vérifiez votre boîte de réception (et les spams).
                        </p>
                      )}
                    </div>
                  )}

                  {codeSource && (
                    <>
                  <label htmlFor="enrollment-code" style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 600 }}>
                    Code à 6 chiffres
                  </label>
                  <input
                    id="enrollment-code"
                    type="text"
                    inputMode="numeric"
                    pattern="[0-9]*"
                    maxLength={6}
                    value={enrollmentCode}
                    onChange={(e) => {
                      setEnrollmentCode(e.target.value.replace(/\D/g, '').slice(0, 6))
                      if (status) setStatus(null)
                    }}
                    placeholder="123456"
                    autoComplete="one-time-code"
                    spellCheck={false}
                    style={{
                      width: '100%',
                      padding: '0.875rem',
                      fontSize: '1.5rem',
                      fontFamily: 'monospace',
                      letterSpacing: '0.35em',
                      textAlign: 'center',
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
                    onClick={submitEnrollmentCode}
                    disabled={enrollmentCode.length !== 6 || loading}
                  >
                    {loading ? 'Vérification…' : 'Enregistrer mon boîtier'}
                  </button>
                    </>
                  )}
                </section>
              )}
            </>
          )}
        </main>
      </div>
    </PatientLayout>
  )
}
