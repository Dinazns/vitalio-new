import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth0 } from '@auth0/auth0-react';
import {
    Users, Activity, Bell, Settings, LogOut,
    Search, ChevronRight, UserPlus
} from 'lucide-react';
import { createDoctorRequest, getMyDoctorRequests, getDoctorPatientsMeasurements } from '../services/api';

const AUDIENCE = import.meta.env.VITE_AUTH0_AUDIENCE || 'auth';

const SidebarItem = ({ icon: Icon, label, active }) => (
    <div className={`sidebar-item ${active ? 'active' : ''}`}>
        <Icon size={20} />
        <span>{label}</span>
    </div>
);

const StatCard = ({ title, value, trend, good }) => (
    <div className="stat-card">
        <p className="title">{title}</p>
        <div className="content-row">
            <span className="value">{value}</span>
            <span className={`trend ${good ? 'good' : 'bad'}`}>
                {trend}
            </span>
        </div>
    </div>
);

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

// Statut médical pour une mesure: normal (vert), warning (orange), critical (rouge)
function getMeasurementStatus(m) {
    let hasCritical = false;
    let hasWarning = false;
    if (m.heart_rate != null) {
        const hr = m.heart_rate;
        if (hr < 50 || hr > 120) hasCritical = true;
        else if (hr < 60 || hr > 100) hasWarning = true;
    }
    if (m.temperature != null) {
        const t = Number(m.temperature);
        if (t < 35.5 || t > 38.0) hasCritical = true;
        else if (t < 36.1 || t > 37.2) hasWarning = true;
    }
    if (m.spo2 != null) {
        if (m.spo2 < 90) hasCritical = true;
        else if (m.spo2 < 95) hasWarning = true;
    }
    if (hasCritical) return 'critical';
    if (hasWarning) return 'warning';
    return 'normal';
}

