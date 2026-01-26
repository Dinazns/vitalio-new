# Healthcare Flask API - Production Implementation

A production-grade Flask API that implements secure patient data access following a strict sequence diagram architecture for healthcare IoT/M2M systems.

## Architecture Overview

This API enforces **strict separation** between identity (Auth0) and medical data:

- **Identity Layer**: Auth0 handles user authentication via JWT (RS256)
- **Correspondence Layer**: Maps Auth0 user IDs to patient pivot IDs
- **Medical Layer**: Stores and retrieves patient vital measurements

**No direct access** to medical data is permitted. All requests must:
1. Authenticate via Auth0 JWT
2. Resolve patient identity through correspondence table
3. Query medical data using pivot ID only

## Features

**JWT Authentication**: RS256 signature verification using Auth0 JWKS  
**Strict Sequence Compliance**: Follows exact 10-step sequence diagram  
**Identity Separation**: Medical database never contains Auth0 user IDs  
**Production-Ready**: Comprehensive error handling and security  
**Healthcare-Grade**: Suitable for academic and production healthcare systems  

## Installation

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Create a `.env` file in the project root:

```env
# Auth0 Configuration
AUTH0_DOMAIN=your-tenant.auth0.com
AUTH0_AUDIENCE=https://your-api-identifier

# Database Configuration (Supabase)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-supabase-service-role-key

# Flask Configuration (optional)
FLASK_HOST=0.0.0.0
FLASK_PORT=5000
FLASK_DEBUG=False
```

### 3. Database Setup

Ensure you have:
- **Correspondence table**: Maps `user_id_auth` (Auth0 user ID) to `patient_id_pivot`
- **Measurements table**: Stores vital signs with `patient_id_pivot` (or `u_id`) column

See `database_schema.md` for detailed schema documentation.

## API Endpoints

### GET /api/me/data

**Protected endpoint** that returns patient medical data.

**Authentication**: Required (JWT Bearer token)

**Request**:
```bash
curl -X GET http://localhost:5000/api/me/data \
  -H "Authorization: Bearer <JWT_ACCESS_TOKEN>"
```

**Response** (200 OK):
```json
{
  "patient_id_pivot": "PAT-001",
  "measurements": [
    {
      "timestamp": "2024-01-15T10:31:00",
      "heart_rate": 75,
      "spo2": 97,
      "temperature": 36.9
    },
    {
      "timestamp": "2024-01-15T10:30:00",
      "heart_rate": 72,
      "spo2": 98,
      "temperature": 36.8
    }
  ],
  "measurement_count": 2
}
```

**Error Responses**:

- `401 Unauthorized`: Invalid or missing JWT token
- `404 Not Found`: Patient record not found in correspondence table
- `500 Internal Server Error`: Database or configuration error

### GET /health

**Public endpoint** for health checks.

**Response**:
```json
{
  "status": "healthy",
  "service": "healthcare-api"
}
```

## Sequence Diagram Implementation

The API implements the following exact sequence:

1. **Frontend** authenticates user via Auth0
2. **Auth0** returns signed JWT (access token)
3. **Frontend** calls `GET /api/me/data` with `Authorization: Bearer <JWT>`
4. **Flask API** verifies JWT:
   - Signature (RS256) using Auth0 JWKS
   - Issuer (`https://{AUTH0_DOMAIN}/`)
   - Audience (API_AUDIENCE)
   - Expiration
   - Extracts `user_id_auth` from JWT `sub` claim
5. **Flask API** authorizes request and identifies user as patient
6. **Flask API** queries correspondence database:
   ```sql
   SELECT patient_id_pivot 
   FROM correspondence 
   WHERE user_id_auth = '<JWT sub>'
   ```
7. **Correspondence database** returns `patient_id_pivot`
8. **Flask API** queries medical database:
   ```sql
   SELECT timestamp, heart_rate, spo2, temperature 
   FROM measurements 
   WHERE patient_id_pivot = '<patient_id_pivot>'
   ORDER BY timestamp DESC
   LIMIT 100
   ```
