# Vitalio Association Migration Notes

## New collections / fields

### `Vitalio_Identity.doctor_patients`

- Added fields for traceability:
  - `linked_by`
  - `linked_by_user_id_auth`
  - `created_at`
- Existing rows without these fields remain valid.

### `Vitalio_Identity.doctor_invites`

- New collection used for both invitation links and cabinet codes.
- Stores only `token_hash` (never raw token/code).
- `expires_at` index with TTL cleanup.

### `Vitalio_Identity.audit_links`

- New audit collection to track association events.

## Indexes added

- `doctor_patients`: unique `(doctor_user_id_auth, patient_user_id_auth)`
- `doctor_invites`: unique `token_hash`
- `doctor_invites`: TTL on `expires_at` (`expireAfterSeconds: 0`)
- `audit_links`: event/date and doctor/patient/date query indexes

## Backward compatibility

- Existing admin association endpoint path is unchanged:
  - `POST /api/admin/associations/doctor-patient`
- Behavior now returns:
  - `201` on created association
  - `409` when association already exists

## Operational notes

- TTL deletion in MongoDB is asynchronous (not immediate to the second).
- API still enforces expiration checks (`410`) based on `expires_at`.
