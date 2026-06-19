const AUTH_PROVIDER_ID_RE = /^(auth0|google-oauth2|windowslive|github)\|/

export function isAuthProviderId(value) {
  if (!value || typeof value !== 'string') return false
  const trimmed = value.trim()
  return AUTH_PROVIDER_ID_RE.test(trimmed) && !trimmed.includes(' ')
}

function isEmailLike(value) {
  if (!value) return false
  return String(value).includes('@')
}

function pickDisplayCandidate(value) {
  if (!value || isAuthProviderId(value) || isEmailLike(value)) return null
  const trimmed = String(value).trim()
  return trimmed || null
}

/**
 * Resolve a patient-facing display name without exposing Auth0 subject ids.
 */
export function resolvePatientDisplayName({ profile, user } = {}) {
  const fullName = profile?.first_name || profile?.last_name
    ? `${profile?.first_name || ''} ${profile?.last_name || ''}`.trim()
    : null

  const candidates = [
    pickDisplayCandidate(fullName),
    pickDisplayCandidate(profile?.display_name),
    pickDisplayCandidate(user?.given_name),
    pickDisplayCandidate(user?.name),
  ]

  for (const candidate of candidates) {
    if (candidate) return candidate
  }

  const email = String(profile?.email || user?.email || '').trim()
  if (email.includes('@')) return email
  return ''
}

/**
 * Display label for patient rows returned by doctor/caregiver list APIs.
 */
export function resolvePatientListDisplayName(patient) {
  if (!patient) return ''
  const fromApi = String(patient.display_name || '').trim()
  if (fromApi && !isAuthProviderId(fromApi)) return fromApi
  const email = String(patient.email || '').trim()
  if (email.includes('@')) return email
  return ''
}

/**
 * Prénom + nom pour l’UI (suivi avancé, en-têtes) - jamais d’identifiant technique.
 */
export function resolvePatientFullName({ profile, analysis } = {}) {
  const firstCandidates = [
    profile?.first_name,
    analysis?.patient_first_name,
  ]
  const lastCandidates = [
    profile?.last_name,
    analysis?.patient_last_name,
  ]

  const first = firstCandidates.map((v) => String(v || '').trim()).find((v) => v && !isAuthProviderId(v)) || ''
  const last = lastCandidates.map((v) => String(v || '').trim()).find((v) => v && !isAuthProviderId(v)) || ''
  const full = `${first} ${last}`.trim()
  if (full) return full

  for (const src of [profile?.display_name, analysis?.patient_display]) {
    const candidate = pickDisplayCandidate(src)
    if (candidate) return candidate
  }

  return ''
}
