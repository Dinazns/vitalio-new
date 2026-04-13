const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:5000'

export async function getVapidPublicKey() {
  const res = await fetch(`${API_URL}/api/push/vapid-public-key`)
  if (!res.ok) throw new Error('Failed to get VAPID key')
  const data = await res.json()
  return data.vapid_public_key || ''
}

export async function registerPushSubscription(accessToken, subscription) {
  return apiRequest('/api/me/push-subscribe', accessToken, {
    method: 'POST',
    body: JSON.stringify({ subscription }),
  })
}

export async function apiRequest(endpoint, accessToken, options = {}) {
  const url = `${API_URL}${endpoint}`
  
  const headers = {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${accessToken}`,
    ...options.headers,
  }

  const response = await fetch(url, {
    ...options,
    headers,
  })

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}))
    throw new Error(errorData.message || `HTTP Error: ${response.status}`)
  }

  return response.json()
}

export async function getPatientData(accessToken) {
  return apiRequest('/api/me/data', accessToken, {
    method: 'GET',
  })
}

export async function getPatientWeeklyAnalysis(accessToken) {
  return apiRequest('/api/me/weekly-analysis', accessToken, {
    method: 'GET',
  })
}

export async function getPatientProfile(accessToken) {
  return apiRequest('/api/me/profile', accessToken, {
    method: 'GET',
  })
}

export async function updatePatientProfile(accessToken, payload) {
  return apiRequest('/api/me/profile', accessToken, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export async function completeOnboarding(accessToken, payload) {
  return apiRequest('/api/me/onboarding', accessToken, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function submitPatientMeasurement(accessToken, measurement) {
  return apiRequest('/api/me/measurements', accessToken, {
    method: 'POST',
    body: JSON.stringify(measurement),
  })
}

export async function getDoctorPatients(accessToken) {
  return apiRequest('/api/doctor/patients', accessToken, {
    method: 'GET',
  })
}

export async function getDoctorPatientMeasurements(accessToken, patientId, days = 30) {
  return apiRequest(`/api/doctor/patients/${encodeURIComponent(patientId)}/measurements?days=${days}`, accessToken, {
    method: 'GET',
  })
}

export async function getDoctorPatientTrends(accessToken, patientId) {
  return apiRequest(`/api/doctor/patients/${encodeURIComponent(patientId)}/trends`, accessToken, {
    method: 'GET',
  })
}

export async function getCaregiverPatients(accessToken) {
  return apiRequest('/api/caregiver/patients', accessToken, {
    method: 'GET',
  })
}

export async function getDoctorAlerts(accessToken, params = {}) {
  const sp = new URLSearchParams()
  if (params.status) sp.set('status', params.status)
  if (params.limit) sp.set('limit', String(params.limit))
  const q = sp.toString()
  return apiRequest(`/api/doctor/alerts${q ? `?${q}` : ''}`, accessToken, { method: 'GET' })
}

export async function getCaregiverAlerts(accessToken, params = {}) {
  const sp = new URLSearchParams()
  if (params.status) sp.set('status', params.status)
  if (params.limit) sp.set('limit', String(params.limit))
  const q = sp.toString()
  return apiRequest(`/api/caregiver/alerts${q ? `?${q}` : ''}`, accessToken, { method: 'GET' })
}

export async function patchDoctorAlert(accessToken, alertId, payload) {
  const body =
    typeof payload === 'string'
      ? { doctor_status: payload }
      : {
          ...(payload.doctor_status != null ? { doctor_status: payload.doctor_status } : {}),
          ...(payload.emergency_escalation
            ? { emergency_escalation: payload.emergency_escalation }
            : {}),
        }
  return apiRequest(`/api/doctor/alerts/${encodeURIComponent(alertId)}`, accessToken, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

export async function patchCaregiverAlert(accessToken, alertId, payload) {
  // Supports both legacy string (resolution_comment only) and new structured payload
  const body = typeof payload === 'string'
    ? { resolution_comment: payload }
    : {
        ...(payload.resolution_comment != null ? { resolution_comment: payload.resolution_comment } : {}),
        ...(payload.seen_patient_since_alert != null ? { seen_patient_since_alert: payload.seen_patient_since_alert } : {}),
      }
  return apiRequest(`/api/caregiver/alerts/${encodeURIComponent(alertId)}`, accessToken, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

export async function getDoctorAlert(accessToken, alertId) {
  return apiRequest(`/api/doctor/alerts/${encodeURIComponent(alertId)}`, accessToken, { method: 'GET' })
}

export async function triggerManualAlert(accessToken, message = '') {
  return apiRequest('/api/patient/alerts', accessToken, {
    method: 'POST',
    body: JSON.stringify({ message }),
  })
}

export async function getPatientMeasurementsById(accessToken, patientId, params = {}) {
  const searchParams = new URLSearchParams()
  if (params.limit) searchParams.set('limit', String(params.limit))
  if (params.from) searchParams.set('from', params.from)
  if (params.to) searchParams.set('to', params.to)
  const query = searchParams.toString()
  const endpoint = `/api/patients/${encodeURIComponent(patientId)}/measurements${query ? `?${query}` : ''}`
  return apiRequest(endpoint, accessToken, { method: 'GET' })
}

export async function createDoctorFeedback(accessToken, patientId, feedbackPayload) {
  return apiRequest(`/api/doctor/patients/${encodeURIComponent(patientId)}/feedback`, accessToken, {
    method: 'POST',
    body: JSON.stringify(feedbackPayload),
  })
}

export async function getLatestPatientFeedback(accessToken, patientId, limit = 5) {
  return apiRequest(`/api/patients/${encodeURIComponent(patientId)}/feedback/latest?limit=${limit}`, accessToken, {
    method: 'GET',
  })
}

export async function getPatientDoctorInfo(accessToken, patientId) {
  return apiRequest(`/api/patients/${encodeURIComponent(patientId)}/doctor-info`, accessToken, {
    method: 'GET',
  })
}

export async function getPatientCaregiverInfo(accessToken, patientId) {
  return apiRequest(`/api/patients/${encodeURIComponent(patientId)}/caregiver-info`, accessToken, {
    method: 'GET',
  })
}

export async function getPatientProfileForDoctor(accessToken, patientId) {
  return apiRequest(`/api/patients/${encodeURIComponent(patientId)}/profile`, accessToken, {
    method: 'GET',
  })
}

export async function createDoctorInvitation(accessToken, payload = {}) {
  return apiRequest('/api/doctor/invitations', accessToken, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function createCabinetCode(accessToken, payload = {}) {
  return apiRequest('/api/doctor/cabinet-codes', accessToken, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function acceptDoctorInvitation(accessToken, inviteToken) {
  return apiRequest('/api/patient/invitations/accept', accessToken, {
    method: 'POST',
    body: JSON.stringify({ invite_token: inviteToken }),
  })
}

export async function acceptCaregiverInvitation(accessToken, inviteToken) {
  return apiRequest('/api/caregiver/invitations/accept', accessToken, {
    method: 'POST',
    body: JSON.stringify({ invite_token: inviteToken }),
  })
}

export async function redeemCabinetCode(accessToken, code) {
  return apiRequest('/api/patient/cabinet-codes/redeem', accessToken, {
    method: 'POST',
    body: JSON.stringify({ code }),
  })
}

export async function adminAssociateDoctorPatient(accessToken, doctorId, patientId) {
  return apiRequest('/api/admin/associations/doctor-patient', accessToken, {
    method: 'POST',
    body: JSON.stringify({
      doctor_user_id_auth: doctorId,
      patient_user_id_auth: patientId,
    }),
  })
}

export async function getMLModelInfo() {
  const url = `${API_URL}/api/ml/info`
  const res = await fetch(url)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export async function getMLDecisions(accessToken, params = {}) {
  const sp = new URLSearchParams()
  if (params.device_id) sp.set('device_id', params.device_id)
  if (params.limit) sp.set('limit', String(params.limit))
  const q = sp.toString()
  return apiRequest(`/api/ml/decisions${q ? `?${q}` : ''}`, accessToken, { method: 'GET' })
}

export async function getMLAnomalies(accessToken, params = {}) {
  const sp = new URLSearchParams()
  if (params.status) sp.set('status', params.status)
  if (params.severity) sp.set('severity', params.severity)
  if (params.device_id) sp.set('device_id', params.device_id)
  if (params.from_date) sp.set('from_date', params.from_date)
  if (params.to_date) sp.set('to_date', params.to_date)
  if (params.limit) sp.set('limit', String(params.limit))
  const q = sp.toString()
  return apiRequest(`/api/doctor/ml-anomalies${q ? `?${q}` : ''}`, accessToken, { method: 'GET' })
}

export async function getPatientMLAnalysis(accessToken, patientId, params = {}) {
  const sp = new URLSearchParams()
  if (params.days) sp.set('days', String(params.days))
  if (params.include_forecast != null) sp.set('include_forecast', String(params.include_forecast))
  if (params.forecast_horizon) sp.set('forecast_horizon', String(params.forecast_horizon))
  const q = sp.toString()
  return apiRequest(`/api/doctor/ml/patient-analysis/${encodeURIComponent(patientId)}${q ? `?${q}` : ''}`, accessToken, { method: 'GET' })
}

export async function getMLForecast(accessToken, patientId, params = {}) {
  const sp = new URLSearchParams()
  if (params.days) sp.set('days', String(params.days))
  if (params.train_days) sp.set('train_days', String(params.train_days))
  if (params.history_hours) sp.set('history_hours', String(params.history_hours))
  if (params.horizon) sp.set('horizon', String(params.horizon))
  const q = sp.toString()
  return apiRequest(`/api/doctor/ml/forecast/${encodeURIComponent(patientId)}${q ? `?${q}` : ''}`, accessToken, { method: 'GET' })
}
