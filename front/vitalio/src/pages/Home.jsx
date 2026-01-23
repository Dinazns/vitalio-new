import React from 'react';
import { useNavigate } from 'react-router-dom';
import { User, Stethoscope, Heart, Settings } from 'lucide-react';

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
                    path="/patient"
                />
                <PersonaCard
                    icon={Stethoscope}
                    title="Médecin"
                    name="Dr. Sophie"
                    description="Tableau de bord. Données vitales."
                    color="#3b82f6"
                    path="/doctor"
                />
                <PersonaCard
                    icon={Heart}
                    title="Famille"
                    name="Julie"
                    description="Timeline, Alertes, Rassurant."
                    color="#8b5cf6"
                    path="/family"
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
