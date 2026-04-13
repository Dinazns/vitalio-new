import React, { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth0 } from '@auth0/auth0-react';
import { LogIn, UserPlus, AlertCircle } from 'lucide-react';
import vitalioLogo from '../assets/vitalio-logo.png';

const ROLE_ROUTES = {
    patient: '/patient',
    doctor: '/doctor',
    medecin: '/doctor',
    'médecin': '/doctor',
    superuser: '/doctor',
    user: '/patient',
    caregiver: '/caregiver',
    aidant: '/caregiver',
    admin: '/admin',
};

function normalizeRole(value) {
    const role = String(value || '').trim().toLowerCase();
    if (role === 'superuser' || role === 'medecin' || role === 'médecin') return 'doctor';
    if (role === 'aidant' || role === 'family') return 'caregiver';
    if (role === 'user') return 'patient';
    return role;
}

function pickRoleFromCandidate(candidate) {
    if (Array.isArray(candidate)) {
        for (const rawRole of candidate) {
            const normalized = normalizeRole(rawRole);
            if (ROLE_ROUTES[normalized]) return normalized;
        }
        return '';
    }
    return normalizeRole(candidate);
}

function extractRole(user) {
    const candidates = [
        user?.['https://vitalio.app/role'],
        user?.['https://vitalio.app/roles'],
        user?.app_metadata?.role,
        user?.app_metadata?.roles,
        user?.app_metadata?.authorization?.roles,
        user?.user_metadata?.role,
        user?.user_metadata?.roles,
        user?.role,
        user?.roles,
    ];

    for (const candidate of candidates) {
        const picked = pickRoleFromCandidate(candidate);
        if (picked && ROLE_ROUTES[picked]) return picked;
    }
    return 'patient';
}

