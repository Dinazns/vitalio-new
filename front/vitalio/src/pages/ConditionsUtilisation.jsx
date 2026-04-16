import React from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'

export default function ConditionsUtilisation() {
  return (
    <div className="conditions-page">
      <header className="conditions-page__header">
        <Link to="/" className="conditions-page__back">
          <ArrowLeft size={18} aria-hidden />
          Retour à la connexion
        </Link>
        <h1 className="conditions-page__title">Conditions d&apos;utilisation</h1>
      </header>

      <main className="conditions-page__body">
        <section className="conditions-page__section">
          <h2>1. Objet</h2>
          <p>
            Les présentes conditions régissent l&apos;accès et l&apos;utilisation de la plateforme VitalIO,
            dédiée à la télésurveillance médicale et aux services numériques associés. En accédant à la plateforme,
            vous reconnaissez avoir pris connaissance des présentes conditions et les accepter sans réserve.
          </p>
        </section>

        <section className="conditions-page__section">
          <h2>2. Compte et sécurité</h2>
          <p>
            L&apos;authentification est assurée via un prestataire sécurisé (Auth0). Vous êtes responsable de la
            confidentialité de vos identifiants et de toute activité réalisée depuis votre compte. 
            Vous vous engagez à informer immédiatement l&apos;administrateur en cas d&apos;utilisation non autorisée
            de votre compte ou de toute faille de sécurité.
          </p>
        </section>

        <section className="conditions-page__section">
          <h2>3. Données de santé</h2>
          <p>
            VitalIO traite des données à caractère personnel, notamment des données de santé, dans le cadre
            du suivi médical assuré par des professionnels habilités. Ces traitements sont réalisés conformément
            à la réglementation en vigueur, notamment le RGPD et les dispositions applicables aux données de santé.
          </p>
          <p>
            Les données collectées sont strictement limitées à celles nécessaires au suivi médical et à l&apos;amélioration
            du service. Elles ne sont accessibles qu&apos;aux personnes autorisées dans le cadre de leurs fonctions.
          </p>
        </section>

        <section className="conditions-page__section">
          <h2>4. Traitement par intelligence artificielle</h2>
          <p>
            Dans le cadre de ses fonctionnalités, VitalIO peut recourir à des systèmes d&apos;intelligence artificielle
            afin d&apos;analyser certaines données de santé (par exemple : détection d&apos;anomalies, aide à l&apos;interprétation,
            priorisation des alertes).
          </p>
          <p>
            Ces traitements automatisés ont pour objectif d&apos;assister les professionnels de santé et ne se substituent
            en aucun cas à une décision médicale humaine. Toute décision médicale reste de la responsabilité exclusive
            d&apos;un professionnel de santé qualifié.
          </p>
        </section>

        <section className="conditions-page__section">
          <h2>5. Sécurité et séparation des données</h2>
          <p>
            VitalIO met en œuvre des mesures techniques et organisationnelles appropriées afin de garantir la sécurité,
            la confidentialité et l&apos;intégrité des données.
          </p>
          <p>
            Les données médicales sont stockées de manière sécurisée et sont strictement séparées des données
            d&apos;identité des utilisateurs. Cette séparation vise à limiter les risques d&apos;accès non autorisé
            et à renforcer la protection des informations sensibles.
          </p>
          <p>
            Des mécanismes de chiffrement, de contrôle d&apos;accès et de traçabilité sont mis en place afin de garantir
            un haut niveau de protection des données.
          </p>
        </section>

        <section className="conditions-page__section">
          <h2>6. Usage acceptable</h2>
          <p>
            Vous vous engagez à utiliser la plateforme conformément à sa finalité médicale et dans le respect
            des lois et réglementations applicables. Il est strictement interdit de :
          </p>
          <ul>
            <li>tenter d&apos;accéder de manière non autorisée aux systèmes ou aux données,</li>
            <li>perturber le fonctionnement du service,</li>
            <li>utiliser la plateforme à des fins frauduleuses ou illégales.</li>
          </ul>
        </section>

        <section className="conditions-page__section">
          <h2>7. Évolution du service</h2>
          <p>
            Les fonctionnalités de VitalIO peuvent évoluer afin d&apos;améliorer le service ou de répondre à des exigences
            réglementaires. Les présentes conditions peuvent être mises à jour à tout moment. La date de dernière
            révision sera indiquée sur cette page.
          </p>
        </section>

        <section className="conditions-page__section">
          <h2>8. Contact</h2>
          <p>
            Pour toute question relative à ces conditions ou au traitement de vos données, vous pouvez contacter
            l&apos;administrateur de votre espace VitalIO ou le responsable désigné par votre organisme de santé.
          </p>
        </section>
      </main>

      <footer className="conditions-page__footer">
        <Link to="/">Retour à la page de connexion</Link>
      </footer>
    </div>
  )
}