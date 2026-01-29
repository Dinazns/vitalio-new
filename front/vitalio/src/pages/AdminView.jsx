import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth0 } from '@auth0/auth0-react';
import { ArrowLeft, Server, Power, FileText } from 'lucide-react';
import { getDoctorRequests } from '../services/api';

const AUDIENCE = import.meta.env.VITE_AUTH0_AUDIENCE || 'auth';

const StatusBadge = ({ status }) => {
    const colors = {
        online: 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20',
        offline: 'bg-slate-500/10 text-slate-500 border-slate-500/20',
        warning: 'bg-amber-500/10 text-amber-500 border-amber-500/20',
    };
    return (
        <span className={`px-2 py-1 rounded text-xs font-mono uppercase border ${colors[status] || colors.offline}`}>
            {status}
        </span>
    );
};

function formatDate(iso) {
    if (!iso) return '—';
    try {
        const d = new Date(iso);
        return d.toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' });
    } catch {
        return iso;
    }
}

export default function AdminView() {
    const navigate = useNavigate();
    const { getAccessTokenSilently, loginWithRedirect, logout } = useAuth0();
    const [doctorRequests, setDoctorRequests] = useState([]);
    const [requestsLoading, setRequestsLoading] = useState(true);
    const [requestsError, setRequestsError] = useState(null);

    useEffect(() => {
        let cancelled = false;
        async function load() {
            setRequestsLoading(true);
            setRequestsError(null);
            try {
                let token;
                try {
                    token = await getAccessTokenSilently({
                        authorizationParams: {
                            audience: AUDIENCE,
                            // Inclure les permissions nécessaires (ex: add_users) dans le scope
                            scope: 'openid profile email read:patient_data add_users',
                        },
                    });
                } catch (e) {
                    // Cas Auth0: consentement / login requis → rediriger vers Auth0 (flow interactif)
                    if (e?.error === 'consent_required' || e?.error === 'login_required' || e?.error === 'interaction_required') {
                        await loginWithRedirect({
                            authorizationParams: {
                                audience: AUDIENCE,
                                scope: 'openid profile email read:patient_data add_users',
                            },
                            appState: { returnTo: '/admin' },
                        });
                        return;
                    }
                    throw e;
                }

                const data = await getDoctorRequests(token);
                if (!cancelled) setDoctorRequests(data.requests || []);
            } catch (err) {
                if (!cancelled) setRequestsError(err.message || 'Erreur chargement des demandes.');
            } finally {
                if (!cancelled) setRequestsLoading(false);
            }
        }
        load();
        return () => { cancelled = true; };
    }, [getAccessTokenSilently, loginWithRedirect]);

    const totalRequests = doctorRequests.length;
    const lastRequestDate = totalRequests > 0 ? doctorRequests[0].created_at : null;

    const handleLogout = () => {
        localStorage.removeItem('vitalio_user');
        logout({ logoutParams: { returnTo: window.location.origin } });
    };

    return (
        <div className="admin-container admin-theme">

            {/* Navbar Technical */}
            <nav className="admin-nav">
                <div className="nav-left">
                    <button onClick={() => navigate('/')} className="back-btn">
                        <ArrowLeft size={20} />
                    </button>
                    <div className="app-info-block">
                        <h1 className="app-title">
                            <Server size={18} className="icon" />
                            VitalIO_Admin
                        </h1>
                        <p className="version">v2.4.0-stable • system: ok</p>
                    </div>
                </div>
                <div className="nav-right">
                    <span className="status-dot animate-pulse"></span>
                    <span className="status-text">Connected</span>
                    <button
                        type="button"
                        className="logout-btn"
                        onClick={handleLogout}
                        aria-label="Déconnexion"
                        style={{ marginLeft: '0.75rem' }}
                    >
                        <Power size={18} />
                    </button>
                </div>
            </nav>

            <div className="admin-content">

                {/* KPI Grid */}
                <div className="kpi-grid">
                    <div className="kpi-card">
                        <p className="label">Total demandes</p>
                        <p className="value">
                            {requestsLoading ? '...' : totalRequests}
                        </p>
                    </div>
                    <div className="kpi-card">
                        <p className="label">Dernière demande</p>
                        <p className="value">
                            {requestsLoading
                                ? '...'
                                : (lastRequestDate ? formatDate(lastRequestDate) : 'Aucune')}
                        </p>
                    </div>
                </div>

                {/* Demandes Médecin → Patient (lecture seule) */}
                <div className="kpi-grid" style={{ marginBottom: '1.5rem' }}>
                    <div className="kpi-card" style={{ gridColumn: '1 / -1' }}>
                        <p className="label" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            <FileText size={18} /> Demandes d'association Médecin → Patient
                        </p>
                        {requestsLoading && <p className="value" style={{ fontSize: '0.9rem' }}>Chargement...</p>}
                        {requestsError && (
                            <p className="value err" style={{ fontSize: '0.9rem' }}>{requestsError}</p>
                        )}
                        {!requestsLoading && !requestsError && (
                            <div className="overflow-x-auto" style={{ marginTop: '0.75rem' }}>
                                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.875rem' }}>
                                    <thead>
                                        <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.1)', textAlign: 'left' }}>
                                            <th style={{ padding: '0.5rem 0.75rem' }}>doctor_id</th>
                                            <th style={{ padding: '0.5rem 0.75rem' }}>doctor_email</th>
                                            <th style={{ padding: '0.5rem 0.75rem' }}>patient_email</th>
                                            <th style={{ padding: '0.5rem 0.75rem' }}>status</th>
                                            <th style={{ padding: '0.5rem 0.75rem' }}>created_at</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {doctorRequests.length === 0 ? (
                                            <tr>
                                                <td colSpan={5} style={{ padding: '1rem', color: 'var(--admin-muted)' }}>
                                                    Aucune demande pour le moment.
                                                </td>
                                            </tr>
                                        ) : (
                                            doctorRequests.map((req) => (
                                                <tr key={req.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                                                    <td style={{ padding: '0.5rem 0.75rem', fontFamily: 'monospace', fontSize: '0.8rem' }}>{req.doctor_id}</td>
                                                    <td style={{ padding: '0.5rem 0.75rem' }}>{req.doctor_email}</td>
                                                    <td style={{ padding: '0.5rem 0.75rem' }}>{req.patient_email}</td>
                                                    <td style={{ padding: '0.5rem 0.75rem', textTransform: 'uppercase', fontSize: '0.75rem' }}>{req.status}</td>
                                                    <td style={{ padding: '0.5rem 0.75rem' }}>{formatDate(req.created_at)}</td>
                                                </tr>
                                            ))
                                        )}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </div>
                </div>

            </div>
        </div>
    );
}
