# Auth0 Integration Setup Guide

This guide explains how to configure Auth0 authentication for the VitalIO frontend application.

## Prerequisites

- Auth0 account and tenant
- Auth0 Application (Single Page Application type)
- Auth0 API configured with proper audience

## Environment Variables

Create a `.env` file in the `front/vitalio` directory with the following variables:

```env
# Auth0 Configuration
VITE_AUTH0_DOMAIN=your-tenant.auth0.com
VITE_AUTH0_CLIENT_ID=your-client-id
VITE_AUTH0_AUDIENCE=https://your-api-identifier

# API Configuration
VITE_API_URL=http://localhost:5000
```

## Auth0 Configuration Steps

### 1. Create Auth0 Application

1. Go to Auth0 Dashboard → Applications → Applications
2. Click "Create Application"
3. Select "Single Page Web Applications"
4. Configure the following:
   - **Allowed Callback URLs**: `http://localhost:5173, http://localhost:3000`
   - **Allowed Logout URLs**: `http://localhost:5173, http://localhost:3000`
   - **Allowed Web Origins**: `http://localhost:5173, http://localhost:3000`

### 2. Configure Auth0 API

1. Go to Auth0 Dashboard → Applications → APIs
2. Create or select your API
3. Note the **Identifier** (this is your `AUTH0_AUDIENCE`)
4. Enable **RS256** signing algorithm

### 3. User Metadata (Optional)

To support role-based routing, you can add user roles in Auth0:

1. Go to Auth0 Dashboard → User Management → Users
2. Select a user → Metadata tab
3. Add `role` to either:
   - **app_metadata**: `{ "role": "patient" }` (for admin-set roles)
   - **user_metadata**: `{ "role": "patient" }` (for user-editable roles)
   - Or use a custom claim: `https://vitalio.app/role`

Available roles:
- `patient` → `/patient`
- `medecin` → `/doctor`
- `aidant` → `/family`
- `admin` → `/admin`

## Backend Configuration

Ensure your backend API (`api.py`) has the following environment variables:

```env
AUTH0_DOMAIN=your-tenant.auth0.com
AUTH0_AUDIENCE=https://your-api-identifier
```

## Testing the Integration

1. Start the frontend: `npm run dev`
2. Navigate to the login page
3. Click "Se connecter avec Auth0"
4. You'll be redirected to Auth0 login page
5. After successful login, you'll be redirected back to the app
6. The app will automatically route you based on your role

## API Usage

The frontend uses the `api.js` service to make authenticated requests:

```javascript
import { getPatientData } from '../services/api';
import { useAuth0 } from '@auth0/auth0-react';

function MyComponent() {
  const { getAccessTokenSilently } = useAuth0();
  
  useEffect(() => {
    const fetchData = async () => {
      const token = await getAccessTokenSilently();
      const data = await getPatientData(token);
      // Use data...
    };
    fetchData();
  }, []);
}
```

## Troubleshooting

### "Auth0 configuration missing" error
- Ensure `.env` file exists in `front/vitalio` directory
- Check that all required environment variables are set
- Restart the dev server after adding/changing `.env` variables

### "Invalid token" or 401 errors
- Verify `AUTH0_AUDIENCE` matches your Auth0 API identifier
- Check that the API is configured to accept tokens from your Auth0 application
- Ensure CORS is properly configured in `api.py`

### User not redirecting after login
- Check that callback URLs are configured in Auth0
- Verify the role is set in user metadata
- Check browser console for errors