export default function DoctorView() {
    const navigate = useNavigate();
    const { logout, getAccessTokenSilently, loginWithRedirect } = useAuth0();
    const [patientEmail, setPatientEmail] = useState('');
    const [associateMessage, setAssociateMessage] = useState(null);
    const [associateError, setAssociateError] = useState(null);
    const [associateLoading, setAssociateLoading] = useState(false);
    const [doctorRequests, setDoctorRequests] = useState([]);
    const [requestsLoading, setRequestsLoading] = useState(true);
    const [requestsError, setRequestsError] = useState(null);
    const [patientsMeasurements, setPatientsMeasurements] = useState([]);
    const [measurementsLoading, setMeasurementsLoading] = useState(true);
    const [measurementsError, setMeasurementsError] = useState(null);
    const [selectedPatientEmail, setSelectedPatientEmail] = useState('');
    const measurementsSectionRef = useRef(null);

    const handleSelectPatient = (email) => {
        setSelectedPatientEmail(email);
        measurementsSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };

    useEffect(() => {
        let cancelled = false;

        async function loadDoctorRequests() {
            setRequestsLoading(true);
            setRequestsError(null);
            try {
                let token;
                try {
                    token = await getAccessTokenSilently({
                        authorizationParams: {
                            audience: AUDIENCE,
                            scope: 'openid profile email read:patient_data',
                        },
                    });
                } catch (e) {
                    if (e?.error === 'consent_required' || e?.error === 'login_required' || e?.error === 'interaction_required') {
                        await loginWithRedirect({
                            authorizationParams: {
                                audience: AUDIENCE,
                                scope: 'openid profile email read:patient_data',
                            },
                            appState: { returnTo: '/doctor' },
                        });
                        return;
                    }
                    throw e;
                }

                const data = await getMyDoctorRequests(token);
                if (!cancelled) {
                    setDoctorRequests(data.requests || []);
                }
            } catch (err) {
                if (!cancelled) {
                    setRequestsError(err.message || 'Erreur lors du chargement des patients.');
                }
            } finally {
                if (!cancelled) {
                    setRequestsLoading(false);
                }
            }
        }

        loadDoctorRequests();
        return () => {
            cancelled = true;
        };
    }, [getAccessTokenSilently, loginWithRedirect]);

    useEffect(() => {
        let cancelled = false;

        async function loadPatientsMeasurements() {
            setMeasurementsLoading(true);
            setMeasurementsError(null);
            try {
                let token;
                try {
                    token = await getAccessTokenSilently({
                        authorizationParams: {
                            audience: AUDIENCE,
                            scope: 'openid profile email read:patient_data',
                        },
                    });
                } catch (e) {
                    if (e?.error === 'consent_required' || e?.error === 'login_required' || e?.error === 'interaction_required') {
                        await loginWithRedirect({
                            authorizationParams: {
                                audience: AUDIENCE,
                                scope: 'openid profile email read:patient_data',
                            },
                            appState: { returnTo: '/doctor' },
                        });
                        return;
                    }
                    throw e;
                }

                const data = await getDoctorPatientsMeasurements(token);
                if (!cancelled) {
                    const patients = data.patients || [];
                    setPatientsMeasurements(patients);
                    if (patients.length > 0) {
                        setSelectedPatientEmail((prev) => prev || patients[0].patient_email);
                    }
                }
            } catch (err) {
                if (!cancelled) {
                    setMeasurementsError(err.message || 'Erreur lors du chargement des mesures.');
                }
            } finally {
                if (!cancelled) {
                    setMeasurementsLoading(false);
                }
            }
        }

        loadPatientsMeasurements();
        return () => {
            cancelled = true;
        };
    }, [getAccessTokenSilently, loginWithRedirect]);

    const totalAssociated = doctorRequests.filter(r => r.status === 'approved').length;
    const totalPending = doctorRequests.filter(r => r.status === 'pending').length;

    const handleAssociatePatient = async (e) => {
        e.preventDefault();
        const email = patientEmail.trim().toLowerCase();
        setAssociateError(null);
        setAssociateMessage(null);

        if (!email) {
            setAssociateError('Veuillez saisir l\'email du patient.');
            return;
        }
        if (!EMAIL_REGEX.test(email)) {
            setAssociateError('Format d\'email invalide.');
            return;
        }

        setAssociateLoading(true);
        try {
            let token;
            try {
                token = await getAccessTokenSilently({
                    authorizationParams: {
                        audience: AUDIENCE,
                        scope: 'openid profile email read:patient_data',
                    },
                });
            } catch (e) {
                // Cas Auth0: consentement ou interaction requis → rediriger vers Auth0 (flow interactif)
                if (e?.error === 'consent_required' || e?.error === 'login_required' || e?.error === 'interaction_required') {
                    await loginWithRedirect({
                        authorizationParams: {
                            audience: AUDIENCE,
                            scope: 'openid profile email read:patient_data',
                        },
                        appState: { returnTo: '/doctor' },
                    });
                    return;
                }
                throw e;
            }

            const result = await createDoctorRequest(token, email);
            setPatientEmail('');
            setAssociateMessage(result.message || 'Demande d\'association envoyée. Elle sera traitée par l\'administrateur.');
        } catch (err) {
            setAssociateError(err.message || 'Erreur lors de la création de la demande.');
        } finally {
            setAssociateLoading(false);
        }
    };

    const handleLogout = () => {
        localStorage.removeItem('vitalio_user');
        logout({ logoutParams: { returnTo: window.location.origin } });
    };

    return (
        <div className="doctor-container doctor-theme">

            {/* Sidebar */}
            <div className="sidebar">
                <div>
                    <div className="logo-area" onClick={() => navigate('/')}>
                        <div className="logo-icon">V</div>
                        <span className="logo-text">VitalIO<span>Pro</span></span>
                    </div>

                    <div className="nav-menu">
                        <SidebarItem icon={Users} label="Mes Patients" active />
                        <SidebarItem icon={Activity} label="Monitoring" />
                        <SidebarItem icon={Bell} label="Alertes" />
                        <SidebarItem icon={Settings} label="Paramètres" />
                    </div>
                </div>

                <div className="user-profile">
                    <button type="button" className="logout-btn" onClick={handleLogout} aria-label="Déconnexion">
                        <LogOut size={16} />
                    </button>
                </div>
            </div>

            {/* Main Content */}
            <div className="main-content">

                {/* Topbar */}
                <header>
                    <h2>Tableau de Bord</h2>
                    <div className="header-actions">
                        <div className="search-bar">
                            <Search className="icon" size={16} />
                            <input
                                type="text"
                                placeholder="Rechercher patient..."
                            />
                        </div>
                        <button className="bell-btn">
                            <Bell size={20} />
                            <span className="badge"></span>
                        </button>
                    </div>
                </header>

                {/* Scrollable Content */}
                <main>

                    {/* Stats Bar */}
                    <div className="stats-bar">
                        <StatCard
                            title="Patients associés"
                            value={requestsLoading ? '...' : totalAssociated}
                            trend=""
                            good={true}
                        />
                        <StatCard
                            title="Demandes en attente"
                            value={requestsLoading ? '...' : totalPending}
                            trend=""
                            good={totalPending === 0}
                        />
                    </div>

                    {/* Demande d'association Médecin → Patient */}
                    <div className="associate-patient-card">
                        <div className="section-header">
                            <div className="section-icon" aria-hidden>
                                <UserPlus size={18} />
                            </div>
                            <h3>Demande d'association patient</h3>
                        </div>
                        <p className="associate-description">
                            Saisissez l'adresse email du patient pour lui envoyer une demande d'association. Il devra accepter la demande depuis son espace patient.
                        </p>
                        <form onSubmit={handleAssociatePatient} className="associate-form">
                            <div className="input-group">
                                <label htmlFor="patient-email">Email du patient</label>
                                <div className="input-wrapper">
                                    <span className="input-icon" aria-hidden>
                                        <Search size={18} />
                                    </span>
                                    <input
                                        id="patient-email"
                                        type="email"
                                        placeholder="ex: patient@exemple.fr"
                                        value={patientEmail}
                                        onChange={(e) => setPatientEmail(e.target.value)}
                                        disabled={associateLoading}
                                    />
                                </div>
                            </div>
                            <button
                                type="submit"
                                className="associate-submit"
                                disabled={associateLoading}
                            >
                                <UserPlus size={18} />
                                {associateLoading ? 'Envoi en cours...' : 'Associer le patient'}
                            </button>
                        </form>
                        {associateError && (
                            <p className="associate-feedback error" role="alert">
                                {associateError}
                            </p>
                        )}
                        {associateMessage && (
                            <p className="associate-feedback success" role="status">
                                {associateMessage}
                            </p>
                        )}
                    </div>

                    <div className="dashboard-grid">

                        {/* Patient Table */}
                        <div className="patient-table-section">
                            <div className="section-header">
                                <h3>Mes patients et demandes</h3>
                                <button type="button">Voir tout <ChevronRight size={16} /></button>
                            </div>
                            <div className="overflow-x-auto">
                                <table>
                                    <thead>
                                        <tr>
                                            <th className="pl-2">Patient</th>
                                            <th className="text-center">Statut</th>
                                            <th className="text-center">Email</th>
                                            <th>Date de création</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {requestsLoading && (
                                            <tr>
                                                <td colSpan={4} className="pl-2 py-3 text-slate-500">
                                                    Chargement des patients...
                                                </td>
                                            </tr>
                                        )}
                                        {requestsError && !requestsLoading && (
                                            <tr>
                                                <td colSpan={4} className="pl-2 py-3 text-red-600">
                                                    {requestsError}
                                                </td>
                                            </tr>
                                        )}
                                        {!requestsLoading && !requestsError && doctorRequests.length === 0 && (
                                            <tr>
                                                <td colSpan={4} className="pl-2 py-3 text-slate-500">
                                                    Aucun patient associé et aucune demande pour le moment.
                                                </td>
                                            </tr>
                                        )}
                                        {!requestsLoading && !requestsError && doctorRequests.map((req) => {
                                            const isApproved = req.status === 'approved';
                                            return (
                                                <tr
                                                    key={req.id}
                                                    role={isApproved ? 'button' : undefined}
                                                    tabIndex={isApproved ? 0 : undefined}
                                                    className={isApproved ? 'patient-row-clickable' : ''}
                                                    onClick={isApproved ? () => handleSelectPatient(req.patient_email) : undefined}
                                                    onKeyDown={isApproved ? (e) => {
                                                        if (e.key === 'Enter' || e.key === ' ') {
                                                            e.preventDefault();
                                                            handleSelectPatient(req.patient_email);
                                                        }
                                                    } : undefined}
                                                >
                                                    <td className="pl-2 font-bold text-slate-700">
                                                        {req.patient_email}
                                                        {isApproved && (
                                                            <ChevronRight size={16} className="inline-block ml-1 opacity-70" style={{ verticalAlign: 'middle' }} aria-hidden />
                                                        )}
                                                    </td>
                                                    <td className="text-center">
                                                        <span className="status-wrapper">
                                                            <span className={`dot ${
                                                                req.status === 'approved'
                                                                    ? 'green'
                                                                    : req.status === 'pending'
                                                                    ? 'yellow'
                                                                    : 'red'
                                                            }`}></span>
                                                            {req.status}
                                                        </span>
                                                    </td>
                                                    <td className="text-center font-mono">
                                                        {req.patient_email}
                                                    </td>
                                                    <td>
                                                        {req.created_at
                                                            ? new Date(req.created_at).toLocaleString('fr-FR', {
                                                                dateStyle: 'short',
                                                                timeStyle: 'short',
                                                            })
                                                            : '—'}
                                                    </td>
                                                </tr>
                                            );
                                        })}
                                    </tbody>
                                </table>
                            </div>
                        </div>

                        {/* Mesures des patients associés */}
                        <div ref={measurementsSectionRef} className="patient-table-section">
                            <div className="section-header">
                                <h3>Mesures du patient{selectedPatientEmail ? ` - ${selectedPatientEmail}` : ''}</h3>
                            </div>
                            {measurementsLoading && (
                                <p className="text-slate-500 py-2">Chargement des mesures...</p>
                            )}
                            {measurementsError && !measurementsLoading && (
                                <p className="text-red-600 py-2">{measurementsError}</p>
                            )}
                            {!measurementsLoading && !measurementsError && patientsMeasurements.length === 0 && (
                                <p className="text-slate-500 py-2">Aucune mesure disponible pour vos patients associés.</p>
                            )}
                            {!measurementsLoading && !measurementsError && patientsMeasurements.length > 0 && (
                                <>
                                    {selectedPatientEmail && (() => {
                                        const current = patientsMeasurements.find((p) => p.patient_email === selectedPatientEmail);
                                        const measurements = current?.measurements ?? [];
                                        return (
                                            <div className="overflow-x-auto">
                                                {measurements.length === 0 ? (
                                                    <p className="text-slate-500 py-2">Aucune mesure pour ce patient.</p>
                                                ) : (
                                                    <table>
                                                        <thead>
                                                            <tr>
                                                                <th className="pl-2">Date / Heure</th>
                                                                <th className="text-center">FC (bpm)</th>
                                                                <th className="text-center">SpO2 (%)</th>
                                                                <th className="text-center">Température (°C)</th>
                                                                <th className="text-center">Statut</th>
                                                            </tr>
                                                        </thead>
                                                        <tbody>
                                                            {measurements.map((m, idx) => {
                                                                const status = getMeasurementStatus(m);
                                                                return (
                                                                    <tr key={m.timestamp ?? idx}>
                                                                        <td className="pl-2 font-mono">
                                                                            {m.timestamp
                                                                                ? new Date(m.timestamp).toLocaleString('fr-FR', {
                                                                                    dateStyle: 'short',
                                                                                    timeStyle: 'short',
                                                                                })
                                                                                : '—'}
                                                                        </td>
                                                                        <td className="text-center">{m.heart_rate != null ? m.heart_rate : '—'}</td>
                                                                        <td className="text-center">{m.spo2 != null ? m.spo2 : '—'}</td>
                                                                        <td className="text-center">{m.temperature != null ? Number(m.temperature).toFixed(1) : '—'}</td>
                                                                        <td className="text-center">
                                                                            <span className="status-wrapper">
                                                                                <span className={`dot ${
                                                                                    status === 'normal' ? 'green' : status === 'warning' ? 'yellow' : 'red'
                                                                                }`}></span>
                                                                                {status === 'normal' ? 'Normal' : status === 'warning' ? 'Attention' : 'Critique'}
                                                                            </span>
                                                                        </td>
                                                                    </tr>
                                                                );
                                                            })}
                                                        </tbody>
                                                    </table>
                                                )}
                                            </div>
                                        );
                                    })()}
                                </>
                            )}
                        </div>

                    </div>
                </main>
            </div>
        </div>
    );
}
