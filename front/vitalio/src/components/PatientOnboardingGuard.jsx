import React, { useEffect, useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useAuth0 } from '@auth0/auth0-react'
import { getPatientProfile } from '../services/api'

/**
 * Redirects patient to /patient/onboarding if onboarding is not completed.
 * Use when wrapping patient routes that require onboarding to be done.
 */
export default function PatientOnboardingGuard({ children }) {
  const navigate = useNavigate()
  const location = useLocation()
  const { getAccessTokenSilently } = useAuth0()
  const [checking, setChecking] = useState(true)
  const [allowed, setAllowed] = useState(false)

  useEffect(() => {
    let mounted = true
    const isOnboardingRoute = location.pathname === '/patient/onboarding'

    ;(async () => {
      try {
        const token = await getAccessTokenSilently()
        const res = await getPatientProfile(token)
        const onboardingCompleted = res?.profile?.onboarding_completed === true
        const hasMeasurements = res?.profile?.has_measurements === true
        const hasDoctor = res?.profile?.has_doctor === true
        // Skip onboarding for users who already have data and are linked to a doctor (existing users)
        const completed = onboardingCompleted || (hasMeasurements && hasDoctor)
        if (mounted) {
          if (isOnboardingRoute && completed) {
            navigate('/patient', { replace: true })
          } else if (!isOnboardingRoute && !completed) {
            navigate('/patient/onboarding', { replace: true })
          } else {
            setAllowed(true)
          }
        }
      } catch {
        if (mounted && isOnboardingRoute) {
          setAllowed(true)
        } else if (mounted) {
          navigate('/patient/onboarding', { replace: true })
        }
      } finally {
        if (mounted) {
          setChecking(false)
        }
      }
    })()
    return () => { mounted = false }
  }, [getAccessTokenSilently, location.pathname, navigate])

  if (checking) {
    return (
      <div className="patient-onboarding patient-onboarding-loading" style={{ placeItems: 'center' }}>
        <p>Chargement...</p>
      </div>
    )
  }

  return allowed ? children : null
}
