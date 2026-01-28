import React, { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth0 } from '@auth0/auth0-react';
import { LogIn, AlertCircle } from 'lucide-react';
import vitalioLogo from '../assets/vitalio-logo.png';
import { ROLES_CLAIM } from '../utils/auth';

const AUDIENCE = import.meta.env.VITE_AUTH0_AUDIENCE || 'auth';
const DOCTOR_ROLE = 'Superuser';

export default function Login() {
    const navigate = useNavigate();
    const hasRedirectedRef = useRef(false);
    const {
        isAuthenticated,
        isLoading,
        loginWithRedirect,
        user,
        getIdTokenClaims,
        error: auth0Error,
    } = useAuth0();

    useEffect(() => {
        if (!isAuthenticated || !user || hasRedirectedRef.current) return;
        handleAuthenticatedUser();
    }, [isAuthenticated, user]);

    async function handleAuthenticatedUser() {
        try {
            const idClaims = await getIdTokenClaims();
            const roles = Array.isArray(idClaims?.[ROLES_CLAIM]) ? idClaims[ROLES_CLAIM] : [];
            const isDoctor = roles.includes(DOCTOR_ROLE);

            localStorage.setItem('vitalio_user', JSON.stringify({
                email: user.email,
                name: user.name || user.email,
                role: isDoctor ? 'doctor' : 'patient',
                picture: user.picture,
            }));

            doRedirect(isDoctor ? '/doctor' : '/patient');
        } catch (e) {
            console.error('[Login] Redirect error:', e);
            doRedirect('/patient');
        }
    }

    function doRedirect(route) {
        if (hasRedirectedRef.current) return;
        hasRedirectedRef.current = true;
        navigate(route, { replace: true });
    }

    const handleLogin = () => {
        loginWithRedirect({
            authorizationParams: {
                screen_hint: 'login',
                audience: AUDIENCE,
                scope: 'openid profile email',
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

    return (
        <div className="login-container">
            {/* Animated background elements */}
            <div className="login-bg-effects">
                <div className="bg-blob blob-1"></div>
                <div className="bg-blob blob-2"></div>
                <div className="bg-blob blob-3"></div>
                <div className="pulse-ring ring-1"></div>
                <div className="pulse-ring ring-2"></div>
            </div>

            <div className="login-card animate-fade-in">
                {/* Logo Section */}
                <div className="login-logo-section">
                    <img src={vitalioLogo} alt="VitalIO Logo" className="login-logo" />
                    <h1 className="login-title">VitalIO</h1>
                    <p className="login-subtitle">Plateforme de Télésurveillance Médicale</p>
                </div>

                {/* Login Form */}
                <div className="login-form">
                    {/* Error Message */}
                    {auth0Error && (
                        <div className="login-error animate-shake">
                            <AlertCircle size={18} />
                            <span>Erreur d'authentification: {auth0Error.message}</span>
                        </div>
                    )}

                    {/* Login Button */}
                    <button 
                        type="button"
                        onClick={handleLogin}
                        className="login-button"
                    >
                        <LogIn size={20} />
                        <span>Se connecter</span>
                    </button>

                    <p className="login-hint">
                        Vous serez redirigé vers la page de connexion pour vous authentifier.
                    </p>
                </div>
            </div>

            {/* Footer */}
            <footer className="login-footer">
                <p>© 2026 VitalIO - Télésurveillance Médicale IoT</p>
            </footer>
        </div>
    );
}
