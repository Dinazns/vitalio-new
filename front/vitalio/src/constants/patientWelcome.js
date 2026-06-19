/** Prefix for per–Auth0-user keys (`sub`). The old app used this string alone as a global flag (bug on shared browsers). */
export const VITALIO_PATIENT_WELCOME_DONE_KEY = 'vitalio_patient_welcome_done'

function storageKeyForUser(userId) {
  if (!userId) return null
  return `${VITALIO_PATIENT_WELCOME_DONE_KEY}:${userId}`
}

export function markPatientWelcomeDone(userId) {
  const key = storageKeyForUser(userId)
  if (!key) return
  try {
    localStorage.setItem(key, '1')
    try {
      localStorage.removeItem(VITALIO_PATIENT_WELCOME_DONE_KEY)
    } catch {
      /* ignore - removes legacy global key only; per-user keys use ":sub" suffix */
    }
  } catch {
    /* ignore */
  }
}

export function isPatientWelcomeDone(userId) {
  const key = storageKeyForUser(userId)
  if (!key) return false
  try {
    return Boolean(localStorage.getItem(key))
  } catch {
    return false
  }
}
