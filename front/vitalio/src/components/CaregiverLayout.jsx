import React, { useEffect, useState } from 'react'
import { NavLink, useNavigate, useParams, Outlet, useLocation } from 'react-router-dom'
import { useAuth0 } from '@auth0/auth0-react'
import {
  Heart,
  BrainCircuit,
  LogOut,
  ChevronLeft,
  ChevronRight,
  Home,
} from 'lucide-react'
import { getCaregiverAlerts } from '../services/api'

const ROLE_DISPLAY = { caregiver: 'Aidant', aidant: 'Aidant' }

function getDisplayRole() {
  try {
    const stored = JSON.parse(localStorage.getItem('vitalio_user') || '{}')
    const role = stored?.role
    if (role) return ROLE_DISPLAY[String(role).toLowerCase()] || 'Aidant'
  } catch {}
  return 'Aidant'
}

export default function CaregiverLayout({ children }) {
  const navigate = useNavigate()
  const { patientId } = useParams()
  const { pathname } = useLocation()
  const base = pathname.startsWith('/family') ? '/family' : '/caregiver'
  const { logout, user, getAccessTokenSilently } = useAuth0()
  const [collapsed, setCollapsed] = useState(false)
  const [criticalCount, setCriticalCount] = useState(0)

  useEffect(() => {
    let mounted = true
    const load = async () => {
      try {
        const token = await getAccessTokenSilently()
        const res = await getCaregiverAlerts(token, { status: 'OPEN', limit: 500 })
        const count = Array.isArray(res.alerts) ? res.alerts.length : 0
        if (mounted) setCriticalCount(count)
      } catch {
        if (mounted) setCriticalCount(0)
      }
    }
    load()
    return () => { mounted = false }
  }, [getAccessTokenSilently])

  const handleLogout = () => {
    logout({ logoutParams: { returnTo: window.location.origin } })
    localStorage.removeItem('vitalio_user')
  }

  const basePath = patientId ? `${base}/patient/${encodeURIComponent(patientId)}` : base

  return (
    <div className={`caregiver-layout ${collapsed ? 'caregiver-layout--collapsed' : ''}`}>
      <aside className="caregiver-sidebar">
        <div className="sidebar-header">
          {!collapsed && (
            <span className="sidebar-brand">
              <Heart size={18} /> VitalIO
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
            <div className="sidebar-user-avatar sidebar-user-avatar--caregiver">
              {(user.given_name || user.name || 'A').charAt(0).toUpperCase()}
            </div>
            <div className="sidebar-user-info">
              <span className="sidebar-user-name">{user.given_name || user.name || 'Aidant'}</span>
              <span className="sidebar-user-role">{getDisplayRole()}</span>
            </div>
          </div>
        )}

        <nav className="sidebar-nav">
          <NavLink
            to={basePath}
            end={!patientId}
            className={({ isActive }) =>
              `sidebar-link${isActive ? ' sidebar-link--active' : ''}`
            }
            title={collapsed ? 'Mon proche' : undefined}
          >
            <Heart size={20} />
            {!collapsed && <span>Mon proche</span>}
            {!collapsed && criticalCount > 0 && (
              <span className="sidebar-badge sidebar-badge--critical">{criticalCount}</span>
            )}
          </NavLink>
          {patientId && (
            <NavLink
              to={`${base}/patient/${encodeURIComponent(patientId)}/ml`}
              className={({ isActive }) =>
                `sidebar-link${isActive ? ' sidebar-link--active' : ''}`
              }
              title={collapsed ? 'Analyses' : undefined}
            >
              <BrainCircuit size={20} />
              {!collapsed && <span>Analyses</span>}
            </NavLink>
          )}
        </nav>

        <div className="sidebar-footer">
          <button className="sidebar-link" onClick={() => navigate('/home')} title="Retour à l'accueil">
            <Home size={20} />
            {!collapsed && <span>Accueil</span>}
          </button>
          <button className="sidebar-link sidebar-link--danger" onClick={handleLogout} title="Déconnexion">
            <LogOut size={20} />
            {!collapsed && <span>Déconnexion</span>}
          </button>
        </div>
      </aside>

      <main className="caregiver-layout-main"><Outlet /></main>
    </div>
  )
}
