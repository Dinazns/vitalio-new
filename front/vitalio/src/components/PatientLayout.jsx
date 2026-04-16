import React, { useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { useAuth0 } from '@auth0/auth0-react'
import {
  LayoutDashboard,
  BrainCircuit,
  User,
  LogOut,
  ChevronLeft,
  ChevronRight,
  Home,
  Cpu,
} from 'lucide-react'

const NAV_ITEMS = [
  { to: '/patient', icon: LayoutDashboard, label: 'Tableau de bord', end: true },
  { to: '/patient/profile', icon: User, label: 'Mon profil' },
  { to: '/patient/enroll-device', icon: Cpu, label: 'Mon boîtier' },
  { to: '/patient/ml', icon: BrainCircuit, label: 'Analyse de mes mesures' },
]

export default function PatientLayout({ children }) {
  const navigate = useNavigate()
  const { logout, user } = useAuth0()
  const [collapsed, setCollapsed] = useState(false)

  const handleLogout = () => {
    logout({ logoutParams: { returnTo: window.location.origin } })
    localStorage.removeItem('vitalio_user')
  }

  return (
    <div className={`patient-layout ${collapsed ? 'patient-layout--collapsed' : ''}`}>
      <aside className="patient-sidebar">
        <div className="sidebar-header">
          {!collapsed && <span className="sidebar-brand">VitalIO</span>}
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
            <div className="sidebar-user-avatar">
              {(user.given_name || user.name || 'P').charAt(0).toUpperCase()}
            </div>
            <span className="sidebar-user-name">{user.given_name || user.name || 'Patient'}</span>
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

      <main className="patient-main">{children}</main>
    </div>
  )
}
