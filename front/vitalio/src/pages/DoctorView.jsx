import React, { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth0 } from '@auth0/auth0-react'
import { QRCodeSVG } from 'qrcode.react'
import { Filter, Mail, QrCode, Search, Send, TriangleAlert, Users } from 'lucide-react'
import { createCabinetCode, createDoctorInvitation, getDoctorPatients, getDoctorAlerts } from '../services/api'
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
  const [cabinetCodeInfo, setCabinetCodeInfo] = useState(null)
  const [patientEmail, setPatientEmail] = useState('')
  const [sendEmail, setSendEmail] = useState(false)
  const [actionError, setActionError] = useState('')
  const [criticalCount, setCriticalCount] = useState(0)

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
      const name = String(patient.display_name || '').toLowerCase()
      const id = String(patient.id || patient.patient_id || '').toLowerCase()
      const device = String(patient.device_id || '').toLowerCase()
      return name.includes(keyword) || id.includes(keyword) || device.includes(keyword)
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
      const data = await createDoctorInvitation(token, payload)
      setInviteInfo(data)
    } catch (e) {
      setActionError(e.message || "Impossible de générer l'invitation")
    }
  }

  const handleGenerateCabinetCode = async () => {
    try {
      setActionError('')
      const token = await getAccessTokenSilently()
      const data = await createCabinetCode(token, { ttl_minutes: 15 })
      setCabinetCodeInfo(data)
    } catch (e) {
      setActionError(e.message || 'Impossible de générer le code cabinet')
    }
  }

  return (
    <DoctorLayout>
      <div className="doctor-container doctor-theme">
        <div className="main-content">
          <header className="doctor-header">
            <div className="doctor-header-left">
              <h1 className="doctor-title">Tableau de bord médecin</h1>
              <p className="doctor-subtitle">Suivez vos patients et gérez les associations</p>
            </div>
            <div className="header-actions">
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
          <section className="doctor-stats">
            <article className="doctor-stat-card doctor-stat-patients">
              <div className="doctor-stat-icon">
                <Users size={24} />
              </div>
              <div className="doctor-stat-content">
                <span className="doctor-stat-value">{patients.length}</span>
                <span className="doctor-stat-label">Patients assignés</span>
              </div>
            </article>
            <article className="doctor-stat-card doctor-stat-alerts">
              <div className="doctor-stat-icon">
                <TriangleAlert size={24} />
              </div>
              <div className="doctor-stat-content">
                <span className="doctor-stat-value doctor-stat-value--critical">{alertCount}</span>
                <span className="doctor-stat-label">Critiques</span>
              </div>
            </article>
            <article className="doctor-stat-card doctor-stat-filtered">
              <div className="doctor-stat-icon">
                <Filter size={24} />
              </div>
              <div className="doctor-stat-content">
                <span className="doctor-stat-value">{filteredPatients.length}</span>
                <span className="doctor-stat-label">Résultats recherche</span>
              </div>
            </article>
          </section>

          <section className="doctor-invite-section">
            <div className="doctor-invite-card">
              <div className="doctor-invite-header">
                <div className="doctor-invite-title-wrap">
                  <Mail size={22} />
                  <h3>Inviter un patient</h3>
                </div>
                <p className="doctor-invite-desc">Générez une invitation par lien ou QR code, envoyée par email au patient.</p>
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
                        Générer et envoyer invitation
                      </>
                    ) : (
                      <>
                        <QrCode size={18} />
                        Générer invitation patient
                      </>
                    )}
                  </button>
                  <button
                    className="doctor-btn doctor-btn-secondary"
                    onClick={handleGenerateCabinetCode}
                  >
                    <QrCode size={18} />
                    Code cabinet / QR
                  </button>
                </div>
              </div>
              {actionError && <p className="doctor-error">{actionError}</p>}
              {inviteInfo && (
                <div className="doctor-invite-result">
                  {inviteInfo.email_sent && (
                    <div className="doctor-invite-success">
                      <span className="doctor-invite-success-dot" />
                      Email envoyé au patient avec le QR code.
                    </div>
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
              {cabinetCodeInfo && (
                <div className="doctor-invite-result doctor-cabinet-result">
                  <span className="doctor-invite-token-label">Code cabinet</span>
                  <code>{cabinetCodeInfo.code}</code>
                  <span className="doctor-invite-expiry">
                    Expire le {new Date(cabinetCodeInfo.expires_at).toLocaleString('fr-FR')}
                  </span>
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
                              {patient.display_name || 'Patient inconnu'}
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
                              <span>Utilisez les invitations ci-dessus pour associer des patients.</span>
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
          </main>
        </div>
      </div>
    </DoctorLayout>
  )
}
