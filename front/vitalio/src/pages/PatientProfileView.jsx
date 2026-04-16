import React, { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { useAuth0 } from '@auth0/auth0-react'
import {
  User,
  Stethoscope,
  Users,
  X,
  Link2,
  Hash,
  CheckCircle2,
  AlertCircle,
  ClipboardList,
  Heart,
  Send,
  CheckCircle,
  MapPin,
  Download,
  Trash2,
} from 'lucide-react'
import {
  acceptDoctorInvitation,
  completeOnboarding,
  DELETE_PATIENT_DATA_CONFIRM,
  deletePatientAccountData,
  downloadPatientDataExport,
  getPatientProfile,
  redeemCabinetCode,
  updatePatientProfile,
} from '../services/api'
import PatientLayout from '../components/PatientLayout'

const SEX_OPTIONS = [
  { value: 'F', label: 'Féminin' },
  { value: 'M', label: 'Masculin' },
  { value: 'O', label: 'Autre' },
]

function mapSexFromProfile(sex) {
  const v = String(sex || '').toLowerCase()
  if (v === 'f' || v === 'femme') return 'F'
  if (v === 'm' || v === 'homme') return 'M'
  if (v === 'o' || v === 'autre') return 'O'
  const u = String(sex || '').toUpperCase()
  if (u === 'F' || u === 'M' || u === 'O') return u
  return ''
}

function computeAgeFromBirthdate(bd) {
  const s = String(bd || '').trim().slice(0, 10)
  if (s.length < 10) return null
  const parts = s.split('-')
  if (parts.length < 3) return null
  const y = parseInt(parts[0], 10)
  const m = parseInt(parts[1], 10) - 1
  const d = parseInt(parts[2], 10)
  if (Number.isNaN(y) || Number.isNaN(m) || Number.isNaN(d)) return null
  const birth = new Date(y, m, d)
  if (Number.isNaN(birth.getTime())) return null
  const today = new Date()
  let age = today.getFullYear() - birth.getFullYear()
  const md = today.getMonth() - birth.getMonth()
  if (md < 0 || (md === 0 && today.getDate() < birth.getDate())) age -= 1
  return age >= 0 && age <= 150 ? age : null
}

function emptyQuestionnaire() {
  return {
    first_name: '',
    last_name: '',
    email: '',
    phone: '',
    birthdate: '',
    sex: '',
    aidant_first_name: '',
    aidant_last_name: '',
    aidant_email: '',
    aidant_phone: '',
    medical_history: '',
    address_line1: '',
    address_line2: '',
    postal_code: '',
    city: '',
    country: '',
  }
}

export default function PatientProfileView() {
  const location = useLocation()
  const { user, getAccessTokenSilently, logout } = useAuth0()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [profile, setProfile] = useState(null)
  const [inviteToken, setInviteToken] = useState('')
  const [cabinetCode, setCabinetCode] = useState('')
  const [linkingMessage, setLinkingMessage] = useState('')
  const [linkingError, setLinkingError] = useState('')
  const [patientModalOpen, setPatientModalOpen] = useState(false)
  const [doctorModalOpen, setDoctorModalOpen] = useState(false)
  const [caregiverModalOpen, setCaregiverModalOpen] = useState(false)
  const [selectedDoctor, setSelectedDoctor] = useState(null)
  const [selectedCaregiver, setSelectedCaregiver] = useState(null)
  const [q, setQ] = useState(emptyQuestionnaire)
  const [questionnaireSaving, setQuestionnaireSaving] = useState(false)
  const [questionnaireError, setQuestionnaireError] = useState('')
  const [questionnaireSuccess, setQuestionnaireSuccess] = useState('')
  const [sendingAidantInvite, setSendingAidantInvite] = useState(false)
  const [aidantInviteSent, setAidantInviteSent] = useState(false)
  const [exportBusy, setExportBusy] = useState(false)
  const [deleteBusy, setDeleteBusy] = useState(false)
  const [deleteConfirmText, setDeleteConfirmText] = useState('')
  const [dataPortabilityMsg, setDataPortabilityMsg] = useState('')
  const [dataPortabilityErr, setDataPortabilityErr] = useState('')

  const refreshProfile = async () => {
    try {
      const token = await getAccessTokenSilently()
      const profileRes = await getPatientProfile(token).catch(() => ({ profile: null, doctors: [], caregivers: [] }))
      const profileData = profileRes?.profile ?? profileRes
      const doctors = profileRes?.doctors ?? profileData?.doctors ?? []
      const caregivers = profileRes?.caregivers ?? profileData?.caregivers ?? []
      setProfile(profileData ? { ...profileData, doctors, caregivers } : null)
    } catch {
      // ignore
    }
  }

  useEffect(() => {
    let mounted = true
    const fetchData = async () => {
      try {
        setLoading(true)
        setError('')
        const token = await getAccessTokenSilently()
        const profileRes = await getPatientProfile(token).catch(() => ({ profile: null, doctors: [], caregivers: [] }))
        const profileData = profileRes?.profile ?? profileRes
        const doctors = profileRes?.doctors ?? profileData?.doctors ?? []
        const caregivers = profileRes?.caregivers ?? profileData?.caregivers ?? []
        if (mounted) {
          setProfile(profileData ? { ...profileData, doctors, caregivers } : null)
        }
      } catch (fetchError) {
        if (mounted) {
          setError(fetchError.message || "Impossible de charger votre profil")
        }
      } finally {
        if (mounted) {
          setLoading(false)
        }
      }
    }
    fetchData()
    return () => { mounted = false }
  }, [getAccessTokenSilently])

  useEffect(() => {
    if (loading) return
    const id = (location.hash || '').replace(/^#/, '')
    if (id !== 'questionnaire-patient') return
    const el = document.getElementById('questionnaire-patient')
    if (!el) return
    const t = window.setTimeout(() => {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }, 100)
    return () => window.clearTimeout(t)
  }, [loading, location.hash])

  useEffect(() => {
    if (!profile) return
    setQ({
      first_name: profile.first_name || '',
      last_name: profile.last_name || '',
      email: profile.email || user?.email || '',
      phone: profile.phone || '',
      birthdate: profile.birthdate || '',
      sex: mapSexFromProfile(profile.sex),
      aidant_first_name: profile.emergency_contact?.first_name || '',
      aidant_last_name: profile.emergency_contact?.last_name || '',
      aidant_email: profile.emergency_contact?.email || '',
      aidant_phone: profile.emergency_contact?.phone || '',
      medical_history: profile.medical_history || '',
      address_line1: profile.address_line1 || '',
      address_line2: profile.address_line2 || '',
      postal_code: profile.postal_code || '',
      city: profile.city || '',
      country: profile.country || '',
    })
  }, [profile, user?.email])

  useEffect(() => {
    setAidantInviteSent(false)
  }, [q.aidant_email])

  const handleQChange = (field, value) => {
    setQ((prev) => ({ ...prev, [field]: value }))
    setQuestionnaireError('')
    setQuestionnaireSuccess('')
  }

  const handleSendAidantInvitation = async () => {
    const email = (q.aidant_email || '').trim()
    if (!email) {
      setQuestionnaireError('Veuillez renseigner l\'email de l\'aidant avant d\'envoyer l\'invitation.')
      return
    }
    setQuestionnaireError('')
    setQuestionnaireSuccess('')
    setSendingAidantInvite(true)
    try {
      const token = await getAccessTokenSilently()
      await updatePatientProfile(token, {
        emergency_contact: {
          first_name: q.aidant_first_name.trim() || null,
          last_name: q.aidant_last_name.trim() || null,
          email,
          phone: q.aidant_phone.trim() || null,
        },
      })
      setAidantInviteSent(true)
      setQuestionnaireSuccess('Invitation envoyée à l\'aidant.')
      await refreshProfile()
    } catch (err) {
      setQuestionnaireError(err.message || 'Erreur lors de l\'envoi de l\'invitation.')
    } finally {
      setSendingAidantInvite(false)
    }
  }

  const handleSaveQuestionnaire = async (e) => {
    e.preventDefault()
    setQuestionnaireError('')
    setQuestionnaireSuccess('')
    setQuestionnaireSaving(true)
    try {
      const token = await getAccessTokenSilently()
      const patch = {
        first_name: q.first_name.trim() || null,
        last_name: q.last_name.trim() || null,
        email: q.email.trim() || null,
        phone: q.phone.trim() || null,
        birthdate: q.birthdate.trim() || null,
        medical_history: q.medical_history.trim() || null,
        address_line1: q.address_line1.trim() || null,
        address_line2: q.address_line2.trim() || null,
        postal_code: q.postal_code.trim() || null,
        city: q.city.trim() || null,
        country: q.country.trim() || null,
      }
      const age = computeAgeFromBirthdate(q.birthdate)
      if (age != null) patch.age = age
      if (q.sex) patch.sex = q.sex
      const ecEmail = q.aidant_email.trim()
      if (ecEmail) {
        patch.emergency_contact = {
          first_name: q.aidant_first_name.trim() || null,
          last_name: q.aidant_last_name.trim() || null,
          email: ecEmail,
          phone: q.aidant_phone.trim() || null,
        }
      } else if (
        q.aidant_first_name.trim()
        || q.aidant_last_name.trim()
        || q.aidant_phone.trim()
      ) {
        patch.emergency_contact = {
          first_name: q.aidant_first_name.trim() || null,
          last_name: q.aidant_last_name.trim() || null,
          email: null,
          phone: q.aidant_phone.trim() || null,
        }
      }
      await updatePatientProfile(token, patch)

      const givenName = q.first_name.trim()
      const familyName = q.last_name.trim()
      const patientEmail = q.email.trim()
      const birthdate = q.birthdate.trim()
      const history = q.medical_history.trim()
      const canCompleteOnboarding = Boolean(
        givenName
        && familyName
        && patientEmail
        && birthdate
        && q.sex
        && ecEmail
        && history,
      )
      if (canCompleteOnboarding) {
        try {
          await completeOnboarding(token, {
            first_name: givenName,
            last_name: familyName,
            email: patientEmail,
            phone: q.phone.trim() || null,
            birthdate,
            sex: q.sex,
            emergency_contact: {
              first_name: q.aidant_first_name.trim() || null,
              last_name: q.aidant_last_name.trim() || null,
              email: ecEmail,
              phone: q.aidant_phone.trim() || null,
            },
            medical_history: history,
          })
        } catch (obErr) {
          setQuestionnaireError(
            obErr.message
            || 'Les informations ont été enregistrées, mais la validation complète du dossier a échoué (vérifiez la date de naissance AAAA-MM-JJ).',
          )
          await refreshProfile()
          return
        }
      }

      setQuestionnaireSuccess('Votre questionnaire a été enregistré.')
      await refreshProfile()
    } catch (err) {
      setQuestionnaireError(err.message || 'Erreur lors de l\'enregistrement.')
    } finally {
      setQuestionnaireSaving(false)
    }
  }

  const handleAcceptInvitation = async () => {
    try {
      setLinkingError('')
      setLinkingMessage('')
      const token = await getAccessTokenSilently()
      const data = await acceptDoctorInvitation(token, inviteToken.trim())
      setLinkingMessage(`Association réussie avec le médecin ${data.doctor_user_id_auth}`)
      setInviteToken('')
      await refreshProfile()
    } catch (e) {
      setLinkingError(e.message || "Échec d'acceptation de l'invitation")
    }
  }

  const handleRedeemCabinetCode = async () => {
    try {
      setLinkingError('')
      setLinkingMessage('')
      const token = await getAccessTokenSilently()
      const data = await redeemCabinetCode(token, cabinetCode.trim())
      setLinkingMessage(`Code valide. Association réussie avec ${data.doctor_user_id_auth}`)
      setCabinetCode('')
      await refreshProfile()
    } catch (e) {
      setLinkingError(e.message || 'Échec du code cabinet')
    }
  }

  const handleExportData = async () => {
    setDataPortabilityErr('')
    setDataPortabilityMsg('')
    setExportBusy(true)
    try {
      const token = await getAccessTokenSilently()
      const { blob, filename } = await downloadPatientDataExport(token)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.rel = 'noopener'
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
      setDataPortabilityMsg("Téléchargement de l'export lancé.")
    } catch (e) {
      setDataPortabilityErr(e.message || "Échec de l'export.")
    } finally {
      setExportBusy(false)
    }
  }

  const handleDeleteAllData = async () => {
    setDataPortabilityErr('')
    setDataPortabilityMsg('')
    if (deleteConfirmText.trim() !== DELETE_PATIENT_DATA_CONFIRM) {
      setDataPortabilityErr(`Recopiez exactement : ${DELETE_PATIENT_DATA_CONFIRM}`)
      return
    }
    setDeleteBusy(true)
    try {
      const token = await getAccessTokenSilently()
      await deletePatientAccountData(token)
      setDeleteConfirmText('')
      localStorage.removeItem('vitalio_user')
      logout({ logoutParams: { returnTo: window.location.origin } })
    } catch (e) {
      setDataPortabilityErr(e.message || 'La suppression a échoué.')
    } finally {
      setDeleteBusy(false)
    }
  }

  const effectiveCaregivers = profile?.caregivers?.length > 0
    ? profile.caregivers
    : profile?.emergency_contact && (profile.emergency_contact.first_name || profile.emergency_contact.last_name || profile.emergency_contact.email)
      ? [{ id: 'ec', first_name: profile.emergency_contact.first_name, last_name: profile.emergency_contact.last_name, email: profile.emergency_contact.email, phone: profile.emergency_contact.phone, contact: profile.emergency_contact.email }]
      : []

  return (
    <PatientLayout>
      <div className="patient-container patient-theme">
        <main className="patient-dashboard patient-profile-page">
          <header className="patient-header">
            <h1>Mon profil</h1>
            <p>
              Aperçu de votre dossier, liaison médecin, puis questionnaire pour compléter vos informations.
            </p>
          </header>

          {loading && <div className="panel">Chargement du profil...</div>}

          {!loading && error && (
            <div className="panel panel-error">
              <AlertCircle size={20} />
              <span>{error}</span>
            </div>
          )}

          {!loading && !error && (
            <>
            <section className="panel patient-profile-section">
                <div className="patient-profile-cards">
                  <button
                    type="button"
                    className="patient-profile-card patient-profile-card-clickable"
                    onClick={() => setPatientModalOpen(true)}
                  >
                    <User size={24} />
                    <div>
                      <h3>Mon profil</h3>
                      <p>{profile?.first_name || profile?.last_name ? `${profile.first_name} ${profile.last_name}`.trim() : profile?.email || user?.email || '-'}</p>
                    </div>
                  </button>
                  {profile?.doctors?.length ? (
                    profile.doctors.map((d) => (
                      <button
                        key={`doctor-${d.id}`}
                        type="button"
                        className="patient-profile-card patient-profile-card-clickable"
                        onClick={() => {
                          setSelectedDoctor(d)
                          setDoctorModalOpen(true)
                        }}
                      >
                        <Stethoscope size={24} />
                        <div>
                          <h3>Mon médecin</h3>
                          <p>{[d.first_name, d.last_name].filter(Boolean).join(' ') || d.contact || '-'}</p>
                        </div>
                      </button>
                    ))
                  ) : (
                    <div className="patient-profile-card">
                      <Stethoscope size={24} />
                      <div>
                        <h3>Mon médecin</h3>
                        <p className="patient-no-doctor">Aucun médecin associé. Utilisez un lien d'invitation ou un code cabinet ci-dessous.</p>
                      </div>
                    </div>
                  )}
                  {effectiveCaregivers.map((c) => (
                    <button
                      key={`caregiver-${c.id}`}
                      type="button"
                      className="patient-profile-card patient-profile-card-clickable"
                      onClick={() => {
                        setSelectedCaregiver(c)
                        setCaregiverModalOpen(true)
                      }}
                    >
                      <Users size={24} />
                      <div>
                        <h3>Mon aidant</h3>
                        <p>{[c.first_name, c.last_name].filter(Boolean).join(' ') || c.contact || c.email || '-'}</p>
                      </div>
                    </button>
                  ))}
                </div>

                {patientModalOpen && (
                  <div className="profile-modal-overlay" onClick={() => setPatientModalOpen(false)} role="dialog" aria-modal="true" aria-label="Informations personnelles">
                    <div className="profile-modal" onClick={(e) => e.stopPropagation()}>
                      <div className="profile-modal-header">
                        <h2>Mes informations personnelles</h2>
                        <button type="button" className="profile-modal-close" onClick={() => setPatientModalOpen(false)} aria-label="Fermer">
                          <X size={24} />
                        </button>
                      </div>
                      <div className="profile-modal-body">
                        <div className="profile-modal-row">
                          <span className="profile-modal-label">Email</span>
                          <span className="profile-modal-value">{profile?.email || user?.email || '-'}</span>
                        </div>
                        <div className="profile-modal-row">
                          <span className="profile-modal-label">Prénom</span>
                          <span className="profile-modal-value">{profile?.first_name || '-'}</span>
                        </div>
                        <div className="profile-modal-row">
                          <span className="profile-modal-label">Nom</span>
                          <span className="profile-modal-value">{profile?.last_name || '-'}</span>
                        </div>
                        <div className="profile-modal-row">
                          <span className="profile-modal-label">Âge</span>
                          <span className="profile-modal-value">{profile?.age != null ? profile.age : '-'}</span>
                        </div>
                        <div className="profile-modal-row">
                          <span className="profile-modal-label">Sexe</span>
                          <span className="profile-modal-value">
                            {profile?.sex === 'f' || profile?.sex === 'femme' ? 'Femme' : profile?.sex === 'm' || profile?.sex === 'homme' ? 'Homme' : profile?.sex === 'autre' ? 'Autre' : profile?.sex || '-'}
                          </span>
                        </div>
                        {profile?.medical_history && (
                          <div className="profile-modal-row profile-modal-row--block">
                            <span className="profile-modal-label">Historique médical</span>
                            <span className="profile-modal-value">{profile.medical_history}</span>
                          </div>
                        )}
                        {(profile?.address_line1 || profile?.city || profile?.postal_code) && (
                          <div className="profile-modal-row profile-modal-row--block">
                            <span className="profile-modal-label">Adresse (urgences)</span>
                            <span className="profile-modal-value">
                              {[profile.address_line1, profile.address_line2,
                                [profile.postal_code, profile.city].filter(Boolean).join(' ').trim(),
                                profile.country].filter(Boolean).join(', ')}
                            </span>
                          </div>
                        )}
                        {profile?.emergency_contact && (
                          <div className="profile-modal-row">
                            <span className="profile-modal-label">Aidant</span>
                            <span className="profile-modal-value">
                              {[profile.emergency_contact.first_name, profile.emergency_contact.last_name].filter(Boolean).join(' ') || profile.emergency_contact.email || '-'}
                              {profile.emergency_contact.email && (
                                <><br /><small>{profile.emergency_contact.email}</small></>
                              )}
                            </span>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                )}

                {doctorModalOpen && selectedDoctor && (
                  <div className="profile-modal-overlay" onClick={() => { setDoctorModalOpen(false); setSelectedDoctor(null) }} role="dialog" aria-modal="true" aria-label="Informations médecin">
                    <div className="profile-modal" onClick={(e) => e.stopPropagation()}>
                      <div className="profile-modal-header">
                        <h2>Mon médecin</h2>
                        <button type="button" className="profile-modal-close" onClick={() => { setDoctorModalOpen(false); setSelectedDoctor(null) }} aria-label="Fermer">
                          <X size={24} />
                        </button>
                      </div>
                      <div className="profile-modal-body">
                        <div className="profile-modal-row">
                          <span className="profile-modal-label">Prénom</span>
                          <span className="profile-modal-value">{selectedDoctor.first_name || '-'}</span>
                        </div>
                        <div className="profile-modal-row">
                          <span className="profile-modal-label">Nom</span>
                          <span className="profile-modal-value">{selectedDoctor.last_name || '-'}</span>
                        </div>
                        <div className="profile-modal-row">
                          <span className="profile-modal-label">Contact</span>
                          <span className="profile-modal-value">{selectedDoctor.contact || '-'}</span>
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {caregiverModalOpen && selectedCaregiver && (
                  <div className="profile-modal-overlay" onClick={() => { setCaregiverModalOpen(false); setSelectedCaregiver(null) }} role="dialog" aria-modal="true" aria-label="Informations aidant">
                    <div className="profile-modal" onClick={(e) => e.stopPropagation()}>
                      <div className="profile-modal-header">
                        <h2>Mon aidant</h2>
                        <button type="button" className="profile-modal-close" onClick={() => { setCaregiverModalOpen(false); setSelectedCaregiver(null) }} aria-label="Fermer">
                          <X size={24} />
                        </button>
                      </div>
                      <div className="profile-modal-body">
                        <div className="profile-modal-row">
                          <span className="profile-modal-label">Prénom</span>
                          <span className="profile-modal-value">{selectedCaregiver.first_name || '-'}</span>
                        </div>
                        <div className="profile-modal-row">
                          <span className="profile-modal-label">Nom</span>
                          <span className="profile-modal-value">{selectedCaregiver.last_name || '-'}</span>
                        </div>
                        <div className="profile-modal-row">
                          <span className="profile-modal-label">Email</span>
                          <span className="profile-modal-value">{selectedCaregiver.email || '-'}</span>
                        </div>
                        <div className="profile-modal-row">
                          <span className="profile-modal-label">Téléphone</span>
                          <span className="profile-modal-value">{selectedCaregiver.phone || selectedCaregiver.contact || '-'}</span>
                        </div>
                      </div>
                    </div>
                  </div>
                )}
              </section>
              <section className="pq" id="questionnaire-patient" aria-labelledby="pq-title">
                <div className="pq__hero">
                  <div className="pq__hero-icon" aria-hidden>
                    <ClipboardList size={28} strokeWidth={1.75} />
                  </div>
                  <div className="pq__hero-text">
                    <h2 id="pq-title" className="pq__title">Questionnaire</h2>
                    <p className="pq__lead">
                      Complétez les blocs ci-dessous à votre rythme. Les informations sont utilisées pour votre suivi et, pour l&apos;adresse, pour aider les secours en cas d&apos;urgence.
                    </p>
                  </div>
                </div>

                <form className="pq__form" onSubmit={handleSaveQuestionnaire} noValidate>
                  {questionnaireError && (
                    <div className="pq__alert pq__alert--error" role="alert">
                      <AlertCircle size={20} strokeWidth={2} aria-hidden />
                      <span>{questionnaireError}</span>
                    </div>
                  )}
                  {questionnaireSuccess && !questionnaireError && (
                    <div className="pq__alert pq__alert--success" role="status">
                      <CheckCircle2 size={20} strokeWidth={2} aria-hidden />
                      <span>{questionnaireSuccess}</span>
                    </div>
                  )}

                  <div className="pq__grid">
                    <article className="pq-card pq-card--identity">
                      <header className="pq-card__head">
                        <span className="pq-card__step" aria-hidden>1</span>
                        <div className="pq-card__head-main">
                          <div className="pq-card__icon pq-card__icon--teal">
                            <User size={18} aria-hidden />
                          </div>
                          <div>
                            <h3 className="pq-card__title">Vous</h3>
                            <p className="pq-card__hint">Identité et moyens de vous joindre</p>
                          </div>
                        </div>
                      </header>
                      <div className="pq-card__body">
                        <div className="pq-field-row">
                          <div className="pq-field">
                            <label className="pq-label" htmlFor="pq_first_name">Prénom</label>
                            <input
                              id="pq_first_name"
                              className="pq-input"
                              type="text"
                              value={q.first_name}
                              onChange={(e) => handleQChange('first_name', e.target.value)}
                              placeholder="Prénom"
                              autoComplete="given-name"
                            />
                          </div>
                          <div className="pq-field">
                            <label className="pq-label" htmlFor="pq_last_name">Nom</label>
                            <input
                              id="pq_last_name"
                              className="pq-input"
                              type="text"
                              value={q.last_name}
                              onChange={(e) => handleQChange('last_name', e.target.value)}
                              placeholder="Nom"
                              autoComplete="family-name"
                            />
                          </div>
                        </div>
                        <div className="pq-field">
                          <label className="pq-label" htmlFor="pq_email">Adresse e-mail</label>
                          <input
                            id="pq_email"
                            className="pq-input"
                            type="email"
                            value={q.email}
                            onChange={(e) => handleQChange('email', e.target.value)}
                            placeholder="vous@exemple.fr"
                            autoComplete="email"
                          />
                        </div>
                        <div className="pq-field-row">
                          <div className="pq-field">
                            <label className="pq-label" htmlFor="pq_phone">Téléphone</label>
                            <input
                              id="pq_phone"
                              className="pq-input"
                              type="tel"
                              value={q.phone}
                              onChange={(e) => handleQChange('phone', e.target.value)}
                              placeholder="+33 6 00 00 00 00"
                              autoComplete="tel"
                            />
                          </div>
                          <div className="pq-field">
                            <label className="pq-label" htmlFor="pq_birthdate">Naissance (AAAA-MM-JJ)</label>
                            <input
                              id="pq_birthdate"
                              className="pq-input"
                              type="text"
                              inputMode="numeric"
                              value={q.birthdate}
                              onChange={(e) => handleQChange('birthdate', e.target.value)}
                              placeholder="1990-01-15"
                              autoComplete="bday"
                            />
                          </div>
                        </div>
                        <div className="pq-field">
                          <label className="pq-label" htmlFor="pq_sex">Sexe enregistré au dossier</label>
                          <select
                            id="pq_sex"
                            className="pq-select"
                            value={q.sex}
                            onChange={(e) => handleQChange('sex', e.target.value)}
                          >
                            <option value="">Choisir…</option>
                            {SEX_OPTIONS.map((opt) => (
                              <option key={opt.value} value={opt.value}>{opt.label}</option>
                            ))}
                          </select>
                        </div>
                      </div>
                    </article>

                    <article className="pq-card pq-card--address">
                      <header className="pq-card__head">
                        <span className="pq-card__step" aria-hidden>2</span>
                        <div className="pq-card__head-main">
                          <div className="pq-card__icon pq-card__icon--blue">
                            <MapPin size={18} aria-hidden />
                          </div>
                          <div>
                            <h3 className="pq-card__title">Adresse d&apos;urgence</h3>
                            <p className="pq-card__hint">Transmise à votre médecin pour les secours (SAMU) si besoin</p>
                          </div>
                        </div>
                      </header>
                      <div className="pq-card__body">
                        <div className="pq-field">
                          <label className="pq-label" htmlFor="pq_addr1">Rue et numéro</label>
                          <input
                            id="pq_addr1"
                            className="pq-input"
                            type="text"
                            value={q.address_line1}
                            onChange={(e) => handleQChange('address_line1', e.target.value)}
                            placeholder="12 rue des Lilas"
                            autoComplete="address-line1"
                          />
                        </div>
                        <div className="pq-field">
                          <label className="pq-label" htmlFor="pq_addr2">Complément <span className="pq-optional">(optionnel)</span></label>
                          <input
                            id="pq_addr2"
                            className="pq-input"
                            type="text"
                            value={q.address_line2}
                            onChange={(e) => handleQChange('address_line2', e.target.value)}
                            placeholder="Appartement, étage…"
                            autoComplete="address-line2"
                          />
                        </div>
                        <div className="pq-field-row pq-field-row--narrow">
                          <div className="pq-field">
                            <label className="pq-label" htmlFor="pq_cp">Code postal</label>
                            <input
                              id="pq_cp"
                              className="pq-input"
                              type="text"
                              value={q.postal_code}
                              onChange={(e) => handleQChange('postal_code', e.target.value)}
                              placeholder="75001"
                              autoComplete="postal-code"
                            />
                          </div>
                          <div className="pq-field pq-field--grow">
                            <label className="pq-label" htmlFor="pq_city">Ville</label>
                            <input
                              id="pq_city"
                              className="pq-input"
                              type="text"
                              value={q.city}
                              onChange={(e) => handleQChange('city', e.target.value)}
                              placeholder="Paris"
                              autoComplete="address-level2"
                            />
                          </div>
                        </div>
                        <div className="pq-field">
                          <label className="pq-label" htmlFor="pq_country">Pays</label>
                          <input
                            id="pq_country"
                            className="pq-input"
                            type="text"
                            value={q.country}
                            onChange={(e) => handleQChange('country', e.target.value)}
                            placeholder="France"
                            autoComplete="country-name"
                          />
                        </div>
                      </div>
                    </article>

                    <article className="pq-card pq-card--caregiver">
                      <header className="pq-card__head">
                        <span className="pq-card__step" aria-hidden>3</span>
                        <div className="pq-card__head-main">
                          <div className="pq-card__icon pq-card__icon--rose">
                            <Heart size={18} aria-hidden />
                          </div>
                          <div>
                            <h3 className="pq-card__title">Aidant</h3>
                            <p className="pq-card__hint">Personne de confiance et invitation VitalIO</p>
                          </div>
                        </div>
                      </header>
                      <div className="pq-card__body">
                        <div className="pq-field-row">
                          <div className="pq-field">
                            <label className="pq-label" htmlFor="pq_afn">Prénom</label>
                            <input
                              id="pq_afn"
                              className="pq-input"
                              type="text"
                              value={q.aidant_first_name}
                              onChange={(e) => handleQChange('aidant_first_name', e.target.value)}
                              placeholder="Prénom"
                            />
                          </div>
                          <div className="pq-field">
                            <label className="pq-label" htmlFor="pq_aln">Nom</label>
                            <input
                              id="pq_aln"
                              className="pq-input"
                              type="text"
                              value={q.aidant_last_name}
                              onChange={(e) => handleQChange('aidant_last_name', e.target.value)}
                              placeholder="Nom"
                            />
                          </div>
                        </div>
                        <div className="pq-field">
                          <label className="pq-label" htmlFor="pq_aem">E-mail de l&apos;aidant</label>
                          <input
                            id="pq_aem"
                            className="pq-input"
                            type="email"
                            value={q.aidant_email}
                            onChange={(e) => handleQChange('aidant_email', e.target.value)}
                            placeholder="aidant@exemple.fr"
                          />
                        </div>
                        <div className="pq-invite">
                          <button
                            type="button"
                            className="pq-btn pq-btn--secondary"
                            onClick={handleSendAidantInvitation}
                            disabled={sendingAidantInvite || !q.aidant_email?.trim()}
                          >
                            {sendingAidantInvite ? (
                              'Envoi en cours…'
                            ) : aidantInviteSent ? (
                              <>
                                <CheckCircle size={18} aria-hidden />
                                Invitation envoyée
                              </>
                            ) : (
                              <>
                                <Send size={18} aria-hidden />
                                Envoyer l&apos;invitation
                              </>
                            )}
                          </button>
                          {aidantInviteSent && (
                            <p className="pq-invite__note">Un e-mail a été envoyé pour créer ou lier le compte aidant.</p>
                          )}
                        </div>
                        <div className="pq-field">
                          <label className="pq-label" htmlFor="pq_aph">Téléphone de l&apos;aidant</label>
                          <input
                            id="pq_aph"
                            className="pq-input"
                            type="tel"
                            value={q.aidant_phone}
                            onChange={(e) => handleQChange('aidant_phone', e.target.value)}
                            placeholder="06 12 34 56 78"
                          />
                        </div>
                      </div>
                    </article>

                    <article className="pq-card pq-card--medical">
                      <header className="pq-card__head">
                        <span className="pq-card__step" aria-hidden>4</span>
                        <div className="pq-card__head-main">
                          <div className="pq-card__icon pq-card__icon--slate">
                            <ClipboardList size={18} aria-hidden />
                          </div>
                          <div>
                            <h3 className="pq-card__title">Historique médical</h3>
                            <p className="pq-card__hint">Antécédents, traitements, allergies utiles au suivi</p>
                          </div>
                        </div>
                      </header>
                      <div className="pq-card__body">
                        <div className="pq-field">
                          <label className="pq-label" htmlFor="pq_mh">Informations pour votre équipe soignante</label>
                          <textarea
                            id="pq_mh"
                            className="pq-textarea"
                            value={q.medical_history}
                            onChange={(e) => handleQChange('medical_history', e.target.value)}
                            placeholder="Ex. hypertension, anticoagulants, allergies médicamenteuses, opérations récentes…"
                            rows={6}
                          />
                        </div>
                      </div>
                    </article>
                  </div>

                  <div className="pq__actions">
                    <p className="pq__actions-hint">
                      Lorsque les champs requis par le dossier médical sont remplis, l&apos;enregistrement marque aussi votre parcours comme complet pour votre médecin.
                    </p>
                    <button type="submit" className="pq-btn pq-btn--primary" disabled={questionnaireSaving}>
                      {questionnaireSaving ? 'Enregistrement en cours…' : 'Enregistrer tout le questionnaire'}
                    </button>
                  </div>
                </form>
              </section>

              {!profile?.doctors?.length && (
                <section className="panel">
                  <div className="panel-title">
                    <h2>Associer mon médecin</h2>
                  </div>
                  <p className="link-doctor-subtitle">
                    Deux façons de vous connecter à votre médecin :
                  </p>
                  <div className="link-doctor-grid">
                    <div className="link-doctor-card">
                      <div className="link-doctor-card-header">
                        <span className="link-doctor-icon link-doctor-icon--invite">
                          <Link2 size={18} />
                        </span>
                        <div>
                          <h3>Lien d'invitation</h3>
                          <p>Votre médecin vous a envoyé un token par e-mail.</p>
                        </div>
                      </div>
                      <div className="link-doctor-input-row">
                        <input
                          type="text"
                          className="link-doctor-input"
                          value={inviteToken}
                          onChange={(e) => setInviteToken(e.target.value)}
                          placeholder="Coller le token ici…"
                        />
                        <button
                          className="link-doctor-btn link-doctor-btn--invite"
                          onClick={handleAcceptInvitation}
                          disabled={!inviteToken.trim()}
                        >
                          Accepter
                        </button>
                      </div>
                    </div>

                    <div className="link-doctor-divider">
                      <span>ou</span>
                    </div>

                    <div className="link-doctor-card">
                      <div className="link-doctor-card-header">
                        <span className="link-doctor-icon link-doctor-icon--cabinet">
                          <Hash size={18} />
                        </span>
                        <div>
                          <h3>Code cabinet</h3>
                          <p>Code temporaire affiché chez votre médecin.</p>
                        </div>
                      </div>
                      <div className="link-doctor-input-row">
                        <input
                          type="text"
                          className="link-doctor-input"
                          value={cabinetCode}
                          onChange={(e) => setCabinetCode(e.target.value)}
                          placeholder="Code à 6 caractères…"
                        />
                        <button
                          className="link-doctor-btn link-doctor-btn--cabinet"
                          onClick={handleRedeemCabinetCode}
                          disabled={!cabinetCode.trim()}
                        >
                          Valider
                        </button>
                      </div>
                    </div>
                  </div>

                  {linkingError && (
                    <div className="link-doctor-feedback link-doctor-feedback--error">
                      <AlertCircle size={16} />
                      <span>{linkingError}</span>
                    </div>
                  )}
                  {linkingMessage && (
                    <div className="link-doctor-feedback link-doctor-feedback--success">
                      <CheckCircle2 size={16} />
                      <span>{linkingMessage}</span>
                    </div>
                  )}
                </section>
              )}

              <section className="panel patient-data-portability" aria-labelledby="data-portability-title">
                <div className="panel-title">
                  <h2 id="data-portability-title">Mes données</h2>
                </div>
                <p className="link-doctor-subtitle">
                  Exportez une copie complète de vos informations VitalIO, ou demandez la suppression définitive de vos données sur notre plateforme (mesures, profil, liaisons). Vous serez déconnecté après suppression.
                </p>
                {dataPortabilityErr && (
                  <div className="link-doctor-feedback link-doctor-feedback--error" style={{ marginTop: '0.75rem' }}>
                    <AlertCircle size={16} />
                    <span>{dataPortabilityErr}</span>
                  </div>
                )}
                {dataPortabilityMsg && (
                  <div className="link-doctor-feedback link-doctor-feedback--success" style={{ marginTop: '0.75rem' }}>
                    <CheckCircle2 size={16} />
                    <span>{dataPortabilityMsg}</span>
                  </div>
                )}
                <div className="patient-data-portability__actions">
                  <button
                    type="button"
                    className="secondary-button"
                    onClick={handleExportData}
                    disabled={exportBusy}
                  >
                    <Download size={18} aria-hidden />
                    {exportBusy ? 'Préparation…' : 'Exporter mes données'}
                  </button>
                </div>
                <div className="patient-data-portability__danger">
                  <p>
                    Pour supprimer <strong>toutes</strong> vos données côté VitalIO, saisissez exactement la phrase ci-dessous puis cliquez sur le bouton. Cette action est irréversible.
                  </p>
                  <code className="patient-data-portability__phrase">{DELETE_PATIENT_DATA_CONFIRM}</code>
                  <input
                    type="text"
                    className="link-doctor-input patient-data-portability__confirm-input"
                    value={deleteConfirmText}
                    onChange={(e) => {
                      setDeleteConfirmText(e.target.value)
                      setDataPortabilityErr('')
                    }}
                    placeholder="Coller la phrase de confirmation"
                    autoComplete="off"
                    disabled={deleteBusy}
                  />
                  <button
                    type="button"
                    className="secondary-button"
                    onClick={handleDeleteAllData}
                    disabled={deleteBusy || deleteConfirmText.trim() !== DELETE_PATIENT_DATA_CONFIRM}
                  >
                    <Trash2 size={18} aria-hidden />
                    {deleteBusy ? 'Suppression…' : 'Supprimer mes données et me déconnecter'}
                  </button>
                </div>
              </section>
            </>
          )}
        </main>
      </div>
    </PatientLayout>
  )
}
