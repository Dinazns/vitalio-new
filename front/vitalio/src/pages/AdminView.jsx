import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth0 } from '@auth0/auth0-react';
import { ArrowLeft, Search, Server, RefreshCw, Link2, Ban, CheckCircle2, Stethoscope, User, ArrowRight, LogOut, ScrollText, Trash2, Users, ChevronDown, Cpu } from 'lucide-react';
import {
    adminListDevices,
    adminUpdateDeviceStatus,
    adminListDoctorPatientLinks,
    adminAssociateDoctorPatient,
    getAdminAuditLog,
    adminListUsers,
    adminDeleteUser,
} from '../services/api';

const AUDIT_EVENT_LABELS = {
    patient_data_export: 'Export données patient',
    patient_data_erasure: 'Suppression compte patient',
    patient_profile_read: 'Consultation profil patient',
    patient_measurements_read: 'Consultation mesures patient',
    admin_association_created: 'Association médecin-patient',
    admin_caregiver_association_created: 'Association aidant-patient',
    admin_user_deleted: 'Suppression utilisateur',
    device_status_changed: 'Changement statut device',
    alert_manual_trigger: 'Alerte manuelle patient',
    alert_doctor_triage: 'Triage alerte médecin',
};

const formatAuditDate = (iso) => {
    if (!iso) return '';
    try {
        return new Date(iso).toLocaleString('fr-FR', {
            day: '2-digit',
            month: '2-digit',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
        });
    } catch {
        return iso;
    }
};

const STATUS_LABELS = {
    active: 'Actif',
    suspended: 'Suspendu',
};

const StatusBadge = ({ status }) => {
    const isActive = status === 'active';
    return (
        <span
            className={`status-led ${isActive ? 'ok' : 'err'}`}
            title={isActive ? 'Dispositif actif' : 'Dispositif suspendu'}
        >
            <span className="led-dot" aria-hidden="true" />
            {STATUS_LABELS[status] || status}
        </span>
    );
};

const EnrolledBadge = ({ enrolled }) => (
    <span
        className={`status-led ${enrolled ? 'ok' : 'err'}`}
        title={enrolled ? 'Boîtier appairé au patient' : 'Boîtier non appairé'}
    >
        <span className="led-dot" aria-hidden="true" />
        {enrolled ? 'Appairé' : 'Non appairé'}
    </span>
);

const personLabel = (person) => {
    if (!person) return '-';
    const fullName = [person.first_name, person.last_name].filter(Boolean).join(' ').trim();
    return person.display_name || fullName || person.email || person.user_id_auth || '-';
};

const ROLE_LABELS = {
    patient: 'Patient',
    doctor: 'Médecin',
    medecin: 'Médecin',
    superuser: 'Médecin',
    caregiver: 'Aidant',
    aidant: 'Aidant',
    admin: 'Administrateur',
};

const roleLabel = (role) => ROLE_LABELS[String(role || '').toLowerCase()] || role || '-';

function AdminCollapsibleSection({ id, title, icon: Icon, count, expanded, onToggle, children }) {
    return (
        <section className={`admin-panel ${expanded ? 'admin-panel--open' : 'admin-panel--collapsed'}`}>
            <button
                type="button"
                className="admin-panel__toggle"
                onClick={onToggle}
                aria-expanded={expanded}
                aria-controls={`${id}-panel-body`}
            >
                <span className="admin-panel__title">
                    <Icon size={18} aria-hidden="true" />
                    {title}
                </span>
                <span className="admin-panel__meta">
                    <span className="admin-panel__count">{count}</span>
                    <ChevronDown
                        size={18}
                        className={`admin-panel__chevron ${expanded ? 'admin-panel__chevron--open' : ''}`}
                        aria-hidden="true"
                    />
                </span>
            </button>
            {expanded && (
                <div id={`${id}-panel-body`} className="admin-panel__body">
                    {children}
                </div>
            )}
        </section>
    );
}

