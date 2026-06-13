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
  return ''
}
