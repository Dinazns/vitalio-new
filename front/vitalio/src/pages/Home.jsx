import React, { useEffect, useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth0 } from '@auth0/auth0-react';
import { User, Stethoscope, Heart, Settings } from 'lucide-react';

const ROLE_ROUTES = {
  patient: '/patient/bienvenue',
  user: '/patient/bienvenue',
  doctor: '/doctor',
  medecin: '/doctor',
  superuser: '/doctor',
  caregiver: '/caregiver',
  aidant: '/caregiver',
  admin: '/admin',
};

function normalizeRole(value) {
  const role = String(value || '').trim().toLowerCase();
  if (['superuser', 'medecin', 'médecin'].includes(role)) return 'doctor';
  if (['aidant', 'family'].includes(role)) return 'caregiver';
  if (role === 'user') return 'patient';
  return role;
}

const PersonaCard = ({ icon: Icon, title, name, description, color, path }) => {
    const navigate = useNavigate();

    return (
        <div
            onClick={() => navigate(path)}
            className="persona-card"
            style={{ borderTop: `4px solid ${color}` }}
        >
            <div className="icon-wrapper">
                <Icon size={32} color={color} />
            </div>
            <div>
                <h3>{title}</h3>
                <p className="persona-name">{name}</p>
            </div>
            <p className="persona-desc">{description}</p>
        </div>
    );
};

export default function Home() {
    const navigate = useNavigate();
    const { isAuthenticated, user, getAccessTokenSilently } = useAuth0();
    const [checkingRole, setCheckingRole] = useState(true);
    const hasFetchedRef = useRef(false);

    useEffect(() => {
        if (!isAuthenticated || !user) {
            setCheckingRole(false);
            return;
        }
        if (hasFetchedRef.current) {
            setCheckingRole(false);
            return;
        }
        hasFetchedRef.current = true;
        let mounted = true;
        (async () => {
            try {
                const token = await getAccessTokenSilently();
                const res = await fetch(`${import.meta.env.VITE_API_URL}/api/me/role`, {
                    headers: { Authorization: `Bearer ${token}` },
                });
                if (mounted && res.ok) {
                    const data = await res.json();
                    const roleForRouting = normalizeRole(data.role);
                    const target = ROLE_ROUTES[roleForRouting];
                    if (target) {
                        localStorage.setItem('vitalio_user', JSON.stringify({
                            email: user.email,
                            name: user.name || user.email,
                            role: data.role,
                            picture: user.picture,
                        }));
                        navigate(target, { replace: true });
                        return;
                    }
                }
            } catch {
                
            } finally {
                hasFetchedRef.current = false;
            }
            if (mounted) setCheckingRole(false);
        })();
        return () => { mounted = false; };
    }, [isAuthenticated, user?.sub, navigate]);

    if (checkingRole && isAuthenticated) {
        return (
            <div className="home-container" style={{ display: 'grid', placeItems: 'center', minHeight: '60vh' }}>
                <p>Chargement...</p>
            </div>
        );
    }

    return (
        <div className="home-container">
            <div className="hero-section animate-fade-in">
                <h1>
                    VitalIO
                </h1>
                <p className="subtitle">Simulateur de Télésurveillance Médicale</p>
                <p className="hint">Choisissez votre interface</p>
            </div>

            <div className="persona-grid">
                <PersonaCard
                    icon={User}
                    title="Patient"
                    name="Robert (78 ans)"
                    description="Interface simplifiée. Gros boutons. SOS."
                    color="#10b981"
                    path="/patient/bienvenue"
                />
                <PersonaCard
                    icon={Stethoscope}
                    title="Médecin"
                    name="Dr. Sophie"
                    description="Tableau de bord. Données vitales."
                    color="#1d4ed8"
                    path="/doctor"
                />
                <PersonaCard
                    icon={Heart}
                    title="Famille"
                    name="Julie"
                    description="Timeline, Alertes, Rassurant."
                    color="#8b5cf6"
                    path="/caregiver"
                />
                <PersonaCard
                    icon={Settings}
                    title="Admin"
                    name="Thomas"
                    description="Maintenance des capteurs IoT."
                    color="#475569"
                    path="/admin"
                />
            </div>
        </div>
    );
}