export default function AdminView() {
    const navigate = useNavigate();
    const { getAccessTokenSilently, logout } = useAuth0();

    const handleLogout = () => {
        logout({ logoutParams: { returnTo: window.location.origin } });
        localStorage.removeItem('vitalio_user');
    };

    const [devices, setDevices] = React.useState([]);
    const [totalDevices, setTotalDevices] = React.useState(0);
    const [links, setLinks] = React.useState([]);
    const [loading, setLoading] = React.useState(true);
    const [error, setError] = React.useState('');
    const [busyDevice, setBusyDevice] = React.useState('');

    const [search, setSearch] = React.useState('');
    const [statusFilter, setStatusFilter] = React.useState('');
    const [doctorFilter, setDoctorFilter] = React.useState('');

    const [doctorId, setDoctorId] = React.useState('');
    const [patientId, setPatientId] = React.useState('');
    const [linkMessage, setLinkMessage] = React.useState('');
    const [linkError, setLinkError] = React.useState('');
    const [associating, setAssociating] = React.useState(false);

    const [auditEvents, setAuditEvents] = React.useState([]);
    const [auditTotal, setAuditTotal] = React.useState(0);
    const [auditFilter, setAuditFilter] = React.useState('');
    const [auditLoading, setAuditLoading] = React.useState(false);

    const [users, setUsers] = React.useState([]);
    const [usersTotal, setUsersTotal] = React.useState(0);
    const [userSearch, setUserSearch] = React.useState('');
    const [userRoleFilter, setUserRoleFilter] = React.useState('');
    const [usersLoading, setUsersLoading] = React.useState(false);
    const [busyUserId, setBusyUserId] = React.useState('');
    const [usersExpanded, setUsersExpanded] = React.useState(false);
    const [linksExpanded, setLinksExpanded] = React.useState(false);
    const [devicesExpanded, setDevicesExpanded] = React.useState(false);
    const [auditExpanded, setAuditExpanded] = React.useState(false);

    const loadAuditLog = React.useCallback(async (eventType = auditFilter) => {
        setAuditLoading(true);
        try {
            const token = await getAccessTokenSilently();
            const res = await getAdminAuditLog(token, { eventType, pageSize: 50 });
            setAuditEvents(res.events || []);
            setAuditTotal(res.total ?? 0);
        } catch (err) {
            console.error('Audit log load failed:', err);
        } finally {
            setAuditLoading(false);
        }
    }, [getAccessTokenSilently, auditFilter]);

    const loadUsers = React.useCallback(async (opts = {}) => {
        setUsersLoading(true);
        try {
            const token = await getAccessTokenSilently();
            const res = await adminListUsers(token, {
                q: opts.q ?? userSearch,
                role: opts.role ?? userRoleFilter,
                pageSize: 50,
            });
            setUsers(res.users || []);
            setUsersTotal(res.count || 0);
        } catch (err) {
            console.error('Users load failed:', err);
            setError(err.message || 'Impossible de charger les utilisateurs');
        } finally {
            setUsersLoading(false);
        }
    }, [getAccessTokenSilently, userSearch, userRoleFilter]);

    const loadAll = React.useCallback(async (opts = {}) => {
        setLoading(true);
        setError('');
        try {
            const token = await getAccessTokenSilently();
            const [devicesRes, linksRes] = await Promise.all([
                adminListDevices(token, { q: opts.q ?? search, status: opts.status ?? statusFilter }),
                adminListDoctorPatientLinks(token),
            ]);
            setDevices(devicesRes.devices || []);
            setTotalDevices(devicesRes.count || 0);
            setLinks(linksRes.links || []);
        } catch (e) {
            setError(e.message || 'Impossible de charger les données admin');
        } finally {
            setLoading(false);
        }
    }, [getAccessTokenSilently, search, statusFilter]);

    React.useEffect(() => {
        loadAll();
        loadAuditLog('');
        loadUsers();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const handleSearchSubmit = (event) => {
        event.preventDefault();
        loadAll();
    };

    const handleFilterChange = (value) => {
        setStatusFilter(value);
        loadAll({ status: value });
    };

    const handleToggleStatus = async (device) => {
        const suspending = device.status !== 'suspended';
        let reason = '';
        if (suspending) {
            if (!window.confirm(`Suspendre le dispositif ${device.device_id} ? Les nouvelles mesures seront bloquées.`)) {
                return;
            }
            reason = window.prompt('Motif de suspension (optionnel) :', '') || '';
        } else if (!window.confirm(`Réactiver le dispositif ${device.device_id} ?`)) {
            return;
        }
        setBusyDevice(device.device_id);
        setError('');
        try {
            const token = await getAccessTokenSilently();
            await adminUpdateDeviceStatus(token, device.device_id, suspending ? 'suspended' : 'active', reason);
            await loadAll();
            await loadAuditLog();
        } catch (e) {
            setError(e.message || 'Impossible de mettre à jour le statut du dispositif');
        } finally {
            setBusyDevice('');
        }
    };

    const handleUserSearchSubmit = (event) => {
        event.preventDefault();
        loadUsers();
    };

    const handleUserRoleFilterChange = (value) => {
        setUserRoleFilter(value);
        loadUsers({ role: value });
    };

    const handleDeleteUser = async (user) => {
        const label = personLabel(user);
        const role = roleLabel(user.role);
        const warning = role === 'Patient'
            ? 'Toutes les mesures, alertes et liens associés seront supprimés.'
            : 'Le profil VitalIO et les associations seront supprimés.';
        if (!window.confirm(`Supprimer ${label} (${role}) ?\n\n${warning}\n\nLe compte Auth0 ne sera pas supprimé automatiquement.`)) {
            return;
        }
        setBusyUserId(user.user_id_auth);
        setError('');
        try {
            const token = await getAccessTokenSilently();
            await adminDeleteUser(token, user.user_id_auth);
            await Promise.all([loadUsers(), loadAll(), loadAuditLog()]);
        } catch (e) {
            setError(e.message || "Impossible de supprimer l'utilisateur");
        } finally {
            setBusyUserId('');
        }
    };

    const handleAssociate = async () => {
        setLinkError('');
        setLinkMessage('');
        setAssociating(true);
        try {
            const token = await getAccessTokenSilently();
            await adminAssociateDoctorPatient(token, doctorId.trim(), patientId.trim());
            setLinkMessage('Association médecin-patient créée.');
            setDoctorId('');
            setPatientId('');
            const linksRes = await adminListDoctorPatientLinks(token);
            setLinks(linksRes.links || []);
            await loadAuditLog();
        } catch (e) {
            setLinkError(e.message || "Impossible de créer l'association");
        } finally {
            setAssociating(false);
        }
    };

    const doctorOptions = React.useMemo(() => {
        const byId = new Map();
        links.forEach((link) => {
            const doctor = link.doctor;
            if (doctor?.user_id_auth) byId.set(doctor.user_id_auth, doctor);
        });
        devices.forEach((device) => {
            (device.doctors || []).forEach((doctor) => {
                if (doctor?.user_id_auth) byId.set(doctor.user_id_auth, doctor);
            });
        });
        return Array.from(byId.values()).sort((a, b) =>
            personLabel(a).localeCompare(personLabel(b), 'fr', { sensitivity: 'base' })
        );
    }, [links, devices]);

    const filteredLinks = React.useMemo(() => {
        const list = doctorFilter
            ? links.filter((link) => link.doctor?.user_id_auth === doctorFilter)
            : links;
        return [...list].sort((a, b) =>
            personLabel(a.patient).localeCompare(personLabel(b.patient), 'fr', { sensitivity: 'base' })
        );
    }, [links, doctorFilter]);

    const filteredDevices = React.useMemo(() => {
        const list = doctorFilter
            ? devices.filter((device) =>
                (device.doctors || []).some((doctor) => doctor.user_id_auth === doctorFilter)
            )
            : devices;
        return [...list].sort((a, b) =>
            personLabel(a.patient).localeCompare(personLabel(b.patient), 'fr', { sensitivity: 'base' })
        );
    }, [devices, doctorFilter]);

    const activeCount = filteredDevices.filter((d) => d.status !== 'suspended').length;
    const suspendedCount = filteredDevices.filter((d) => d.status === 'suspended').length;
    const enrolledCount = filteredDevices.filter((d) => d.enrolled).length;

    const selectedDoctorLabel = doctorFilter
        ? personLabel(doctorOptions.find((d) => d.user_id_auth === doctorFilter))
        : null;

    return (
        <div className="admin-container admin-theme">

            <nav className="admin-nav">
                <div className="nav-left">
                    <button onClick={() => navigate('/')} className="back-btn">
                        <ArrowLeft size={20} />
                    </button>
                    <div className="app-info-block">
                        <h1 className="app-title">
                            <Server size={18} className="icon" />
                            Administration VitalIO
                        </h1>
                        <p className="version">Gestion des comptes, dispositifs et associations</p>
                    </div>
                </div>
                <div className="nav-right">
                    <span className="status-dot" />
                    <span className="status-text">{loading ? 'Chargement' : 'Connecté'}</span>
                    <button
                        type="button"
                        className="admin-logout-btn"
                        onClick={handleLogout}
                        title="Déconnexion"
                    >
                        <LogOut size={16} />
                        <span>Déconnexion</span>
                    </button>
                </div>
            </nav>

            <div className="admin-content">

                <div className="kpi-grid">
                    <div className="kpi-card">
                        <p className="label">{doctorFilter ? 'Patients filtrés' : 'Dispositifs (page)'}</p>
                        <p className="value">{filteredDevices.length}</p>
                    </div>
                    <div className="kpi-card">
                        <p className="label">Actifs</p>
                        <p className="value ok">{activeCount}</p>
                    </div>
                    <div className="kpi-card">
                        <p className="label">Suspendus</p>
                        <p className="value err">{suspendedCount}</p>
                    </div>
                    <div className="kpi-card">
                        <p className="label">Appairés</p>
                        <p className="value">
                            {enrolledCount}
                            {' / '}
                            {doctorFilter ? filteredDevices.length : totalDevices}
                            {doctorFilter ? '' : ' total'}
                        </p>
                    </div>
                </div>

                {error && <p className="admin-error-banner" role="alert">{error}</p>}

                <AdminCollapsibleSection
                    id="users"
                    title="Utilisateurs"
                    icon={Users}
                    count={`${usersTotal} compte${usersTotal !== 1 ? 's' : ''}`}
                    expanded={usersExpanded}
                    onToggle={() => setUsersExpanded((open) => !open)}
                >
                    <div className="toolbar" style={{ marginBottom: 0 }}>
                        <form className="search-box" onSubmit={handleUserSearchSubmit}>
                            <Search className="icon" size={16} />
                            <input
                                type="text"
                                placeholder="Rechercher email, nom ou identifiant…"
                                value={userSearch}
                                onChange={(event) => setUserSearch(event.target.value)}
                            />
                        </form>
                        <div className="toolbar-controls">
                            <select
                                className="admin-select"
                                value={userRoleFilter}
                                onChange={(event) => handleUserRoleFilterChange(event.target.value)}
                                aria-label="Filtrer par rôle"
                            >
                                <option value="">Tous les rôles</option>
                                <option value="patient">Patients</option>
                                <option value="doctor">Médecins</option>
                                <option value="caregiver">Aidants</option>
                            </select>
                            <button className="refresh-btn" type="button" onClick={() => loadUsers()} disabled={usersLoading}>
                                <RefreshCw size={16} /> {usersLoading ? 'Chargement…' : 'Actualiser'}
                            </button>
                        </div>
                    </div>

                    {usersLoading && users.length === 0 ? (
                        <p className="admin-empty">Chargement des utilisateurs…</p>
                    ) : users.length === 0 ? (
                        <p className="admin-empty">Aucun utilisateur trouvé.</p>
                    ) : (
                        <div className="admin-table-wrap">
                            <table className="admin-table">
                                <thead>
                                    <tr>
                                        <th>Nom</th>
                                        <th>Email</th>
                                        <th>Rôle</th>
                                        <th>Identifiant</th>
                                        <th style={{ width: '72px' }}>Action</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {users.map((user) => {
                                        const isAdminAccount = String(user.role || '').toLowerCase() === 'admin';
                                        return (
                                            <tr key={user.user_id_auth}>
                                                <td>{personLabel(user)}</td>
                                                <td>{user.email || '-'}</td>
                                                <td>{roleLabel(user.role)}</td>
                                                <td
                                                    style={{ maxWidth: '180px', overflow: 'hidden', textOverflow: 'ellipsis' }}
                                                    title={user.user_id_auth}
                                                >
                                                    {user.user_id_auth || '-'}
                                                </td>
                                                <td>
                                                    {!isAdminAccount ? (
                                                        <button
                                                            type="button"
                                                            className="admin-delete-user-btn"
                                                            title="Supprimer l'utilisateur"
                                                            disabled={busyUserId === user.user_id_auth}
                                                            onClick={() => handleDeleteUser(user)}
                                                        >
                                                            <Trash2 size={15} />
                                                        </button>
                                                    ) : (
                                                        <span className="admin-empty" style={{ fontSize: '0.75rem' }}>-</span>
                                                    )}
                                                </td>
                                            </tr>
                                        );
                                    })}
                                </tbody>
                            </table>
                        </div>
                    )}
                </AdminCollapsibleSection>

                <AdminCollapsibleSection
                    id="links"
                    title="Liaison médecin / patient"
                    icon={Link2}
                    count={
                        doctorFilter
                            ? `${filteredLinks.length} patient${filteredLinks.length !== 1 ? 's' : ''}`
                            : `${links.length} lien${links.length !== 1 ? 's' : ''}`
                    }
                    expanded={linksExpanded}
                    onToggle={() => setLinksExpanded((open) => !open)}
                >
                    <div className="association-section association-section--flat">
                    <div className="association-form">
                        <div className="association-field">
                            <label htmlFor="admin-doctor-id">
                                <Stethoscope size={12} />
                                Médecin
                            </label>
                            <input
                                id="admin-doctor-id"
                                type="text"
                                placeholder="auth0|… ou identifiant médecin"
                                value={doctorId}
                                onChange={(event) => setDoctorId(event.target.value)}
                            />
                        </div>

                        <div className="association-arrow" aria-hidden="true">
                            <ArrowRight size={18} />
                        </div>

                        <div className="association-field">
                            <label htmlFor="admin-patient-id">
                                <User size={12} />
                                Patient
                            </label>
                            <input
                                id="admin-patient-id"
                                type="text"
                                placeholder="auth0|… ou identifiant patient"
                                value={patientId}
                                onChange={(event) => setPatientId(event.target.value)}
                            />
                        </div>

                        <div className="association-submit">
                            <button
                                className="refresh-btn"
                                onClick={handleAssociate}
                                type="button"
                                disabled={associating || !doctorId.trim() || !patientId.trim()}
                            >
                                <Link2 size={16} />
                                {associating ? 'Association…' : 'Associer'}
                            </button>
                        </div>
                    </div>

                    {linkError && (
                        <p className="association-feedback error" role="alert">{linkError}</p>
                    )}
                    {linkMessage && (
                        <p className="association-feedback success" role="status">{linkMessage}</p>
                    )}

                    <div className="association-links">
                        <p className="links-label">
                            {doctorFilter
                                ? `Patients de ${selectedDoctorLabel}`
                                : 'Liens existants'}
                        </p>
                        {filteredLinks.length === 0 ? (
                            <p className="links-empty">
                                {doctorFilter
                                    ? 'Aucun patient associé à ce médecin.'
                                    : 'Aucun lien médecin-patient enregistré.'}
                            </p>
                        ) : (
                            <div className="links-list">
                                {filteredLinks.map((link, idx) => (
                                    <div
                                        key={`${link.doctor?.user_id_auth}-${link.patient?.user_id_auth}-${idx}`}
                                        className="link-row"
                                    >
                                        <div className="link-parties">
                                            <span className="link-person doctor" title={link.doctor?.user_id_auth}>
                                                {personLabel(link.doctor)}
                                            </span>
                                            <ArrowRight size={14} className="link-arrow" />
                                            <span className="link-person patient" title={link.patient?.user_id_auth}>
                                                {personLabel(link.patient)}
                                            </span>
                                        </div>
                                        {link.linked_by && (
                                            <span className="link-meta">via {link.linked_by}</span>
                                        )}
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                    </div>
                </AdminCollapsibleSection>

                <AdminCollapsibleSection
                    id="devices"
                    title="Dispositifs"
                    icon={Cpu}
                    count={`${filteredDevices.length} affiché${filteredDevices.length !== 1 ? 's' : ''}`}
                    expanded={devicesExpanded}
                    onToggle={() => setDevicesExpanded((open) => !open)}
                >
                    <div className="toolbar">
                        <form className="search-box" onSubmit={handleSearchSubmit}>
                            <Search className="icon" size={16} />
                            <input
                                type="text"
                                placeholder="Rechercher ID dispositif, email ou nom patient…"
                                value={search}
                                onChange={(event) => setSearch(event.target.value)}
                            />
                        </form>
                        <div className="toolbar-controls">
                            <select
                                className="admin-select doctor-filter"
                                value={doctorFilter}
                                onChange={(event) => setDoctorFilter(event.target.value)}
                                aria-label="Filtrer par médecin"
                            >
                                <option value="">Tous les médecins</option>
                                {doctorOptions.map((doctor) => (
                                    <option key={doctor.user_id_auth} value={doctor.user_id_auth}>
                                        {personLabel(doctor)}
                                    </option>
                                ))}
                            </select>
                            <select
                                className="admin-select"
                                value={statusFilter}
                                onChange={(event) => handleFilterChange(event.target.value)}
                                aria-label="Filtrer par statut"
                            >
                                <option value="">Tous les statuts</option>
                                <option value="active">Actifs</option>
                                <option value="suspended">Suspendus</option>
                            </select>
                            <button className="refresh-btn" onClick={() => loadAll()} type="button">
                                <RefreshCw size={16} /> Actualiser
                            </button>
                        </div>
                    </div>

                    {loading && filteredDevices.length === 0 && devices.length === 0 ? (
                        <p className="admin-empty">Chargement des dispositifs…</p>
                    ) : filteredDevices.length === 0 ? (
                        <p className="admin-empty">
                            {doctorFilter
                                ? `Aucun dispositif pour ${selectedDoctorLabel}.`
                                : 'Aucun dispositif trouvé.'}
                        </p>
                    ) : (
                        <div className="devices-grid">
                            {filteredDevices.map((device) => (
                                <div key={device.device_id} className="device-card group">
                                    {device.status === 'suspended' && <div className="warning-overlay" />}

                                    <div className="card-header">
                                        <div>
                                            <h3>{personLabel(device.patient)}</h3>
                                            <p className="id-text">{device.device_id}</p>
                                        </div>
                                        <StatusBadge status={device.status} />
                                    </div>

                                    <div className="info-list">
                                        <div className="info-row border-b">
                                            <span className="label">Email</span>
                                            <span className="val">{device.patient?.email || '-'}</span>
                                        </div>
                                        <div className="info-row">
                                            <span className="label">Médecins liés</span>
                                            <span className="val">
                                                {device.doctors && device.doctors.length > 0
                                                    ? device.doctors.map((d) => personLabel(d)).join(', ')
                                                    : '-'}
                                            </span>
                                        </div>
                                        <div className="info-row">
                                            <span className="label">Appairage</span>
                                            <EnrolledBadge enrolled={device.enrolled} />
                                        </div>
                                        {device.status === 'suspended' && device.suspension_reason && (
                                            <div className="info-row">
                                                <span className="label">Motif</span>
                                                <span className="val">{device.suspension_reason}</span>
                                            </div>
                                        )}
                                    </div>

                                    <div className="actions">
                                        <button
                                            type="button"
                                            title={device.status === 'suspended' ? 'Réactiver' : 'Suspendre'}
                                            onClick={() => handleToggleStatus(device)}
                                            disabled={busyDevice === device.device_id}
                                        >
                                            {device.status === 'suspended'
                                                ? <CheckCircle2 size={16} />
                                                : <Ban size={16} />}
                                        </button>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </AdminCollapsibleSection>

                <AdminCollapsibleSection
                    id="audit"
                    title="Journal d'audit"
                    icon={ScrollText}
                    count={`${auditTotal} événement${auditTotal !== 1 ? 's' : ''}`}
                    expanded={auditExpanded}
                    onToggle={() => setAuditExpanded((open) => !open)}
                >
                    <div className="toolbar">
                    <div className="toolbar-controls">
                        <select
                            className="admin-select"
                            value={auditFilter}
                            onChange={(e) => {
                                setAuditFilter(e.target.value);
                                loadAuditLog(e.target.value);
                            }}
                            aria-label="Filtrer le journal d'audit"
                        >
                            <option value="">Tous les types</option>
                            {Object.entries(AUDIT_EVENT_LABELS).map(([key, label]) => (
                                <option key={key} value={key}>{label}</option>
                            ))}
                        </select>
                        <button className="refresh-btn" type="button" onClick={() => loadAuditLog()} disabled={auditLoading}>
                            <RefreshCw size={16} /> {auditLoading ? 'Chargement…' : 'Actualiser'}
                        </button>
                    </div>
                    </div>
                    {auditLoading && auditEvents.length === 0 ? (
                        <p className="admin-empty">Chargement du journal…</p>
                    ) : auditEvents.length === 0 ? (
                        <p className="admin-empty">Aucun événement enregistré pour le moment.</p>
                    ) : (
                        <div className="admin-table-wrap">
                            <table className="admin-table">
                                <thead>
                                    <tr>
                                        <th>Date</th>
                                        <th>Type</th>
                                        <th>Acteur</th>
                                        <th>Rôle</th>
                                        <th>Ressource</th>
                                        <th>Action</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {auditEvents.map((ev) => (
                                        <tr key={ev.id || `${ev.created_at}-${ev.event_type}`}>
                                            <td style={{ whiteSpace: 'nowrap' }}>{formatAuditDate(ev.created_at)}</td>
                                            <td>{AUDIT_EVENT_LABELS[ev.event_type] || ev.event_type}</td>
                                            <td style={{ maxWidth: '120px', overflow: 'hidden', textOverflow: 'ellipsis' }} title={ev.actor_user_id_auth}>
                                                {ev.actor_user_id_auth ? String(ev.actor_user_id_auth).slice(-12) : '-'}
                                            </td>
                                            <td>{ev.actor_role || '-'}</td>
                                            <td style={{ maxWidth: '140px', overflow: 'hidden', textOverflow: 'ellipsis' }} title={ev.resource_id}>
                                                {ev.resource_id || '-'}
                                            </td>
                                            <td>{ev.action || '-'}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </AdminCollapsibleSection>

            </div>
        </div>
    );
}