9. **Medical database** returns vital measurements
10. **Flask API** returns minimal patient identity + medical measurements

## Security Features

### JWT Validation

- **Algorithm**: RS256 (asymmetric signing)
- **Key Source**: Auth0 JWKS endpoint (`.well-known/jwks.json`)
- **Validation Checks**:
  - Signature verification
  - Issuer validation
  - Audience validation
  - Expiration check
  - `sub` claim extraction

### Data Isolation

- **No Direct Access**: Frontend cannot query medical database directly
- **Pivot Resolution**: All medical queries require correspondence table lookup
- **Minimal Identity**: Only `patient_id_pivot` returned, never `user_id_auth`
- **Database Separation**: Medical database has no Auth0 user ID columns

### Error Handling

- **AuthError**: Authentication/authorization failures (401)
- **DatabaseError**: Database operation failures (500)
- **No Information Leakage**: Error messages don't expose internal details

## Code Structure

```
api.py
├── Configuration
│   ├── Auth0 settings (domain, audience)
│   └── Database settings (Supabase)
├── Error Handling
│   ├── AuthError (authentication failures)
│   └── DatabaseError (database failures)
├── JWT Authentication (Steps 3-5)
│   ├── get_token_auth_header()
│   ├── verify_jwt()
│   └── @requires_auth decorator
├── Database Access Layer
│   ├── get_patient_id_pivot() (Steps 6-7)
│   └── get_patient_measurements() (Steps 8-9)
└── API Routes
    ├── GET /api/me/data (Step 10)
    └── GET /health
```

## Running the API

### Development Mode

```bash
python api.py
```

The API will start on `http://localhost:5000` (or configured port).

### Production Mode

Set `FLASK_DEBUG=False` in `.env` and use a production WSGI server:

```bash
gunicorn -w 4 -b 0.0.0.0:5000 api:app
```

## Testing

### 1. Get Auth0 Access Token

Using Auth0 Management API or OAuth2 flow:

```bash
curl -X POST https://{AUTH0_DOMAIN}/oauth/token \
  -H "Content-Type: application/json" \
  -d '{
    "client_id": "YOUR_CLIENT_ID",
    "client_secret": "YOUR_CLIENT_SECRET",
    "audience": "YOUR_API_AUDIENCE",
    "grant_type": "client_credentials"
  }'
```

### 2. Test Protected Endpoint

```bash
curl -X GET http://localhost:5000/api/me/data \
  -H "Authorization: Bearer <YOUR_ACCESS_TOKEN>"
```

### 3. Test Health Check

```bash
curl http://localhost:5000/health
```

## Database Schema

See `database_schema.md` for complete schema documentation including:
- Correspondence table structure
- Measurements table structure
- Indexes and constraints
- Example data

## Dependencies

- **Flask**: Web framework
- **python-jose**: JWT verification (RS256)
- **python-dotenv**: Environment variable management
- **supabase**: Database client (PostgreSQL)

## Academic/Healthcare Context

This implementation is designed for:

- **Healthcare IoT Systems**: Secure patient data access
- **M2M Communication**: Machine-to-machine authentication
- **Academic Projects**: Clear architecture and documentation
- **Production Systems**: Production-grade error handling and security

## Compliance Notes

- **HIPAA Considerations**: Ensure proper encryption in transit and at rest
- **GDPR Considerations**: Minimal data exposure (only pivot ID returned)
- **Audit Trail**: Consider adding request logging for compliance

## Troubleshooting

### "authorization_header_missing"

Ensure the request includes `Authorization: Bearer <token>` header.

### "invalid_token"

- Verify JWT token is not expired
- Check `AUTH0_DOMAIN` and `AUTH0_AUDIENCE` match token issuer/audience
- Ensure token was issued for the correct API audience

### "patient_not_found"

- Verify correspondence table has entry for the Auth0 user ID
- Check `user_id_auth` in correspondence table matches JWT `sub` claim

### "database_not_configured"

- Ensure `SUPABASE_URL` and `SUPABASE_KEY` are set in `.env`
- Verify Supabase credentials are correct

## License

This implementation is provided for educational and production use in healthcare systems.
