export const CURRENT_PATIENT = {
  id: "P001",
  name: "Robert",
  age: 78,
  status: "stable", // stable, warning, critical
  vitals: {
    heartRate: { value: 72, unit: "bpm", status: "normal", trend: "stable" },
    spo2: { value: 96, unit: "%", status: "normal", trend: "down" },
    temperature: { value: 36.8, unit: "°C", status: "normal", trend: "stable" }
  },
  lastUpdate: "Il y a 10 min"
};

export const PATIENTS_LIST = [
  { id: 1, name: "Robert", age: 78, riskScore: 15, heartRate: 72, spo2: 96, status: "Normal" },
  { id: 2, name: "Maria", age: 82, riskScore: 45, heartRate: 88, spo2: 94, status: "A surveiller" },
  { id: 3, name: "Jean", age: 65, riskScore: 85, heartRate: 110, spo2: 89, status: "Critique" },
  { id: 4, name: "Sophie", age: 71, riskScore: 10, heartRate: 68, spo2: 98, status: "Normal" },
  { id: 5, name: "Pierre", age: 76, riskScore: 30, heartRate: 75, spo2: 95, status: "Stable" },
];

export const VITALS_HISTORY = [
  { time: "08:00", heartRate: 70, spo2: 97 },
  { time: "09:00", heartRate: 72, spo2: 97 },
  { time: "10:00", heartRate: 75, spo2: 96 },
  { time: "11:00", heartRate: 71, spo2: 96 },
  { time: "12:00", heartRate: 69, spo2: 98 },
  { time: "13:00", heartRate: 74, spo2: 95 },
  { time: "14:00", heartRate: 72, spo2: 96 },
];

export const EVENTS_TODAY = [
  { id: 1, time: "08:00", type: "info", message: "Prise de mesure automatique", details: "Tous les indicateurs sont normaux." },
  { id: 2, time: "08:30", type: "check", message: "Prise médicament", details: "Validé par le patient." },
  { id: 3, time: "12:15", type: "warning", message: "SpO2 légèrement bas", details: "94% détecté. Retour à la normale à 12:20." },
  { id: 4, time: "14:00", type: "info", message: "Visite infirmière", details: "Rapport: Tout va bien." },
];

export const SENSORS_STATUS = [
  { id: "S-101", type: "Oxymètre", location: "Chambre", battery: 85, signal: 90, status: "online" },
  { id: "S-102", type: "Cardio", location: "Poignet", battery: 12, signal: 95, status: "warning" },
  { id: "S-103", type: "Hub Central", location: "Salon", battery: 100, signal: 100, status: "online" },
  { id: "S-104", type: "Tensiomètre", location: "Salle de bain", battery: 0, signal: 0, status: "offline" },
];
