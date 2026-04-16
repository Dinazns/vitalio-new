import React, { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth0 } from '@auth0/auth0-react'
import { BookOpen, CheckCircle2, Circle, Cpu, ClipboardList } from 'lucide-react'
import PatientLayout from '../components/PatientLayout'
import { getPatientProfile, getPatientDevice } from '../services/api'
import {
  markPatientWelcomeDone,
  isPatientWelcomeDone,
} from '../constants/patientWelcome'

export default function PatientWelcome() {
  const navigate = useNavigate()
  const { getAccessTokenSilently } = useAuth0()
  const [loading, setLoading] = useState(true)
  const [hasDevice, setHasDevice] = useState(false)
  const [questionnaireDone, setQuestionnaireDone] = useState(false)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const token = await getAccessTokenSilently()
        const [profileRes, deviceRes] = await Promise.all([
          getPatientProfile(token).catch(() => ({ profile: null })),
          getPatientDevice(token).catch(() => ({ device_id: null })),
        ])
        if (cancelled) return
        const profile = profileRes?.profile ?? profileRes
        const deviceId = deviceRes?.device_id
        const onboarded = Boolean(profile?.onboarding_completed)
        const linked = Boolean(deviceId)
        setHasDevice(linked)
        setQuestionnaireDone(onboarded)
        if (linked && onboarded) {
          markPatientWelcomeDone()
          navigate('/patient', { replace: true })
          return
        }
        if (isPatientWelcomeDone()) {
          navigate('/patient', { replace: true })
          return
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [getAccessTokenSilently, navigate])

  const goDashboard = () => {
    markPatientWelcomeDone()
    navigate('/patient', { replace: true })
  }

  if (loading) {
    return (
      <PatientLayout>
        <div className="patient-container patient-theme">
          <main className="patient-dashboard">
            <div className="panel">Chargement…</div>
          </main>
        </div>
      </PatientLayout>
    )
  }

  return (
    <PatientLayout>
      <div className="patient-container patient-theme">
        <main className="patient-dashboard" style={{ maxWidth: 720, margin: '0 auto' }}>
          <header className="patient-header">
            <h1 style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
              <BookOpen size={30} aria-hidden />
              Bienvenue sur VitalIO
            </h1>
            <p>
              Voici comment mettre votre boîtier en service et compléter votre dossier. Vous pourrez retrouver ces
              actions dans le menu à gauche (Mon boîtier, Mon profil).
            </p>
          </header>

          <section className="panel" style={{ marginBottom: '1.25rem' }}>
            <h2 className="panel-title" style={{ marginTop: 0, fontSize: '1.1rem' }}>
              Comment fonctionne l&apos;appairage du boîtier
            </h2>
            <ol style={{ margin: '0.75rem 0 0', paddingLeft: '1.25rem', lineHeight: 1.55, color: '#334155' }}>
              <li>Le boîtier démarre et se connecte au Wi-Fi.</li>
              <li>Il affiche un code à 6 chiffres sur son écran (valable environ 10 minutes).</li>
              <li>Dans VitalIO, ouvrez <strong>Mon boîtier</strong> et saisissez ce code pour lier le dispositif à votre compte.</li>
              <li>Le boîtier confirme l&apos;enregistrement puis peut envoyer vos mesures.</li>
            </ol>
          </section>

          <section className="panel" style={{ marginBottom: '1.25rem' }}>
            <h2 className="panel-title" style={{ marginTop: 0, fontSize: '1.1rem' }}>
              Premières actions
            </h2>
            <ul className="welcome-checklist">
              <li className="welcome-checklist__item">
                <span className="welcome-checklist__icon" aria-hidden>
                  {hasDevice ? <CheckCircle2 size={22} className="welcome-checklist__done" /> : <Circle size={22} />}
                </span>
                <div className="welcome-checklist__body">
                  <strong>Associer votre boîtier</strong>
                  <p className="welcome-checklist__hint">
                    Entrez le code à 6 chiffres affiché sur l&apos;écran du dispositif après sa connexion au réseau.
                  </p>
                  <button
                    type="button"
                    className="primary-button welcome-checklist__btn"
                    onClick={() => navigate('/patient/enroll-device')}
                  >
                    <Cpu size={18} aria-hidden />
                    Mon boîtier - enregistrer le code
                  </button>
                </div>
              </li>
              <li className="welcome-checklist__item">
                <span className="welcome-checklist__icon" aria-hidden>
                  {questionnaireDone ? (
                    <CheckCircle2 size={22} className="welcome-checklist__done" />
                  ) : (
                    <Circle size={22} />
                  )}
                </span>
                <div className="welcome-checklist__body">
                  <strong>Remplir le questionnaire</strong>
                  <p className="welcome-checklist__hint">
                    Dans Mon profil, complétez le questionnaire (identité, aidant, antécédents). Cela finalise votre dossier
                    médical dans l&apos;application.
                  </p>
                  <button
                    type="button"
                    className="secondary-button welcome-checklist__btn"
                    onClick={() => navigate('/patient/profile#questionnaire-patient')}
                  >
                    <ClipboardList size={18} aria-hidden />
                    Mon profil - questionnaire
                  </button>
                </div>
              </li>
            </ul>
          </section>

          <section className="panel panel-cta" style={{ alignItems: 'center' }}>
            <div>
              <h2 style={{ marginTop: 0 }}>Tableau de bord</h2>
              <p style={{ marginBottom: 0 }}>
                Lorsque vous êtes prêt, accédez à vos mesures et à l&apos;analyse. Vous pouvez aussi y aller maintenant et
                revenir plus tard aux étapes ci-dessus via le menu.
              </p>
            </div>
            <button type="button" className="primary-button" onClick={goDashboard}>
              Accéder au tableau de bord
            </button>
          </section>
        </main>
      </div>
    </PatientLayout>
  )
}
