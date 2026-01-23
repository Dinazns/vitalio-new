import React from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft, CheckCircle, AlertTriangle, Clock, User, Heart } from 'lucide-react';
import { EVENTS_TODAY, CURRENT_PATIENT } from '../data/mockData';

const TimelineEvent = ({ event, last }) => {
    const isWarning = event.type === 'warning';
    const isCheck = event.type === 'check';
    const typeClass = isWarning ? 'warning' : isCheck ? 'check' : 'info';

    return (
        <div className="timeline-event">
            <div className="marker-col">
                <div className={`marker ${typeClass}`}>
                    {isWarning ? <AlertTriangle size={18} /> : isCheck ? <CheckCircle size={18} /> : <Clock size={18} />}
                </div>
                {!last && <div className="line"></div>}
            </div>
            <div className="content-col">
                <div className="card">
                    <span className="time">{event.time}</span>
                    <h4 className={isWarning ? 'warning' : 'normal'}>{event.message}</h4>
                    <p>{event.details}</p>
                </div>
            </div>
        </div>
    );
};

export default function FamilyView() {
    const navigate = useNavigate();

    return (
        <div className="family-container family-theme">

            {/* Header Mobile Style */}
            <div className="family-header">
                <div className="top-bar">
                    <button onClick={() => navigate('/')} className="back-btn">
                        <ArrowLeft size={20} />
                    </button>
                    <span className="title">Profil de Robert</span>
                    <div className="w-10"></div> {/* Spacer */}
                </div>

                {/* Patient Profile Card */}
                <div className="profile-card">
                    <div className="bg-blob"></div>

                    <div className="info-row">
                        <div className="avatar">R</div>
                        <div className="details">
                            <h2>Papa</h2>
                            <p className="status">
                                <CheckCircle size={14} /> Stabilisé
                            </p>
                        </div>
                    </div>

                    <div className="footer-row">
                        <div>
                            <p className="label">Dernière mise à jour</p>
                            <p className="value">{CURRENT_PATIENT.lastUpdate}</p>
                        </div>
                        <div className="heart-icon">
                            <Heart size={20} className="animate-pulse" />
                        </div>
                    </div>
                </div>
            </div>

            {/* Timeline Section */}
            <div className="timeline-section">
                <h3>
                    <Clock size={20} className="icon" />
                    Journal d'aujourd'hui
                </h3>

                <div className="flex flex-col">
                    {EVENTS_TODAY.map((event, index) => (
                        <TimelineEvent
                            key={event.id}
                            event={event}
                            last={index === EVENTS_TODAY.length - 1}
                        />
                    ))}
                </div>
            </div>

            {/* Bottom Floating Action */}
            <div className="floating-action">
                <button>
                    <User size={20} /> Contacter Médecin
                </button>
            </div>

        </div>
    );
}