export default function Login() {
    const navigate = useNavigate();
    const hasRedirectedRef = useRef(false);
    const {
        isAuthenticated,
        isLoading,
        loginWithRedirect,
        user,
        getAccessTokenSilently,
        error: auth0Error,
    } = useAuth0();

    
    useEffect(() => {
        if (!isAuthenticated || !user?.sub || hasRedirectedRef.current) return;
        hasRedirectedRef.current = true;
        handleAuthenticatedUser();
    }, [isAuthenticated, user?.sub]);

    async function handleAuthenticatedUser() {
        try {
            const token = await getAccessTokenSilently();

            
            try {
                const profilePayload = {};
                if (user.given_name)  profilePayload.first_name   = user.given_name;
                if (user.family_name) profilePayload.last_name    = user.family_name;
                // Si Auth0 ne fournit que name, le découper pour first_name/last_name (display_name = first + last)
                if ((!profilePayload.first_name || !profilePayload.last_name) && user.name) {
                    const parts = String(user.name).trim().split(/\s+/);
                    if (parts.length >= 2 && !profilePayload.first_name) profilePayload.first_name = parts[0];
                    if (parts.length >= 2 && !profilePayload.last_name)  profilePayload.last_name  = parts.slice(1).join(' ');
                }
                if (user.name)        profilePayload.display_name = user.name;
                if (user.email)       profilePayload.email        = user.email;
                if (user.picture)     profilePayload.picture      = user.picture;
                if (Object.keys(profilePayload).length === 0 && user.email) {
                    profilePayload.email = user.email;
                    profilePayload.display_name = user.email;
                }

                if (Object.keys(profilePayload).length > 0) {
                    await fetch(`${import.meta.env.VITE_API_URL}/api/me/profile`, {
                        method: 'PATCH',
                        headers: {
                            'Authorization': `Bearer ${token}`,
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify(profilePayload),
                    });
                }
            } catch (e) {
                console.warn('Profile sync failed (non-blocking):', e);
            }

            
            let roleForRouting = 'patient';
            let roleForDisplay = 'Patient';
            try {
                const res = await fetch(`${import.meta.env.VITE_API_URL}/api/me/role`, {
                    headers: { 'Authorization': `Bearer ${token}` },
                });
                if (res.ok) {
                    const data = await res.json();
                    roleForDisplay = data.role || 'Patient';
                    roleForRouting = normalizeRole(roleForDisplay) || 'patient';
                } else {
                    roleForRouting = extractRole(user);
                    roleForDisplay = roleForRouting === 'doctor' ? 'Médecin' : roleForRouting;
                }
            } catch {
                roleForRouting = extractRole(user);
                roleForDisplay = roleForRouting === 'doctor' ? 'Médecin' : roleForRouting;
            }

            localStorage.setItem('vitalio_user', JSON.stringify({
                email: user.email,
                name: user.name || user.email,
                role: roleForDisplay,
                picture: user.picture,
            }));

            navigate(ROLE_ROUTES[roleForRouting] || '/patient');
        } catch (error) {
            console.error('Error handling authenticated user:', error);
            hasRedirectedRef.current = false;
        }
    };

    const handleLogin = () => {
        loginWithRedirect({
            authorizationParams: {
                screen_hint: 'login',
            },
        });
    };

    const handleSignup = () => {
        loginWithRedirect({
            authorizationParams: {
                screen_hint: 'signup',
            },
        });
    };

    if (isLoading) {
        return (
            <div className="login-container">
                <div className="login-card animate-fade-in">
                    <div className="login-logo-section">
                        <img src={vitalioLogo} alt="VitalIO Logo" className="login-logo" />
                        <h1 className="login-title">VitalIO</h1>
                        <p className="login-subtitle">Chargement...</p>
                    </div>
                </div>
            </div>
        );
    }

    if (isAuthenticated && user?.sub) {
        return (
            <div className="login-container">
                <div className="login-card animate-fade-in">
                    <div className="login-logo-section">
                        <img src={vitalioLogo} alt="VitalIO Logo" className="login-logo" />
                        <h1 className="login-title">VitalIO</h1>
                        <p className="login-subtitle">Connexion en cours...</p>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="login-container">
            {}
            <div className="login-bg-effects">
                <div className="bg-blob blob-1"></div>
                <div className="bg-blob blob-2"></div>
                <div className="bg-blob blob-3"></div>
                <div className="pulse-ring ring-1"></div>
                <div className="pulse-ring ring-2"></div>
            </div>

            <div className="login-card animate-fade-in">
                {}
                <div className="login-logo-section">
                    <img src={vitalioLogo} alt="VitalIO Logo" className="login-logo" />
                    <h1 className="login-title">VitalIO</h1>
                    <p className="login-subtitle">Plateforme de Télésurveillance Médicale</p>
                </div>

                {}
                <div className="login-form">
                    {}
                    {auth0Error && (
                        <div className="login-error animate-shake">
                            <AlertCircle size={18} />
                            <span>Erreur d'authentification: {auth0Error.message}</span>
                        </div>
                    )}

                    {/* Signup Button (primary) */}
                    <button 
                        type="button"
                        onClick={handleSignup}
                        className="login-button"
                    >
                        <UserPlus size={20} />
                        <span>S'inscrire</span>
                    </button>

                    {}
                    <button 
                        type="button"
                        onClick={handleLogin}
                        className="login-button login-button-secondary"
                    >
                        <LogIn size={20} />
                        <span>Déjà un compte ? Se connecter</span>
                    </button>

                    <p className="login-hint">
                        Créez un compte ou connectez-vous avec Auth0 pour accéder à VitalIO.
                    </p>
                </div>

                {}
                <div className="demo-accounts">
                    <p className="demo-title">Authentification sécurisée</p>
                    <p className="demo-hint">
                        Cette application utilise Auth0 pour une authentification sécurisée.
                        Connectez-vous avec vos identifiants Auth0 pour accéder à la plateforme.
                    </p>
                </div>
            </div>

            {}
            <footer className="login-footer">
                <p>© 2026 VitalIO - Télésurveillance Médicale IoT</p>
            </footer>
        </div>
    );
}
