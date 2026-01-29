/**
 * API Service for making authenticated requests to the backend
 */

/**
 * Make an authenticated API request
 * @param {string} endpoint - API endpoint (e.g., '/api/me/data')
 * @param {string} accessToken - Auth0 access token
 * @param {Object} options - Additional fetch options
 * @returns {Promise<Response>}
 */
export async function apiRequest(endpoint, accessToken, options = {}) {
  const baseUrl = import.meta.env.VITE_API_URL ?? 'http://localhost:5000'
  const url = `${baseUrl}${endpoint}`

  const headers = {
    'Content-Type': 'application/json',
    ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
    ...options.headers,
  }

  const response = await fetch(url, {
    ...options,
    headers,
  })

  if (!response.ok) {
    const text = await response.text()
    throw new Error(`HTTP ${response.status}: ${text}`)
  }

  return response.json()
}

/**
 * Get patient data (requires authentication)
 * @param {string} accessToken - Auth0 access token
 * @returns {Promise<Object>} Patient data with device_id and measurements
 */
const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:5000'

export async function getPatientData(accessToken) {
  return apiRequest('/api/me/data', accessToken, {
    method: 'GET',
  })
}

/**
 * Get the device associated with the authenticated user.
 * @param {string} accessToken - Auth0 access token
 * @returns {Promise<{device_id: string, serial_number: string, mqtt_topic: string} | null>} Device or null if none
 */
export async function getMyDevice(accessToken) {
  const response = await fetch(`${API_URL}/api/me/device`, {
    method: 'GET',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${accessToken}`,
    },
  })
  if (response.status === 404) return null
  if (!response.ok) {
    const text = await response.text()
    throw new Error(`HTTP ${response.status}: ${text}`)
  }
  return response.json()
}

/**
 * Pair the authenticated user with a device by serial number.
 * This helper deliberately does NOT throw on non-2xx responses so that
 * the caller can branch on HTTP status codes (201, 404, 409, ...).
 *
 * @param {string} accessToken - Auth0 access token
 * @param {string} serialNumber - Device serial number (e.g. "SIM-ESP32-001")
 * @returns {Promise<{status: number, data: any}>}
 */
export async function pairUserDevice(accessToken, serialNumber) {
  const url = `${API_URL}/api/user-devices`

  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${accessToken}`,
    },
    body: JSON.stringify({
      serial_number: serialNumber,
    }),
  })

  let data = null
  try {
    data = await response.json()
  } catch {
    // ignore JSON parse errors; callers can still inspect status
  }

  return { status: response.status, data }
}

/**
 * Create a doctor→patient association request (doctor only).
 * @param {string} accessToken - Auth0 access token
 * @param {string} patientEmail - Patient email
 * @returns {Promise<{request: object, message?: string}>}
 */
export async function createDoctorRequest(accessToken, patientEmail) {
  return apiRequest('/api/doctor/requests', accessToken, {
    method: 'POST',
    body: JSON.stringify({ patient_email: patientEmail.trim().toLowerCase() }),
  })
}

/**
 * List doctor association requests for the currently authenticated doctor.
 * Backend route: GET /api/doctor/requests
 * @param {string} accessToken - Auth0 access token
 * @returns {Promise<{requests: Array<{id: string, patient_email: string, status: string, created_at: string}>}>}
 */
export async function getMyDoctorRequests(accessToken) {
  return apiRequest('/api/doctor/requests', accessToken, {
    method: 'GET',
  })
}

/**
 * Get measurements for all patients associated with the connected doctor.
 * Backend route: GET /api/doctor/patients/measurements
 * @param {string} accessToken - Auth0 access token
 * @returns {Promise<{patients: Array<{patient_email: string, measurements: Array<{timestamp: string, heart_rate?: number, spo2?: number, temperature?: number}>}>}>}
 */
export async function getDoctorPatientsMeasurements(accessToken) {
  return apiRequest('/api/doctor/patients/measurements', accessToken, {
    method: 'GET',
  })
}

/**
 * List all doctor association requests (admin only, read-only).
 * @param {string} accessToken - Auth0 access token
 * @returns {Promise<{requests: Array<{id: string, doctor_id: string, patient_email: string, created_at: string}>}>}
 */
export async function getDoctorRequests(accessToken) {
  return apiRequest('/api/admin/doctor-requests', accessToken, {
    method: 'GET',
  })
}
