import React, { useEffect, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { useAuth0 } from '@auth0/auth0-react'
import {
  LayoutDashboard,
  BrainCircuit,
  User,
  LogOut,
  PanelLeftClose,
  PanelLeft,
  Cpu,
} from 'lucide-react'
import { resolvePatientDisplayName } from '../utils/displayName'

const NAV_ITEMS = [
  { to: '/patient', icon: LayoutDashboard, label: 'Tableau de bord', end: true },
  { to: '/patient/profile', icon: User, label: 'Mon profil' },
  { to: '/patient/enroll-device', icon: Cpu, label: 'Mon boîtier' },
  { to: '/patient/ml', icon: BrainCircuit, label: 'Analyse de mes mesures' },
]

export default function PatientLayout({ children }) {
  const { logout, user } = useAuth0()
  const [collapsed, setCollapsed] = useState(true)
  const sidebarName = resolvePatientDisplayName({ user }) || 'Patient'

  const closeSidebar = () => setCollapsed(true)

  useEffect(() => {
    if (collapsed) return
    const onKeyDown = (e) => {
      if (e.key === 'Escape') closeSidebar()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [collapsed])

  const handleLogout = () => {
    logout({ logoutParams: { returnTo: window.location.origin } })
    localStorage.removeItem('vitalio_user')
  }

  return (
    <div className={`patient-layout ${collapsed ? 'patient-layout--collapsed' : ''}`}>
      <aside className="patient-sidebar" aria-hidden={collapsed}>
        <div className="sidebar-header">
          <span className="sidebar-brand">VitalIO</span>
        </div>

        {user && (
          <div className="sidebar-user">
            <div className="sidebar-user-avatar">
              {sidebarName.charAt(0).toUpperCase()}
            </div>
            <span className="sidebar-user-name">{sidebarName}</span>
          </div>
        )}

        <nav className="sidebar-nav" aria-label="Navigation principale">
          {NAV_ITEMS.map(({ to, icon: Icon, label, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `sidebar-link${isActive ? ' sidebar-link--active' : ''}`
              }
              onClick={closeSidebar}
            >
              <Icon size={20} />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-footer">
          <button type="button" className="sidebar-link sidebar-link--danger" onClick={handleLogout}>
            <LogOut size={20} />
            <span>Déconnexion</span>
          </button>
        </div>
      </aside>

      {!collapsed && (
        <button
          type="button"
          className="sidebar-backdrop"
          aria-label="Fermer le menu"
          onClick={closeSidebar}
        />
      )}

      <button
        type="button"
        className="patient-sidebar-fab"
        onClick={() => setCollapsed((c) => !c)}
        aria-label={collapsed ? 'Ouvrir le menu' : 'Fermer le menu'}
        aria-expanded={!collapsed}
      >
        {collapsed ? <PanelLeft size={22} aria-hidden /> : <PanelLeftClose size={22} aria-hidden />}
      </button>

      <main className="patient-main">{children}</main>
    </div>
  )
}
