# Vitalio Relations & Access Test Plan

## Prerequisites

- MongoDB running locally (`mongodb://localhost:27017`)
- API running on `http://localhost:5000`
- Valid Auth0 access tokens for each role:
  - `ADMIN_TOKEN`
  - `DOCTOR_TOKEN`
  - `CAREGIVER_TOKEN`
  - `PATIENT_TOKEN`

## Seed sample data

```powershell
cd back
python seed_relations_feedback.py
```

## Association endpoints (admin)

```bash
curl -X POST http://localhost:5000/api/admin/associations/doctor-patient \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"doctor_user_id_auth":"auth0|seed-doctor","patient_user_id_auth":"auth0|seed-patient"}'
```

```bash
curl -X POST http://localhost:5000/api/admin/associations/caregiver-patient \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"caregiver_user_id_auth":"auth0|seed-caregiver","patient_user_id_auth":"auth0|seed-patient"}'
```

## Doctor / caregiver patient lists

```bash
curl -X GET http://localhost:5000/api/doctor/patients \
  -H "Authorization: Bearer $DOCTOR_TOKEN"
```

```bash
curl -X GET http://localhost:5000/api/caregiver/patients \
  -H "Authorization: Bearer $CAREGIVER_TOKEN"
```

## Authorized measurements access

```bash
curl -X GET "http://localhost:5000/api/patients/auth0%7Cseed-patient/measurements?limit=50" \
  -H "Authorization: Bearer $DOCTOR_TOKEN"
```

## Doctor feedback

```bash
curl -X POST http://localhost:5000/api/doctor/patients/auth0%7Cseed-patient/feedback \
  -H "Authorization: Bearer $DOCTOR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"Hydratation renforcée et contrôle SpO2 matin/soir","severity":"medium","status":"new"}'
```

```bash
curl -X GET "http://localhost:5000/api/patients/auth0%7Cseed-patient/feedback/latest?limit=5" \
  -H "Authorization: Bearer $CAREGIVER_TOKEN"
```

## Forbidden checks (must return 403)

- Doctor token accessing non-associated patient measurements
- Caregiver token posting doctor feedback
- Patient token accessing another patient data
- Non-admin token calling admin association routes
