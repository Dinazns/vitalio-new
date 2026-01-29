import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth0 } from '@auth0/auth0-react';
import { Activity, ArrowLeft, AlertCircle, LogOut } from 'lucide-react';
import { CURRENT_PATIENT } from '../data/mockData';
import { getPatientData, getMyDevice, pairUserDevice } from '../services/api';

const AUDIENCE = import.meta.env.VITE_AUTH0_AUDIENCE || 'auth';

export default function PatientView() {
    const navigate = useNavigate();
    const { logout, user, isAuthenticated, getAccessTokenSilently, loginWithRedirect } = useAuth0();
    const [sosActive, setSosActive] = useState(false);
    const [sosTimer, setSosTimer] = useState(0);
    const [measuring, setMeasuring] = useState(false);
    
    // Device/sensor state: null = none, object = current device
    const [device, setDevice] = useState(null);
    const [deviceLoading, setDeviceLoading] = useState(true);
    const [newSensorSerial, setNewSensorSerial] = useState('');
    const [addSensorError, setAddSensorError] = useState(null);
    const [addSensorSubmitting, setAddSensorSubmitting] = useState(false);

    // Measurement History state
    const [measurements, setMeasurements] = useState([]);
    const [measurementsLoading, setMeasurementsLoading] = useState(true);
    const [measurementsError, setMeasurementsError] = useState(null);
    const [showAllMeasurements, setShowAllMeasurements] = useState(false);

    // Current time state
    const [currentTime, setCurrentTime] = useState(new Date());
    
    // Format date/time in a user-friendly way using timestamp column
    const formatDateTime = (dateString) => {
        if (!dateString) return 'N/A';
        
        const date = new Date(dateString);
        const now = new Date();
        const diffMs = now - date;
        const diffMins = Math.floor(diffMs / 60000);
        const diffHours = Math.floor(diffMs / 3600000);
        const diffDays = Math.floor(diffMs / 86400000);
        
        // Format: "Aujourd'hui à 14:30" or "il y a 2 heures" or "27 jan 2026 à 14:30"
        const timeStr = date.toLocaleTimeString('fr-FR', {
            hour: '2-digit',
            minute: '2-digit',
            hour12: false
        });
        
        if (diffMins < 1) {
            return `À l'instant (${timeStr})`;
        } else if (diffMins < 60) {
            return `Il y a ${diffMins} min (${timeStr})`;
        } else if (diffHours < 24) {
            return `Il y a ${diffHours} ${diffHours === 1 ? 'heure' : 'heures'} (${timeStr})`;
        } else if (diffDays === 1) {
            return `Hier à ${timeStr}`;
        } else if (diffDays < 7) {
            return `Il y a ${diffDays} ${diffDays === 1 ? 'jour' : 'jours'} (${date.toLocaleDateString('fr-FR', { month: 'short', day: 'numeric' })} ${timeStr})`;
        } else {
            return date.toLocaleDateString('fr-FR', {
                month: 'short',
                day: 'numeric',
                year: 'numeric'
            }) + ` à ${timeStr}`;
        }
    };
    
    // Determine medical status: 'normal' (green), 'warning' (orange), 'critical' (red)
    const getMedicalStatus = (measurement) => {
        let hasCritical = false;
        let hasWarning = false;
        
        // Heart Rate: Normal 60-100 bpm
        if (measurement.heart_rate != null) {
            const hr = measurement.heart_rate;
            if (hr < 50 || hr > 120) {
                hasCritical = true;
            } else if (hr < 60 || hr > 100) {
                hasWarning = true;
            }
        }
        
        // Temperature: Normal 36.1-37.2°C
        if (measurement.temperature != null) {
            const temp = Number(measurement.temperature);
            if (temp < 35.5 || temp > 38.0) {
                hasCritical = true;
            } else if (temp < 36.1 || temp > 37.2) {
                hasWarning = true;
            }
        }
        
        // SpO2: Normal 95-100%
        if (measurement.spo2 != null) {
            const spo2 = measurement.spo2;
            if (spo2 < 90) {
                hasCritical = true;
            } else if (spo2 < 95) {
                hasWarning = true;
            }
        }
        
        if (hasCritical) return 'critical';
        if (hasWarning) return 'warning';
        return 'normal';
    };
    
    // Filter measurements (show last 20 by default, or all if showAllMeasurements is true)
    const displayedMeasurements = showAllMeasurements 
        ? measurements 
        : measurements.slice(0, 20);
    
    // Get user's display name - prefer username, fallback to nickname, then extract from email
    const getUserName = () => {
        if (user?.username) return user.username;
        if (user?.nickname) return user.nickname;
        // Extract username from email (part before @)
        if (user?.email) {
            const emailParts = user.email.split('@');
            return emailParts[0];
        }
        return 'Patient';
    };
    const userName = getUserName();
    
    // Get last measurement time for "Dernière maj"
    const getLastUpdateText = () => {
        if (measurements.length === 0) {
            return 'Aucune mesure';
        }
        
        const lastMeasurement = measurements[0]; // Already sorted by timestamp DESC
        if (!lastMeasurement?.timestamp) {
            return 'Aucune mesure';
        }
        
        const lastTime = new Date(lastMeasurement.timestamp);
        const now = new Date();
        const diffMs = now - lastTime;
        const diffHours = Math.floor(diffMs / 3600000);
        
        // If less than 24 hours, show relative time
        if (diffHours < 24) {
            return formatDateTime(lastMeasurement.timestamp);
        } else {
            // If more than 24 hours, show date
            return lastTime.toLocaleDateString('fr-FR', {
                day: 'numeric',
                month: 'short',
                year: 'numeric',
                hour: '2-digit',
                minute: '2-digit'
            });
        }
    };
    
    // Update current time every minute
    useEffect(() => {
        // Set initial time
        setCurrentTime(new Date());
        
        // Update every minute
        const timer = setInterval(() => {
            setCurrentTime(new Date());
        }, 60000); // Update every minute
        
        return () => clearInterval(timer);
    }, []);

    const handleDisconnect = () => {
        logout({
            logoutParams: {
                returnTo: window.location.origin,
            },
        });
        // Clear local storage
        localStorage.removeItem('vitalio_user');
    };

    // SOS Logic: Hold for 3 seconds
    useEffect(() => {
        let interval;
        if (sosActive) {
            interval = setInterval(() => {
                setSosTimer(prev => {
                    if (prev >= 100) return 100;
                    return prev + 2; // fills in ~1-2 seconds
                });
            }, 20);
        } else {
            setSosTimer(0);
        }
        return () => clearInterval(interval);
    }, [sosActive]);

    useEffect(() => {
        if (sosTimer >= 100) {
            alert("ALERTE SOS ENVOYÉE AUX URGENCES !");
            setSosActive(false);
            setSosTimer(0);
        }
    }, [sosTimer]);

    // Fetch device (capteur) for current user
    useEffect(() => {
        const fetchDevice = async () => {
            if (!isAuthenticated || !user) {
                setDeviceLoading(false);
                setDevice(null);
                return;
            }
            setDeviceLoading(true);
            try {
                let token;
                try {
                    token = await getAccessTokenSilently({
                        authorizationParams: { audience: AUDIENCE, scope: 'openid profile email read:patient_data' },
                    });
                } catch (e) {
                    if (e?.error === 'consent_required' || e?.error === 'login_required' || e?.error === 'interaction_required') {
                        await loginWithRedirect({
                            authorizationParams: { audience: AUDIENCE, scope: 'openid profile email read:patient_data' },
                            appState: { returnTo: '/patient' },
                        });
                        return;
                    }
                    setDevice(null);
                    setDeviceLoading(false);
                    return;
                }
                const dev = await getMyDevice(token);
                setDevice(dev);
            } catch (err) {
                console.error('Error fetching device:', err);
                setDevice(null);
            } finally {
                setDeviceLoading(false);
            }
        };
        fetchDevice();
    }, [isAuthenticated, user, getAccessTokenSilently, loginWithRedirect]);

    // Fetch Measurement History via l'API (only when user has a device)
    useEffect(() => {
        const fetchMeasurements = async () => {
            if (!isAuthenticated || !user) {
                setMeasurementsLoading(false);
                setMeasurementsError('Veuillez vous connecter pour voir les mesures');
                return;
            }
            if (!device) {
                setMeasurements([]);
                setMeasurementsError(null);
                setMeasurementsLoading(false);
                return;
            }

            setMeasurementsLoading(true);
            setMeasurementsError(null);

            try {
                let token;
                try {
                    token = await getAccessTokenSilently({
                        authorizationParams: { audience: AUDIENCE, scope: 'openid profile email read:patient_data' },
                    });
                } catch (e) {
                    if (e?.error === 'consent_required' || e?.error === 'login_required' || e?.error === 'interaction_required') {
                        await loginWithRedirect({
                            authorizationParams: {
                                audience: AUDIENCE,
                                scope: 'openid profile email read:patient_data',
                            },
                            appState: { returnTo: '/patient' },
                        });
                        return;
                    }
                    setMeasurementsError('Impossible d\'obtenir un token pour charger les mesures.');
                    setMeasurements([]);
                    setMeasurementsLoading(false);
                    return;
                }

                const apiData = await getPatientData(token);
                const list = apiData?.measurements ?? [];
                setMeasurements(Array.isArray(list) ? list : []);
            } catch (err) {
                console.error('Error fetching measurements:', err);
                const msg = err instanceof Error ? err.message : 'Échec du chargement des mesures';
                setMeasurementsError(msg);
                setMeasurements([]);
            } finally {
                setMeasurementsLoading(false);
            }
        };

        fetchMeasurements();
    }, [isAuthenticated, user, getAccessTokenSilently, loginWithRedirect, device]);

    const handleMeasure = () => {
        setMeasuring(true);
        setTimeout(() => {
            setMeasuring(false);
            alert("Mesure envoyée avec succès !");
        }, 2000);
    };

    const handleAddSensor = async (e) => {
        e.preventDefault();
        const serial = newSensorSerial?.trim();
        if (!serial) {
            setAddSensorError('Veuillez saisir le numéro de série du capteur.');
            return;
        }
        if (!isAuthenticated || !user) return;
        setAddSensorError(null);
        setAddSensorSubmitting(true);
        try {
            const token = await getAccessTokenSilently({
                authorizationParams: { audience: AUDIENCE, scope: 'openid profile email read:patient_data' },
            });
            const { status, data } = await pairUserDevice(token, serial);
            if (status === 201 || status === 200) {
                setDevice({
                    device_id: data?.device_id,
                    serial_number: data?.serial_number ?? serial,
                    mqtt_topic: data?.mqtt_topic,
                });
                setNewSensorSerial('');
            } else if (status === 409) {
                setAddSensorError('Ce capteur est déjà associé à un autre utilisateur.');
            } else if (status === 400) {
                setAddSensorError(data?.error || 'Numéro de série invalide.');
            } else {
                setAddSensorError(data?.message || 'Impossible d\'associer le capteur.');
            }
        } catch (err) {
            console.error('Error pairing device:', err);
            setAddSensorError(err instanceof Error ? err.message : 'Erreur lors de l\'association.');
        } finally {
            setAddSensorSubmitting(false);
        }
    };

    return (
        <div className="patient-container patient-theme">
            {/* Navigation Simpifiée */}
            <button
                onClick={() => navigate('/')}
                className="back-button"
            >
                <ArrowLeft size={32} />
            </button>

            {/* Disconnect Button */}
            <button
                onClick={handleDisconnect}
                className="disconnect-button"
                title="Déconnexion"
            >
                <LogOut size={24} />
            </button>

            <div className="content-wrapper">

                {/* Header Patient */}
                <div className="patient-header">
                    <h1>Bonjour, {userName}</h1>
                    <p className="time-display">
                        {currentTime.toLocaleTimeString('fr-FR', {
                            hour: '2-digit',
                            minute: '2-digit',
                            hour12: false
                        })}
                    </p>
                </div>

                {/* Zone de saisie du capteur : visible uniquement si l'utilisateur n'a pas encore de capteur */}
                {!deviceLoading && !device && (
                    <div className="add-sensor-section">
                        <h2 className="add-sensor-title">Ajouter un capteur</h2>
                        <p className="add-sensor-hint">Saisissez le numéro de série de votre capteur pour l'associer à votre compte.</p>
                        <form onSubmit={handleAddSensor} className="add-sensor-form">
                            <input
                                type="text"
                                value={newSensorSerial}
                                onChange={(e) => { setNewSensorSerial(e.target.value); setAddSensorError(null); }}
                                placeholder="Ex. SIM-ESP32-001"
                                className="add-sensor-input"
                                disabled={addSensorSubmitting}
                                autoComplete="off"
                            />
                            <button
                                type="submit"
                                disabled={addSensorSubmitting || !newSensorSerial?.trim()}
                                className="add-sensor-button"
                            >
                                {addSensorSubmitting ? 'Association...' : 'Associer le capteur'}
                            </button>
                        </form>
                        {addSensorError && (
                            <p className="add-sensor-error">{addSensorError}</p>
                        )}
                    </div>
                )}

                {/* Status Indicator Giant */}
                <div className={`status-indicator ${CURRENT_PATIENT.status === 'stable' ? 'status-stable' : 'status-warning'}`}>
                    <Activity size={64} className="mb-4 animate-pulse" />
                    <span className="main-text">{CURRENT_PATIENT.status === 'stable' ? 'TOUT VA BIEN' : 'ATTENTION'}</span>
                    <span className="sub-text">Dernière maj: {getLastUpdateText()}</span>
                </div>

                {/* Actions Grid */}
                <div className="actions-grid">

                    {/* Prise de Mesure */}
                    <button
                        onClick={handleMeasure}
                        disabled={measuring}
                        className={`measure-button ${measuring ? 'measuring' : ''}`}
                    >
                        {measuring ? (
                            <>En cours...</>
                        ) : (
                            <>
                                <div className="icon-box"><Activity size={32} /></div>
                                Prendre Mesures
                            </>
                        )}
                    </button>

                    {/* SOS Button Long Press */}
                    <button
                        onMouseDown={() => setSosActive(true)}
                        onMouseUp={() => setSosActive(false)}
                        onMouseLeave={() => setSosActive(false)}
                        onTouchStart={() => setSosActive(true)}
                        onTouchEnd={() => setSosActive(false)}
                        className="sos-button"
                    >
                        <div
                            className="progress-bar"
                            style={{ width: `${sosTimer}%` }}
                        />
                        <div className="content">
                            <AlertCircle size={48} className="mb-2" />
                            <span className="sos-text">SOS</span>
                            <span className="sos-hint">MAINTENIR POUR APPELER</span>
                        </div>
                    </button>

                </div>

                {/* Measurement History Section */}
                <div className="measurement-history-section">
                    <div className="measurement-history-header">
                        <h2 className="measurement-history-title">Historique des Mesures</h2>
                        {measurements.length > 0 && (
                            <span className="measurement-count">
                                {measurements.length} {measurements.length === 1 ? 'mesure' : 'mesures'}
                            </span>
                        )}
                    </div>
                    
                    {measurementsLoading ? (
                        <div className="measurement-history-loading">
                            <p>Chargement des mesures...</p>
                        </div>
                    ) : measurementsError ? (
                        <div className="measurement-history-error">
                            <p>Erreur : {measurementsError}</p>
                        </div>
                    ) : measurements.length === 0 ? (
                        <div className="measurement-history-empty">
                            <p>Aucune mesure disponible</p>
                        </div>
                    ) : (
                        <>
                            <div className="measurement-history-table-container">
                                <table className="measurement-history-table">
                                    <thead>
                                        <tr>
                                            <th>Date et Heure</th>
                                            <th>Température</th>
                                            <th>Fréquence Cardiaque</th>
                                            <th>SpO₂</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {displayedMeasurements.map((measurement, index) => {
                                            const status = getMedicalStatus(measurement);
                                            return (
                                                <tr key={measurement.id ?? `m-${index}-${measurement.timestamp ?? ''}`} className={`measurement-row measurement-row-${status}`}>
                                                    <td className="measurement-time">
                                                        {formatDateTime(measurement.timestamp)}
                                                    </td>
                                                    <td className="measurement-value">
                                                        {measurement.temperature != null 
                                                            ? (
                                                                <span className="value-with-unit">
                                                                    <span className="value">{Number(measurement.temperature).toFixed(1)}</span>
                                                                    <span className="unit">°C</span>
                                                                </span>
                                                            )
                                                            : <span className="no-value">—</span>}
                                                    </td>
                                                    <td className="measurement-value">
                                                        {measurement.heart_rate != null 
                                                            ? (
                                                                <span className="value-with-unit">
                                                                    <span className="value">{measurement.heart_rate}</span>
                                                                    <span className="unit"> bpm</span>
                                                                </span>
                                                            )
                                                            : <span className="no-value">—</span>}
                                                    </td>
                                                    <td className="measurement-value">
                                                        {measurement.spo2 != null 
                                                            ? (
                                                                <span className="value-with-unit">
                                                                    <span className="value">{measurement.spo2}</span>
                                                                    <span className="unit">%</span>
                                                                </span>
                                                            )
                                                            : <span className="no-value">—</span>}
                                                    </td>
                                                </tr>
                                            );
                                        })}
                                    </tbody>
                                </table>
                            </div>
                            
                            {measurements.length > 20 && (
                                <div className="measurement-history-footer">
                                    <button
                                        onClick={() => setShowAllMeasurements(!showAllMeasurements)}
                                        className="show-more-button"
                                    >
                                        {showAllMeasurements 
                                            ? `Afficher moins` 
                                            : `Afficher toutes les ${measurements.length} mesures`}
                                    </button>
                                </div>
                            )}
                        </>
                    )}
                </div>
            </div>
        </div>
    );
}
