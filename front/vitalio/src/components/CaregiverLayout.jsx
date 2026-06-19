import React, { useEffect, useState } from 'react'
import { NavLink, useParams, Outlet, useLocation } from 'react-router-dom'
import { useAuth0 } from '@auth0/auth0-react'
import {
  LayoutDashboard,
  BrainCircuit,
  LogOut,
  PanelLeftClose,
  PanelLeft,
  TriangleAlert,
  UserRound,
} from 'lucide-react'
import { getCaregiverAlerts, getCaregiverPatients } from '../services/api'
import PushPermissionBanner from './PushPermissionBanner'

const ROLE_DISPLAY = { caregiver: 'Aidant', aidant: 'Aidant' }

function getDisplayRole() {
  try {
    const stored = JSON.parse(localStorage.getItem('vitalio_user') || '{}')
    const role = stored?.role
    if (role) return ROLE_DISPLAY[String(role).toLowerCase()] || 'Aidant'
  } catch {}
  return 'Aidant'
}

function resolvePatientId(patient) {
  if (!patient) return null
  const id = patient.id ?? patient.patient_id
  return id != null ? String(id) : null
}

export default function CaregiverLayout({ children }) {
  const { patientId } = useParams()
  const { pathname } = useLocation()
  const base = pathname.startsWith('/family') ? '/family' : '/caregiver'
  const { logout, user, getAccessTokenSilently } = useAuth0()
  const [collapsed, setCollapsed] = useState(true)
  const [criticalCount, setCriticalCount] = useState(0)
  const [linkedPatientId, setLinkedPatientId] = useState(null)

  const navPatientId = patientId ?? linkedPatientId

  const closeSidebar = () => setCollapsed(true)

  useEffect(() => {
    if (collapsed) return
    const onKeyDown = (e) => {
      if (e.key === 'Escape') closeSidebar()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [collapsed])

  useEffect(() => {
    let mounted = true
    const load = async () => {
      try {
        const token = await getAccessTokenSilently()
        const [alertsRes, patientsRes] = await Promise.all([
          getCaregiverAlerts(token, { status: 'OPEN', limit: 500 }),
          getCaregiverPatients(token),
        ])
        if (!mounted) return
        setCriticalCount(Array.isArray(alertsRes.alerts) ? alertsRes.alerts.length : 0)
        const pts = Array.isArray(patientsRes.patients) ? patientsRes.patients : []
        setLinkedPatientId(resolvePatientId(pts[0]))
      } catch {
        if (mounted) {
          setCriticalCount(0)
          setLinkedPatientId(null)
        }
      }
    }
    load()
    const t = setInterval(load, 30000)
    return () => {
      mounted = false
      clearInterval(t)
    }
  }, [getAccessTokenSilently])

  const handleLogout = () => {
    logout({ logoutParams: { returnTo: window.location.origin } })
    localStorage.removeItem('vitalio_user')
  }

  return (
    <div className={`caregiver-layout ${collapsed ? 'caregiver-layout--collapsed' : ''}`}>
      <aside className="caregiver-sidebar" aria-hidden={collapsed}>
        <div className="sidebar-header">
          <span className="sidebar-brand">VitalIO</span>
        </div>

        {user && (
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

        <nav className="sidebar-nav" aria-label="Navigation principale">
          <NavLink
            to={base}
            end
            className={({ isActive }) =>
              `sidebar-link${isActive ? ' sidebar-link--active' : ''}`
            }
            onClick={closeSidebar}
          >
            <LayoutDashboard size={20} aria-hidden />
            <span>Tableau de bord</span>
          </NavLink>
          <NavLink
            to={`${base}/alertes`}
            className={({ isActive }) =>
              `sidebar-link${isActive ? ' sidebar-link--active' : ''}`
            }
            onClick={closeSidebar}
          >
            <TriangleAlert size={20} aria-hidden />
            <span>Alertes</span>
            {criticalCount > 0 && (
              <span className="sidebar-badge sidebar-badge--critical" aria-hidden>
                {criticalCount}
              </span>
            )}
          </NavLink>
          {navPatientId && (
            <NavLink
              to={`${base}/patient/${encodeURIComponent(navPatientId)}`}
              end
              className={({ isActive }) =>
                `sidebar-link${isActive ? ' sidebar-link--active' : ''}`
              }
              onClick={closeSidebar}
            >
              <UserRound size={20} aria-hidden />
              <span>Mon proche</span>
            </NavLink>
          )}
          {navPatientId && (
            <NavLink
              to={`${base}/patient/${encodeURIComponent(navPatientId)}/ml`}
              className={({ isActive }) =>
                `sidebar-link${isActive ? ' sidebar-link--active' : ''}`
              }
              onClick={closeSidebar}
            >
              <BrainCircuit size={20} aria-hidden />
              <span>Suivi avancé</span>
            </NavLink>
          )}
        </nav>

        <div className="sidebar-footer">
          <button type="button" className="sidebar-link sidebar-link--danger" onClick={handleLogout}>
            <LogOut size={20} aria-hidden />
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
        className="caregiver-sidebar-fab"
        onClick={() => setCollapsed((c) => !c)}
        aria-label={collapsed ? 'Ouvrir le menu' : 'Fermer le menu'}
        aria-expanded={!collapsed}
      >
        {collapsed ? <PanelLeft size={22} aria-hidden /> : <PanelLeftClose size={22} aria-hidden />}
      </button>

      <main className="caregiver-layout-main">
        <PushPermissionBanner getAccessTokenSilently={getAccessTokenSilently} />
        <Outlet />
      </main>
    </div>
  )
}
