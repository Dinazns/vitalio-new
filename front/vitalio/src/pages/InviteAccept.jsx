import React, { useState } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { useAuth0 } from '@auth0/auth0-react'
import { LogIn, CheckCircle, AlertCircle } from 'lucide-react'
import { acceptDoctorInvitation } from '../services/api'

export default function InviteAccept() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const { isAuthenticated, isLoading, loginWithRedirect, getAccessTokenSilently, user } = useAuth0()
  const token = searchParams.get('token')?.trim() || ''

  const [accepting, setAccepting] = useState(false)
  const [success, setSuccess] = useState(false)
  const [error, setError] = useState('')

  const handleLogin = () => {
    loginWithRedirect({
      appState: { returnTo: `/invite?token=${encodeURIComponent(token)}` },
      authorizationParams: { screen_hint: 'login' },
    })
  }

  const handleSignup = () => {
    loginWithRedirect({
      appState: { returnTo: `/invite?token=${encodeURIComponent(token)}` },
      authorizationParams: { screen_hint: 'signup' },
    })
  }

  const handleAccept = async () => {
    if (!token) return
    try {
      setError('')
      setAccepting(true)
      const accessToken = await getAccessTokenSilently()
      await acceptDoctorInvitation(accessToken, token)
      setSuccess(true)
      if (user) {
        localStorage.setItem('vitalio_user', JSON.stringify({
          email: user.email,
          name: user.name || user.email,
          role: 'patient',
          picture: user.picture,
        }))
      }
      setTimeout(() => navigate('/patient/bienvenue'), 2000)
    } catch (e) {
      setError(e.message || "Echec d'acceptation de l'invitation")
    } finally {
      setAccepting(false)
    }
  }

  if (!token) {
    return (
      <div className="login-container">
        <div className="login-card animate-fade-in">
          <AlertCircle size={48} style={{ color: '#dc2626', marginBottom: '16px' }} />
          <h2>Lien invalide</h2>
          <p>Cette invitation ne contient pas de token valide.</p>
          <button onClick={() => navigate('/')} className="login-button">
            Retour à l'accueil
          </button>
        </div>
      </div>
    )
  }

  if (!isAuthenticated && !isLoading) {
    return (
      <div className="login-container">
        <div className="login-card animate-fade-in">
          <h2>Invitation VitalIO</h2>
          <p>Créez un compte ou connectez-vous pour accepter cette invitation et associer votre compte à votre médecin.</p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <button onClick={handleSignup} className="login-button">
              <LogIn size={20} />
              <span>S'inscrire</span>
            </button>
            <button onClick={handleLogin} className="login-button" style={{ background: 'transparent', color: 'var(--color-primary, #2563eb)' }}>
              <span>Déjà un compte ? Se connecter</span>
            </button>
          </div>
        </div>
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="login-container">
        <div className="login-card">
          <p>Chargement...</p>
        </div>
      </div>
    )
  }

  if (success) {
    return (
      <div className="login-container">
        <div className="login-card animate-fade-in">
          <CheckCircle size={48} style={{ color: '#047857', marginBottom: '16px' }} />
          <h2>Invitation acceptée</h2>
          <p>Votre compte est maintenant associé à votre médecin. Redirection...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="login-container">
      <div className="login-card animate-fade-in">
        <h2>Accepter l'invitation</h2>
        <p>Votre médecin vous a invité à associer votre compte VitalIO. Cliquez ci-dessous pour accepter.</p>
        {error && (
          <div className="login-error" style={{ marginBottom: '16px' }}>
            <AlertCircle size={18} />
            <span>{error}</span>
          </div>
        )}
        <button
          onClick={handleAccept}
          disabled={accepting}
          className="login-button"
        >
          {accepting ? 'Acceptation en cours...' : 'Accepter l\'invitation'}
        </button>
      </div>
    </div>
  )
}
