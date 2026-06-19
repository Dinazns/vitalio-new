import React, { useEffect, useMemo, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useAuth0 } from '@auth0/auth0-react'
import { QRCodeSVG } from 'qrcode.react'
import { ChevronDown, Cpu, Mail, QrCode, Search, Send, TriangleAlert, Users } from 'lucide-react'
import { createDoctorInvitation, getDoctorPatients, getDoctorAlerts } from '../services/api'
import { resolvePatientListDisplayName } from '../utils/displayName'
import { DEVICE_ID_PREFIX, isDeviceIdPrefixOnly, normalizeDeviceIdInput } from '../utils/parseDeviceId'
import DoctorLayout from '../components/DoctorLayout'

function formatLastTime(timestamp) {
  if (!timestamp) return 'Aucune mesure'
  const date = new Date(timestamp)
  return date.toLocaleString('fr-FR')
}

export default function DoctorView() {
  const navigate = useNavigate()
  const { getAccessTokenSilently } = useAuth0()
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [patients, setPatients] = useState([])
  const [inviteInfo, setInviteInfo] = useState(null)
  const [patientEmail, setPatientEmail] = useState('')
  const [inviteDeviceId, setInviteDeviceId] = useState(DEVICE_ID_PREFIX)
  const [sendEmail, setSendEmail] = useState(false)
  const [actionError, setActionError] = useState('')
  const [criticalCount, setCriticalCount] = useState(0)
  const [inviteExpanded, setInviteExpanded] = useState(false)

  useEffect(() => {
    let mounted = true

    const loadDoctorPatients = async () => {
      try {
        setLoading(true)
        setError('')
        const token = await getAccessTokenSilently()
        const [data, alertsRes] = await Promise.all([
          getDoctorPatients(token),
          getDoctorAlerts(token, { status: 'OPEN', limit: 500 }).catch(() => ({ alerts: [] })),
        ])
        if (mounted) {
          setPatients(Array.isArray(data.patients) ? data.patients : [])
          setCriticalCount(Array.isArray(alertsRes.alerts) ? alertsRes.alerts.length : 0)
        }
      } catch (fetchError) {
        if (mounted) {
          setError(fetchError.message || 'Impossible de charger les patients')
        }
      } finally {
        if (mounted) {
          setLoading(false)
        }
      }
    }

    loadDoctorPatients()
    return () => {
      mounted = false
    }
  }, [getAccessTokenSilently])

  const filteredPatients = useMemo(() => {
    const keyword = query.trim().toLowerCase()
    if (!keyword) return patients
    return patients.filter((patient) => {
      const name = resolvePatientListDisplayName(patient).toLowerCase()
      const email = String(patient.email || '').toLowerCase()
      const device = String(patient.device_id || '').toLowerCase()
      return name.includes(keyword) || email.includes(keyword) || device.includes(keyword)
    })
  }, [patients, query])

  const alertCount = Math.max(criticalCount, filteredPatients.filter((patient) => patient.alert).length)

  const handleGenerateInvitation = async () => {
    try {
      setActionError('')
      const token = await getAccessTokenSilently()
      const payload = {}
      if (sendEmail && patientEmail?.trim()) {
        payload.patient_email = patientEmail.trim()
        payload.send_email = true
      }
      const trimmedDevice = inviteDeviceId.trim()
      if (trimmedDevice && !isDeviceIdPrefixOnly(trimmedDevice)) {
        payload.device_id = trimmedDevice
      }
      const data = await createDoctorInvitation(token, payload)
      setInviteInfo(data)
    } catch (e) {
      setActionError(e.message || "Impossible de générer l'invitation")
    }
  }

  return (
    <DoctorLayout>
      <div className="doctor-container doctor-theme">
        <div className="main-content">
          <header className="doctor-header">
            <div className="doctor-header-left">
              <h1 className="doctor-title">Tableau de bord</h1>
              <p className="doctor-subtitle">Suivi de vos patients, invitations et alertes cliniques</p>
            </div>
            <div className="header-actions">
              <Link to="/doctor/alertes" className="doctor-btn doctor-btn-secondary doctor-alertes-link">
                <TriangleAlert size={18} />
                File d&apos;alertes
                {criticalCount > 0 && (
                  <span className="doctor-alertes-badge">{criticalCount}</span>
                )}
              </Link>
              <div className="search-bar">
                <Search className="icon" size={18} />
                <input
                  type="text"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Rechercher un patient..."
                />
              </div>
            </div>
          </header>

          <main className="doctor-main">
          <div className="doctor-workspace">
          <section className="doctor-invite-section">
            <div className={`doctor-invite-card ${inviteExpanded ? 'doctor-invite-card--open' : 'doctor-invite-card--collapsed'}`}>
              <button
                type="button"
                className="doctor-invite-toggle"
                onClick={() => setInviteExpanded((open) => !open)}
                aria-expanded={inviteExpanded}
                aria-controls="doctor-invite-panel"
              >
                <div className="doctor-invite-title-wrap">
                  <Mail size={22} />
                  <h3>Inviter un patient</h3>
                </div>
                <ChevronDown
                  size={20}
                  className={`doctor-invite-chevron ${inviteExpanded ? 'doctor-invite-chevron--open' : ''}`}
                  aria-hidden
                />
              </button>
              {inviteExpanded && (
              <div id="doctor-invite-panel" className="doctor-invite-body">
              <p className="doctor-invite-desc">Générez une invitation par lien ou QR code, envoyée par email au patient.</p>
              <div
                className="doctor-invite-device-panel"
                style={{
                  marginBottom: '1.25rem',
                  padding: '1rem 0 0',
                  borderTop: '1px solid #e2e8f0',
                }}
              >
                <div className="section-header" style={{ marginBottom: '0.75rem' }}>
                  <h3 style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', margin: 0, fontSize: '1rem' }}>
                    <Cpu size={20} /> Boîtier patient
                  </h3>
                </div>
                <p style={{ margin: '0 0 1rem', fontSize: '0.875rem', color: '#64748b', lineHeight: 1.5 }}>
                  Saisissez ou scannez l&apos;identifiant matériel affiché sur le boîtier. Une fois
                  enregistré, le patient peut terminer l&apos;enrôlement à domicile.
                </p>
                <label style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
                  <span style={{ fontSize: '0.75rem', color: '#64748b' }}>Device ID (optionnel)</span>
                  <input
                    type="text"
                    className="doctor-invite-email"
                    value={inviteDeviceId}
                    onChange={(e) => setInviteDeviceId(normalizeDeviceIdInput(e.target.value))}
                    placeholder="VITALIO-XXXXXXXX"
                    autoComplete="off"
                    spellCheck="false"
                  />
                </label>
                <p style={{ margin: '0.75rem 0 0', fontSize: '0.8rem', color: '#94a3b8' }}>
                  Si vous laissez ce champ vide, vous pourrez renseigner le boîtier plus tard depuis la fiche patient.
                </p>
              </div>
              <div className="doctor-invite-form">
                <label className="doctor-invite-checkbox">
                  <input
                    type="checkbox"
                    checked={sendEmail}
                    onChange={(e) => setSendEmail(e.target.checked)}
                  />
                  <span>Envoyer par email au patient</span>
                </label>
                {sendEmail && (
                  <input
                    type="email"
                    className="doctor-invite-email"
                    value={patientEmail}
                    onChange={(e) => setPatientEmail(e.target.value)}
                    placeholder="Email du patient"
                  />
                )}
                <div className="doctor-invite-actions">
                  <button
                    className="doctor-btn doctor-btn-primary"
                    onClick={handleGenerateInvitation}
                  >
                    {sendEmail && patientEmail ? (
                      <>
                        <Send size={18} />
                        Envoyer une invitation
                      </>
                    ) : (
                      <>
                        <QrCode size={18} />
                        Générer invitation patient
                      </>
                    )}
                  </button>
                </div>
              </div>
              {actionError && <p className="doctor-error">{actionError}</p>}
              {inviteInfo && (
                <div className="doctor-invite-result">
                  {(inviteInfo.email_queued || inviteInfo.email_sent) && (
                    <div className="doctor-invite-success">
                      <span className="doctor-invite-success-dot" />
                      {inviteInfo.email_queued
                        ? 'Email en cours d\'envoi au patient (lien d\'invitation).'
                        : 'Email envoyé au patient avec le lien d\'invitation.'}
                    </div>
                  )}
                  {inviteInfo.pending_device_id && (
                    <p style={{ margin: '0 0 0.75rem', fontSize: '0.875rem', color: '#334155' }}>
                      Boîtier prévu pour cette invitation&nbsp;:{' '}
                      <strong style={{ letterSpacing: '0.03em' }}>{inviteInfo.pending_device_id}</strong>
                    </p>
                  )}
                  <div className="doctor-invite-token">
                    <span className="doctor-invite-token-label">Lien d'invitation</span>
                    <code>{inviteInfo.invite_token}</code>
                    <span className="doctor-invite-expiry">
                      Expire le {new Date(inviteInfo.expires_at).toLocaleString('fr-FR')}
                    </span>
                  </div>
                  {(inviteInfo.web_invite_url || inviteInfo.qr_payload) && (
                    <div className="doctor-invite-qr">
                      <div className="doctor-invite-qr-box">
                        <QRCodeSVG
                          value={inviteInfo.web_invite_url || inviteInfo.qr_payload}
                          size={200}
                          level="M"
                        />
                      </div>
                      <p>Scannez pour accepter l'invitation</p>
                    </div>
                  )}
                </div>
              )}
              </div>
              )}
            </div>
          </section>

          <section className="doctor-patients-section">
            <div className="doctor-patients-card">
              <div className="section-header">
                <h3>Patients assignés</h3>
              </div>
              {loading && (
                <div className="doctor-loading">
                  <div className="doctor-loading-spinner" />
                  <p>Chargement des patients...</p>
                </div>
              )}
              {!loading && error && <p className="doctor-error">{error}</p>}
              {!loading && !error && (
                <div className="doctor-table-wrap">
                  <table className="doctor-table">
                    <thead>
                      <tr>
                        <th>Patient</th>
                        <th>Dernière mesure</th>
                        <th>SpO₂</th>
                        <th>FC</th>
                        <th>Température</th>
                        <th>Alerte</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredPatients.map((patient) => (
                        <tr
                          key={patient.id || patient.patient_id}
                          className="patient-row"
                          onClick={() => navigate(`/doctor/patient/${encodeURIComponent(patient.id || patient.patient_id)}`)}
                        >
                          <td>
                            <span className="doctor-table-name">
                              {resolvePatientListDisplayName(patient)}
                            </span>
                          </td>
                          <td>{formatLastTime(patient.last_measurement?.timestamp)}</td>
                          <td>{patient.last_measurement?.spo2 ?? '-'}</td>
                          <td>{patient.last_measurement?.heart_rate ?? '-'}</td>
                          <td>{patient.last_measurement?.temperature ?? '-'}</td>
                          <td>
                            <span className={`risk-badge ${patient.alert ? 'high' : 'low'}`}>
                              {patient.alert ? 'Alerte' : 'OK'}
                            </span>
                          </td>
                        </tr>
                      ))}
                      {!filteredPatients.length && (
                        <tr>
                          <td colSpan="6">
                            <div className="doctor-empty">
                              <Users size={48} />
                              <p>Aucun patient assigné pour ce médecin.</p>
                              <span>Utilisez le panneau d&apos;invitation pour associer des patients.</span>
                            </div>
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </section>
          </div>
          </main>
        </div>
      </div>
    </DoctorLayout>
  )
}
