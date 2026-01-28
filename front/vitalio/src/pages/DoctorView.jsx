import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth0 } from '@auth0/auth0-react';
import {
    Users, Activity, Bell, Settings, LogOut,
    Search, Filter, ChevronRight
} from 'lucide-react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, AreaChart, Area } from 'recharts';
import { PATIENTS_LIST, VITALS_HISTORY } from '../data/mockData';

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

export default function DoctorView() {
    const navigate = useNavigate();
    const { logout } = useAuth0();

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
                    <div className="avatar">Dr</div>
                    <div className="info">
                        <p className="name">Dr. Sophie</p>
                        <p className="role">Cardiologue</p>
                    </div>
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
                        <StatCard title="Patients Suivis" value="24" trend="+3" good={true} />
                        <StatCard title="Alertes Critiques" value="2" trend="-1" good={true} />
                        <StatCard title="Consultations" value="8" trend="Auj." good={true} />
                        <StatCard title="Risque Moyen" value="Medium" trend="+2%" good={false} />
                    </div>

                    <div className="dashboard-grid">

                        {/* Patient Table */}
                        <div className="patient-table-section">
                            <div className="section-header">
                                <h3>Patients à Risque (Top 5)</h3>
                                <button>Voir tout <ChevronRight size={16} /></button>
                            </div>
                            <div className="overflow-x-auto">
                                <table>
                                    <thead>
                                        <tr>
                                            <th className="pl-2">Patient</th>
                                            <th className="text-center">Score Risque</th>
                                            <th className="text-center">SpO2</th>
                                            <th className="text-center">BPM</th>
                                            <th>Status</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {PATIENTS_LIST.sort((a, b) => b.riskScore - a.riskScore).map(patient => (
                                            <tr key={patient.id}>
                                                <td className="pl-2 font-bold text-slate-700">{patient.name} <span className="font-normal text-slate-400 ml-1">{patient.age} ans</span></td>
                                                <td className="text-center">
                                                    <span className={`risk-badge ${patient.riskScore > 50 ? 'high' : 'low'}`}>
                                                        {patient.riskScore}%
                                                    </span>
                                                </td>
                                                <td className="text-center font-mono">{patient.spo2}%</td>
                                                <td className="text-center font-mono">{patient.heartRate}</td>
                                                <td>
                                                    <span className="status-wrapper">
                                                        <span className={`dot ${patient.riskScore > 50 ? 'red' : 'green'}`}></span>
                                                        {patient.status}
                                                    </span>
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </div>

                        {/* Charts Section */}
                        <div className="charts-column">

                            {/* SpO2 Chart */}
                            <div className="chart-card">
                                <h3>Tendance SpO2 (Robert)</h3>
                                <div className="chart-area">
                                    <ResponsiveContainer width="100%" height="100%">
                                        <AreaChart data={VITALS_HISTORY}>
                                            <defs>
                                                <linearGradient id="colorSpo2" x1="0" y1="0" x2="0" y2="1">
                                                    <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                                                    <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                                                </linearGradient>
                                            </defs>
                                            <XAxis dataKey="time" hide />
                                            <YAxis domain={[90, 100]} hide />
                                            <Tooltip
                                                contentStyle={{ borderRadius: '12px', border: 'none', boxShadow: '0 4px 12px rgba(0,0,0,0.1)' }}
                                            />
                                            <Area
                                                type="monotone"
                                                dataKey="spo2"
                                                stroke="#3b82f6"
                                                strokeWidth={3}
                                                fillOpacity={1}
                                                fill="url(#colorSpo2)"
                                            />
                                        </AreaChart>
                                    </ResponsiveContainer>
                                </div>
                            </div>

                            {/* Heart Rate Chart */}
                            <div className="chart-card">
                                <h3>Tendance Cardiaque (Robert)</h3>
                                <div className="chart-area">
                                    <ResponsiveContainer width="100%" height="100%">
                                        <LineChart data={VITALS_HISTORY}>
                                            <XAxis dataKey="time" axisLine={false} tickLine={false} tick={{ fontSize: 10 }} interval={2} />
                                            <YAxis domain={[60, 100]} hide />
                                            <Tooltip
                                                contentStyle={{ borderRadius: '12px', border: 'none', boxShadow: '0 4px 12px rgba(0,0,0,0.1)' }}
                                            />
                                            <Line type="monotone" dataKey="heartRate" stroke="#ef4444" strokeWidth={3} dot={{ r: 4, fill: '#ef4444', strokeWidth: 2, stroke: '#fff' }} />
                                        </LineChart>
                                    </ResponsiveContainer>
                                </div>
                            </div>

                        </div>

                    </div>
                </main>
            </div>
        </div>
    );
}
