import React from 'react';
import { useAuth0 } from '@auth0/auth0-react';
import { useNavigate } from 'react-router-dom';
import { ShieldCheck, Info, ArrowLeft, LogIn } from 'lucide-react';

const AUDIENCE = import.meta.env.VITE_AUTH0_AUDIENCE || 'auth';

/**
 * Écran d'information sur le consentement utilisateur (Auth0 - User Consent and Third-Party Applications).
 *
 * Objectifs :
 * - Expliquer en français le principe de consentement lorsqu'une application (potentiellement tierce)
 *   demande l'accès à des API protégées.
 * - Détail des scopes utilisés par l'application (action:ressource) pour être aligné avec la doc Auth0.
 * - Laisser l'utilisateur choisir explicitement de poursuivre vers la page d'Auth0 qui affichera
 *   la boîte de dialogue de consentement officielle.
 */
export default function Consent() {
  const { loginWithRedirect } = useAuth0();
  const navigate = useNavigate();

  const handleContinue = () => {
    // Redirige vers Auth0 avec l'audience de l'API et les scopes nécessaires.
    // La boîte de dialogue de consentement officielle Auth0 sera affichée
    // si l'application est considérée comme tierce ou si le consentement n'a
    // pas encore été accordé pour ce couple (application, API, scopes).
    loginWithRedirect({
      authorizationParams: {
        audience: AUDIENCE,
        scope: 'openid profile email read:patient_data',
      },
    });
  };

  return (
    <div className="login-container">
      <div className="login-bg-effects">
        <div className="bg-blob blob-1"></div>
        <div className="bg-blob blob-2"></div>
        <div className="bg-blob blob-3"></div>
        <div className="pulse-ring ring-1"></div>
        <div className="pulse-ring ring-2"></div>
      </div>

      <div className="login-card animate-fade-in">
        <button
          type="button"
          onClick={() => navigate('/')}
          className="back-button"
          aria-label="Retour à la page de connexion"
        >
          <ArrowLeft size={20} />
        </button>

        <div className="login-logo-section">
          <ShieldCheck size={40} className="mb-3 text-accent" />
          <h1 className="login-title">Consentement et accès à vos données</h1>
          <p className="login-subtitle">
            Comprendre comment vos données de santé sont protégées et quand votre accord est requis.
          </p>
        </div>

        <div className="login-form">
          <section className="consent-section">
            <h2 className="consent-section-title">Applications tierces et APIs protégées</h2>
            <p>
              VitalIO utilise <strong>Auth0</strong> et le standard <strong>OIDC (OpenID Connect)</strong> pour
              gérer l’authentification et l’accès aux <strong>APIs de télésurveillance médicale</strong>. Les
              APIs (par exemple l’API de mesures physiologiques) sont traitées comme des{' '}
              <strong>serveurs de ressources</strong>, séparés des applications clientes qui les consomment.
            </p>
            <p>
              Lorsqu’une application (y compris une application tierce que vous ne contrôlez pas directement)
              souhaite accéder à vos données via ces APIs, elle doit d’abord obtenir votre{' '}
              <strong>consentement explicite</strong>.
            </p>
          </section>

          <section className="consent-section">
            <h2 className="consent-section-title">Boîte de dialogue de consentement Auth0</h2>
            <p>
              Quand une application demande un accès à vos informations ou veut effectuer des actions en votre nom
              (par exemple lire vos mesures de santé), Auth0 affiche une{' '}
              <strong>boîte de dialogue de consentement</strong>. Cette boîte vous indique :
            </p>
            <ul className="consent-list">
              <li>Quelle application fait la demande.</li>
              <li>À quelle <strong>API</strong> elle souhaite accéder (par exemple l’API VitalIO).</li>
              <li>Quels <strong>scopes</strong> (permissions) elle demande.</li>
            </ul>
            <p>
              Si vous acceptez, Auth0 crée une <strong>autorisation (user grant)</strong> pour ce trio
              <em> (application, API, scopes)</em>. Tant que vous ne la révoquez pas, vous ne verrez plus cette
              boîte de dialogue pour la même combinaison.
            </p>
          </section>

          <section className="consent-section">
            <h2 className="consent-section-title">Scopes demandés par VitalIO</h2>
            <p>
              Conformément aux recommandations d’Auth0, les scopes sont nommés selon le format{' '}
              <code>action:ressource</code>. Par exemple :
            </p>
            <ul className="consent-list">
              <li>
                <code>openid</code>, <code>profile</code>, <code>email</code> – nécessaires pour vous identifier
                de manière sécurisée (standard OIDC).
              </li>
              <li>
                <code>read:patient_data</code> – autorise l’application à <strong>lire vos mesures de santé</strong>{' '}
                (données physiologiques issues de vos capteurs) via l’API VitalIO.
              </li>
            </ul>
            <p>
              Dans le panneau d’administration Auth0, il est également possible d’activer l’option{' '}
              <code>use_scope_descriptions_for_consent</code> pour afficher des descriptions plus lisibles à la
              place des noms techniques des scopes sur la boîte de dialogue de consentement.
            </p>
          </section>

          <section className="consent-section">
            <h2 className="consent-section-title">Votre choix</h2>
            <p>
              En cliquant sur <strong>« Continuer vers Auth0 »</strong>, vous serez redirigé vers la page
              d’authentification et de consentement officielle d’Auth0. Vous pourrez alors :
            </p>
            <ul className="consent-list">
              <li>Vérifier quelle application demande l’accès.</li>
              <li>Consulter précisément les permissions demandées.</li>
              <li>Accepter ou refuser en toute transparence.</li>
            </ul>
            <div className="consent-callout">
              <Info size={18} />
              <p>
                Vous pourrez révoquer ultérieurement ce consentement depuis votre compte Auth0 ou via les
                mécanismes prévus par votre établissement ou votre professionnel de santé.
              </p>
            </div>
          </section>

          <div className="consent-actions">
            <button
              type="button"
              className="login-button"
              onClick={handleContinue}
            >
              <LogIn size={20} />
              <span>Continuer vers Auth0</span>
            </button>
            <button
              type="button"
              className="secondary-button"
              onClick={() => navigate('/')}
            >
              <ArrowLeft size={18} />
              <span>Retour sans continuer</span>
            </button>
          </div>
        </div>
      </div>

      <footer className="login-footer">
        <p>© 2026 VitalIO - Télésurveillance Médicale IoT</p>
      </footer>
    </div>
  );
}

