import React, { useEffect, useRef, useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth0 } from '@auth0/auth0-react';
import { LogIn, UserPlus, AlertCircle, CheckCircle2 } from 'lucide-react';
import vitalioLogo from '../assets/vitalio-logo.png';
import { acceptTerms, getTermsStatus } from '../services/api';
import { isAuthProviderId } from '../utils/displayName';

const SIGNUP_TERMS_KEY = 'vitalio_signup_terms';

const ROLE_ROUTES = {
    patient: '/patient/bienvenue',
    doctor: '/doctor',
    medecin: '/doctor',
    'médecin': '/doctor',
    superuser: '/doctor',
    user: '/patient/bienvenue',
    caregiver: '/caregiver',
    aidant: '/caregiver',
    admin: '/admin',
};

const SIGNUP_QUESTIONNAIRE_PATH = '/patient/profile#questionnaire-patient';

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

function isEmailLike(value) {
    if (!value) return false;
    return String(value).includes('@');
}

function isSafePersonName(value) {
    if (!value || isEmailLike(value) || isAuthProviderId(value)) return false;
    return true;
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
    const [acceptedTerms, setAcceptedTerms] = useState(false);
    const [pendingTermsGate, setPendingTermsGate] = useState(false);
    const [termsGateReason, setTermsGateReason] = useState('');
    const [isSubmittingTerms, setIsSubmittingTerms] = useState(false);
    const [termsError, setTermsError] = useState('');
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

    async function syncProfile(token) {
        const profilePayload = {};
        if (user.given_name && isSafePersonName(user.given_name)) {
            profilePayload.first_name = user.given_name;
        }
        if (user.family_name && isSafePersonName(user.family_name)) {
            profilePayload.last_name = user.family_name;
        }
        if ((!profilePayload.first_name || !profilePayload.last_name) && user.name && isSafePersonName(user.name)) {
            const parts = String(user.name).trim().split(/\s+/);
            if (parts.length >= 2 && !profilePayload.first_name) profilePayload.first_name = parts[0];
            if (parts.length >= 2 && !profilePayload.last_name) profilePayload.last_name = parts.slice(1).join(' ');
        }
        if (user.name && isSafePersonName(user.name)) profilePayload.display_name = user.name;
        if (user.email) profilePayload.email = user.email;
        if (user.picture) profilePayload.picture = user.picture;

        if (!profilePayload.email && Object.keys(profilePayload).length === 0) return;

        await fetch(`${import.meta.env.VITE_API_URL}/api/me/profile`, {
            method: 'PATCH',
            headers: {
                Authorization: `Bearer ${token}`,
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(profilePayload),
        });
    }

    async function resolveRoleForRouting(token) {
        try {
            const res = await fetch(`${import.meta.env.VITE_API_URL}/api/me/role`, {
                headers: { Authorization: `Bearer ${token}` },
            });
            if (res.ok) {
                const data = await res.json();
                return normalizeRole(data.role) || 'patient';
            }
        } catch {
            /* fall through */
        }
        return extractRole(user);
    }

    async function completeRedirect(token) {
        let roleForRouting = 'patient';
        let roleForDisplay = 'Patient';
        try {
            const res = await fetch(`${import.meta.env.VITE_API_URL}/api/me/role`, {
                headers: { Authorization: `Bearer ${token}` },
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

        navigate(ROLE_ROUTES[roleForRouting] || '/patient/bienvenue');
    }

    async function handleAuthenticatedUser() {
        try {
            const token = await getAccessTokenSilently();

            try {
                await syncProfile(token);
            } catch (e) {
                console.warn('Profile sync failed (non-blocking):', e);
            }

            const signupTermsPending = sessionStorage.getItem(SIGNUP_TERMS_KEY) === '1';
            sessionStorage.removeItem(SIGNUP_TERMS_KEY);

            if (signupTermsPending) {
                await acceptTerms(token);
                const roleForRouting = await resolveRoleForRouting(token);
                if (roleForRouting === 'patient') {
                    localStorage.setItem('vitalio_user', JSON.stringify({
                        email: user.email,
                        name: user.name || user.email,
                        role: 'Patient',
                        picture: user.picture,
                    }));
                    navigate(SIGNUP_QUESTIONNAIRE_PATH);
                    return;
                }
                await completeRedirect(token);
                return;
            }

            const termsStatus = await getTermsStatus(token);
            if (termsStatus.needs_acceptance) {
                setTermsGateReason(
                    termsStatus.terms_accepted_at
                        ? 'Les conditions d\'utilisation ont été mises à jour. Veuillez les accepter pour continuer.'
                        : 'Veuillez accepter les conditions d\'utilisation pour utiliser VitalIO.'
                );
                setPendingTermsGate(true);
                return;
            }

            await completeRedirect(token);
        } catch (error) {
            console.error('Error handling authenticated user:', error);
            hasRedirectedRef.current = false;
        }
    }

    async function handleAcceptTermsAndContinue() {
        if (!acceptedTerms || isSubmittingTerms) return;
        setIsSubmittingTerms(true);
        setTermsError('');
        try {
            const token = await getAccessTokenSilently();
            await acceptTerms(token);
            setPendingTermsGate(false);
            await completeRedirect(token);
        } catch (error) {
            console.error('Terms acceptance failed:', error);
            setTermsError(error.message || 'Impossible d\'enregistrer votre acceptation.');
        } finally {
            setIsSubmittingTerms(false);
        }
    }

    const handleLogin = () => {
        sessionStorage.removeItem(SIGNUP_TERMS_KEY);
        loginWithRedirect({
            authorizationParams: {
                screen_hint: 'login',
            },
        });
    };

    const handleSignup = () => {
        if (!acceptedTerms) return;
        sessionStorage.setItem(SIGNUP_TERMS_KEY, '1');
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

    if (isAuthenticated && user?.sub && pendingTermsGate) {
        return (
            <div className="login-container">
                <div className="login-bg-effects">
                    <div className="bg-blob blob-1"></div>
                    <div className="bg-blob blob-2"></div>
                    <div className="bg-blob blob-3"></div>
                    <div className="pulse-ring ring-1"></div>
                    <div className="pulse-ring ring-2"></div>
                </div>

                <div className="login-card animate-fade-in">
                    <div className="login-logo-section">
                        <img src={vitalioLogo} alt="VitalIO Logo" className="login-logo" />
                        <p className="login-subtitle">Conditions d&apos;utilisation</p>
                    </div>

                    <div className="login-form">
                        <p className="login-hint">{termsGateReason}</p>

                        {termsError && (
                            <div className="login-error animate-shake">
                                <AlertCircle size={18} />
                                <span>{termsError}</span>
                            </div>
                        )}

                        <label className="login-terms">
                            <input
                                type="checkbox"
                                checked={acceptedTerms}
                                onChange={(e) => setAcceptedTerms(e.target.checked)}
                                aria-describedby="terms-gate-hint"
                            />
                            <span className="login-terms__label" id="terms-gate-hint">
                                J&apos;accepte les{' '}
                                <Link to="/conditions-utilisation" className="login-terms__link">
                                    conditions d&apos;utilisation
                                </Link>
                                {' '}pour utiliser VitalIO.
                            </span>
                        </label>

                        <button
                            type="button"
                            onClick={handleAcceptTermsAndContinue}
                            className="login-button"
                            disabled={!acceptedTerms || isSubmittingTerms}
                        >
                            <CheckCircle2 size={20} />
                            <span>{isSubmittingTerms ? 'Enregistrement...' : 'Accepter et continuer'}</span>
                        </button>
                    </div>
                </div>

                <footer className="login-footer">
                    <p>© 2026 VitalIO - Télésurveillance Médicale IoT</p>
                </footer>
            </div>
        );
    }

    if (isAuthenticated && user?.sub) {
        return (
            <div className="login-container">
                <div className="login-card animate-fade-in">
                    <div className="login-logo-section">
                        <img src={vitalioLogo} alt="VitalIO Logo" className="login-logo" />
                        <p className="login-subtitle">Connexion en cours...</p>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="login-container">
            <div className="login-bg-effects">
                <div className="bg-blob blob-1"></div>
                <div className="bg-blob blob-2"></div>
                <div className="bg-blob blob-3"></div>
                <div className="pulse-ring ring-1"></div>
                <div className="pulse-ring ring-2"></div>
            </div>

            <div className="login-card animate-fade-in">
                <div className="login-logo-section">
                    <img src={vitalioLogo} alt="VitalIO Logo" className="login-logo" />
                    <p className="login-subtitle">Plateforme de Télésurveillance Médicale</p>
                </div>

                <div className="login-form">
                    {auth0Error && (
                        <div className="login-error animate-shake">
                            <AlertCircle size={18} />
                            <span>Erreur d&apos;authentification: {auth0Error.message}</span>
                        </div>
                    )}

                    <label className="login-terms">
                        <input
                            type="checkbox"
                            checked={acceptedTerms}
                            onChange={(e) => setAcceptedTerms(e.target.checked)}
                            aria-describedby="login-terms-hint"
                        />
                        <span className="login-terms__label" id="login-terms-hint">
                            J&apos;accepte les{' '}
                            <Link to="/conditions-utilisation" className="login-terms__link">
                                conditions d&apos;utilisation
                            </Link>
                            {' '}pour créer un compte VitalIO.
                        </span>
                    </label>

                    <button
                        type="button"
                        onClick={handleSignup}
                        className="login-button"
                        disabled={!acceptedTerms}
                    >
                        <UserPlus size={20} />
                        <span>S&apos;inscrire</span>
                    </button>

                    <button
                        type="button"
                        onClick={handleLogin}
                        className="login-button login-button-secondary"
                    >
                        <LogIn size={20} />
                        <span>Déjà un compte ? Se connecter</span>
                    </button>

                    <p className="login-hint">
                        La case ci-dessus est requise pour l&apos;inscription. La connexion ne la demande pas si vous avez déjà accepté les conditions.
                    </p>
                </div>

                <div className="demo-accounts">
                    <p className="demo-title">Authentification sécurisée</p>
                    <p className="demo-hint">
                        Cette application utilise Auth0 pour une authentification sécurisée.
                        Connectez-vous avec vos identifiants Auth0 pour accéder à la plateforme.
                    </p>
                </div>
            </div>

            <footer className="login-footer">
                <p>© 2026 VitalIO - Télésurveillance Médicale IoT</p>
            </footer>
        </div>
    );
}
