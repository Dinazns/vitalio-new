import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Mail, Lock, Eye, EyeOff, LogIn, AlertCircle } from 'lucide-react';
import vitalioLogo from '../assets/vitalio-logo.png';

// Mock users database for demonstration
const MOCK_USERS = [
    { email: 'robert@patient.fr', password: 'patient123', role: 'patient', name: 'Robert' },
    { email: 'sophie@medecin.fr', password: 'medecin123', role: 'medecin', name: 'Dr. Sophie' },
    { email: 'julie@famille.fr', password: 'famille123', role: 'aidant', name: 'Julie' },
    { email: 'thomas@admin.fr', password: 'admin123', role: 'admin', name: 'Thomas' },
];

// Route mapping based on role
const ROLE_ROUTES = {
    patient: '/patient',
    medecin: '/doctor',
    aidant: '/family',
    admin: '/admin',
};

export default function Login() {
    const navigate = useNavigate();
    const [formData, setFormData] = useState({ email: '', password: '' });
    const [showPassword, setShowPassword] = useState(false);
    const [error, setError] = useState('');
    const [isLoading, setIsLoading] = useState(false);

    const handleChange = (e) => {
        const { name, value } = e.target;
        setFormData(prev => ({ ...prev, [name]: value }));
        if (error) setError('');
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        setIsLoading(true);
        setError('');

        // Simulate API call delay
        await new Promise(resolve => setTimeout(resolve, 800));

        const user = MOCK_USERS.find(
            u => u.email === formData.email && u.password === formData.password
        );

        if (user) {
            // Store user info in localStorage for session persistence
            localStorage.setItem('vitalio_user', JSON.stringify({
                email: user.email,
                name: user.name,
                role: user.role
            }));
            
            // Redirect based on role
            const route = ROLE_ROUTES[user.role];
            navigate(route);
        } else {
            setError('Email ou mot de passe incorrect');
        }

        setIsLoading(false);
    };

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
                <form onSubmit={handleSubmit} className="login-form">
                    {/* Email Field */}
                    <div className="input-group">
                        <label htmlFor="email" className="input-label">
                            <Mail size={18} />
                            <span>Email</span>
                        </label>
                        <div className="input-wrapper">
                            <input
                                type="email"
                                id="email"
                                name="email"
                                value={formData.email}
                                onChange={handleChange}
                                placeholder="votre@email.fr"
                                required
                                className="login-input"
                                autoComplete="email"
                            />
                        </div>
                    </div>

                    {/* Password Field */}
                    <div className="input-group">
                        <label htmlFor="password" className="input-label">
                            <Lock size={18} />
                            <span>Mot de passe</span>
                        </label>
                        <div className="input-wrapper">
                            <input
                                type={showPassword ? 'text' : 'password'}
                                id="password"
                                name="password"
                                value={formData.password}
                                onChange={handleChange}
                                placeholder="••••••••"
                                required
                                className="login-input"
                                autoComplete="current-password"
                            />
                            <button
                                type="button"
                                className="password-toggle"
                                onClick={() => setShowPassword(!showPassword)}
                                aria-label={showPassword ? 'Masquer le mot de passe' : 'Afficher le mot de passe'}
                            >
                                {showPassword ? <EyeOff size={20} /> : <Eye size={20} />}
                            </button>
                        </div>
                    </div>

                    {/* Error Message */}
                    {error && (
                        <div className="login-error animate-shake">
                            <AlertCircle size={18} />
                            <span>{error}</span>
                        </div>
                    )}

                    {/* Submit Button */}
                    <button 
                        type="submit" 
                        className={`login-button ${isLoading ? 'loading' : ''}`}
                        disabled={isLoading}
                    >
                        {isLoading ? (
                            <div className="button-loader"></div>
                        ) : (
                            <>
                                <LogIn size={20} />
                                <span>Se connecter</span>
                            </>
                        )}
                    </button>
                </form>

                {/* Demo Accounts Info */}
                <div className="demo-accounts">
                    <p className="demo-title">Comptes de démonstration :</p>
                    <div className="demo-grid">
                        <div className="demo-account">
                            <span className="demo-role patient">Patient</span>
                            <span className="demo-email">robert@patient.fr</span>
                        </div>
                        <div className="demo-account">
                            <span className="demo-role medecin">Médecin</span>
                            <span className="demo-email">sophie@medecin.fr</span>
                        </div>
                        <div className="demo-account">
                            <span className="demo-role aidant">Aidant</span>
                            <span className="demo-email">julie@famille.fr</span>
                        </div>
                        <div className="demo-account">
                            <span className="demo-role admin">Admin</span>
                            <span className="demo-email">thomas@admin.fr</span>
                        </div>
                    </div>
                    <p className="demo-hint">Mot de passe : [role]123</p>
                </div>
            </div>

            {/* Footer */}
            <footer className="login-footer">
                <p>© 2026 VitalIO - Télésurveillance Médicale IoT</p>
            </footer>
        </div>
    );
}
