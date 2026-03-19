import React, { useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { useAuth0 } from '@auth0/auth0-react'
import {
  LayoutDashboard,
  BrainCircuit,
  LogOut,
  ChevronLeft,
  ChevronRight,
  Home,
  Stethoscope,
} from 'lucide-react'

const NAV_ITEMS = [
  { to: '/doctor', icon: LayoutDashboard, label: 'Patients', end: true },
  { to: '/doctor/alertes', icon: BrainCircuit, label: 'Alertes' },
]

const ROLE_DISPLAY = { superuser: 'Superuser', doctor: 'Médecin', medecin: 'Médecin', 'médecin': 'Médecin' }

function getDisplayRole() {
  try {
    const stored = JSON.parse(localStorage.getItem('vitalio_user') || '{}')
    const role = stored?.role
    if (role) return ROLE_DISPLAY[String(role).toLowerCase()] || role
  } catch {}
  return 'Médecin'
}

export default function DoctorLayout({ children }) {
  const navigate = useNavigate()
  const { logout, user } = useAuth0()
  const [collapsed, setCollapsed] = useState(false)

  const handleLogout = () => {
    logout({ logoutParams: { returnTo: window.location.origin } })
    localStorage.removeItem('vitalio_user')
  }

  return (
    <div className={`doctor-layout ${collapsed ? 'doctor-layout--collapsed' : ''}`}>
      <aside className="doctor-sidebar">
        <div className="sidebar-header">
          {!collapsed && (
            <span className="sidebar-brand">
              <Stethoscope size={18} /> VitalIO
            </span>
          )}
          <button
            className="sidebar-toggle"
            onClick={() => setCollapsed((c) => !c)}
            aria-label={collapsed ? 'Ouvrir le menu' : 'Réduire le menu'}
          >
            {collapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}
          </button>
        </div>

        {!collapsed && user && (
          <div className="sidebar-user">
            <div className="sidebar-user-avatar sidebar-user-avatar--doctor">
              {(user.given_name || user.name || 'D').charAt(0).toUpperCase()}
            </div>
            <div className="sidebar-user-info">
              <span className="sidebar-user-name">{user.given_name || user.name || 'Médecin'}</span>
              <span className="sidebar-user-role">{getDisplayRole()}</span>
            </div>
          </div>
        )}

        <nav className="sidebar-nav">
          {NAV_ITEMS.map(({ to, icon: Icon, label, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `sidebar-link${isActive ? ' sidebar-link--active' : ''}`
              }
              title={collapsed ? label : undefined}
            >
              <Icon size={20} />
              {!collapsed && <span>{label}</span>}
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-footer">
          <button className="sidebar-link" onClick={() => navigate('/home')} title="Accueil">
            <Home size={20} />
            {!collapsed && <span>Accueil</span>}
          </button>
          <button className="sidebar-link sidebar-link--danger" onClick={handleLogout} title="Déconnexion">
            <LogOut size={20} />
            {!collapsed && <span>Déconnexion</span>}
          </button>
        </div>
      </aside>

      <main className="doctor-layout-main">{children}</main>
    </div>
  )
}
