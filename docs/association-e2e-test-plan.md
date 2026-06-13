# Association E2E Test Plan

## Actors

- `ADMIN_TOKEN`
- `DOCTOR_TOKEN`
- `PATIENT_TOKEN`
- `CAREGIVER_TOKEN`

## 1) Invitation flow (doctor -> patient)

1. Doctor creates invite:
   - `POST /api/doctor/invitations`
2. Patient accepts invite:
   - `POST /api/patient/invitations/accept`
3. Verify association appears in:
   - `GET /api/doctor/patients`

Expected:
- creation `201`
- accept `201`
- duplicate accept `409`

## 2) Admin association flow

1. Admin links doctor/patient:
   - `POST /api/admin/associations/doctor-patient`
2. Repeat same request.

Expected:
- first `201`
- second `409`

## 3) Cabinet code / QR flow

1. Doctor generates code:
   - `POST /api/doctor/cabinet-codes`
2. Patient redeems:
   - `POST /api/patient/cabinet-codes/redeem`
3. Redeem again.

Expected:
- generation `201`
- first redeem `201`
- second redeem `409`

## 4) Expiration checks

- Wait for expiry or use short TTL (`ttl_minutes=10`) and retry redeem/accept.

Expected:
- endpoint returns `410`

## 5) Forbidden checks (must be `403`)

- Patient accepts invite targeted to another patient.
- Caregiver calls doctor-only creation endpoints.
- Doctor accesses unassociated patient via shared patient endpoints.
- Non-admin calls admin association endpoint.
