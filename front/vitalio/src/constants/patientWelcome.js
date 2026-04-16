export const VITALIO_PATIENT_WELCOME_DONE_KEY = 'vitalio_patient_welcome_done'

export function markPatientWelcomeDone() {
  try {
    localStorage.setItem(VITALIO_PATIENT_WELCOME_DONE_KEY, '1')
  } catch {
    /* ignore */
  }
}

export function isPatientWelcomeDone() {
  try {
    return Boolean(localStorage.getItem(VITALIO_PATIENT_WELCOME_DONE_KEY))
  } catch {
    return false
  }
}
