import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import CaregiverLayout from './components/CaregiverLayout';
import Login from './pages/Login';
import ConditionsUtilisation from './pages/ConditionsUtilisation';
import Home from './pages/Home';
import InviteAccept from './pages/InviteAccept';
import CaregiverInviteAccept from './pages/CaregiverInviteAccept';
import PatientView from './pages/PatientView';
import PatientProfileView from './pages/PatientProfileView';
import PatientMeasurement from './pages/PatientMeasurement';
import PatientMLView from './pages/PatientMLView';
import EnrollDevice from './pages/EnrollDevice';
import PatientWelcome from './pages/PatientWelcome';
import DoctorView from './pages/DoctorView';
import DoctorPatientDetail from './pages/DoctorPatientDetail';
import DoctorPatientML from './pages/DoctorPatientML';
import DoctorMLView from './pages/DoctorMLView';
import FamilyView from './pages/FamilyView';
import CaregiverPatientDetail from './pages/CaregiverPatientDetail';
import CaregiverPatientML from './pages/CaregiverPatientML';
import AdminView from './pages/AdminView';
import ProtectedRoute from './components/ProtectedRoute';
import RoleProtectedRoute from './components/RoleProtectedRoute';
function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Login />} />
      <Route path="/conditions-utilisation" element={<ConditionsUtilisation />} />
      <Route path="/invite" element={<InviteAccept />} />
      <Route path="/invite-caregiver" element={<CaregiverInviteAccept />} />
      <Route 
        path="/home" 
        element={
          <ProtectedRoute>
            <Home />
          </ProtectedRoute>
        } 
      />
      <Route
        path="/patient/onboarding"
        element={
          <ProtectedRoute>
            <RoleProtectedRoute allowedRoles={['patient']}>
              <Navigate to="/patient/bienvenue" replace />
            </RoleProtectedRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/patient/bienvenue"
        element={
          <ProtectedRoute>
            <RoleProtectedRoute allowedRoles={['patient']}>
              <PatientWelcome />
            </RoleProtectedRoute>
          </ProtectedRoute>
        }
      />
      <Route 
        path="/patient" 
        element={
          <ProtectedRoute>
            <RoleProtectedRoute allowedRoles={['patient']}>
              <PatientView />
            </RoleProtectedRoute>
          </ProtectedRoute>
        } 
      />
      <Route
        path="/patient/profile"
        element={
          <ProtectedRoute>
            <RoleProtectedRoute allowedRoles={['patient']}>
              <PatientProfileView />
            </RoleProtectedRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/patient/measure"
        element={
          <ProtectedRoute>
            <RoleProtectedRoute allowedRoles={['patient']}>
              <PatientMeasurement />
            </RoleProtectedRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/patient/ml"
        element={
          <ProtectedRoute>
            <RoleProtectedRoute allowedRoles={['patient']}>
              <PatientMLView />
            </RoleProtectedRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/patient/enroll-device"
        element={
          <ProtectedRoute>
            <RoleProtectedRoute allowedRoles={['patient']}>
              <EnrollDevice />
            </RoleProtectedRoute>
          </ProtectedRoute>
        }
      />
      <Route 
        path="/doctor" 
        element={
          <ProtectedRoute>
            <RoleProtectedRoute allowedRoles={['doctor', 'medecin', 'Superuser']}>
              <DoctorView />
            </RoleProtectedRoute>
          </ProtectedRoute>
        } 
      />
      <Route
        path="/doctor/alertes"
        element={
          <ProtectedRoute>
            <RoleProtectedRoute allowedRoles={['doctor', 'medecin', 'Superuser']}>
              <DoctorMLView />
            </RoleProtectedRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/doctor/patient/:patientId"
        element={
          <ProtectedRoute>
            <RoleProtectedRoute allowedRoles={['doctor', 'medecin', 'Superuser']}>
              <DoctorPatientDetail />
            </RoleProtectedRoute>
          </ProtectedRoute>
        } 
      />
      <Route
        path="/doctor/patient/:patientId/ml"
        element={
          <ProtectedRoute>
            <RoleProtectedRoute allowedRoles={['doctor', 'medecin', 'Superuser']}>
              <DoctorPatientML />
            </RoleProtectedRoute>
          </ProtectedRoute>
        }
      />
      <Route 
        path="/caregiver" 
        element={
          <ProtectedRoute>
            <RoleProtectedRoute allowedRoles={['caregiver', 'aidant']}>
              <CaregiverLayout />
            </RoleProtectedRoute>
          </ProtectedRoute>
        }
      >
        <Route index element={<FamilyView />} />
        <Route path="patient/:patientId" element={<CaregiverPatientDetail />} />
        <Route path="patient/:patientId/ml" element={<CaregiverPatientML />} />
      </Route>
      <Route 
        path="/family" 
        element={
          <ProtectedRoute>
            <RoleProtectedRoute allowedRoles={['caregiver', 'aidant']}>
              <CaregiverLayout />
            </RoleProtectedRoute>
          </ProtectedRoute>
        }
      >
        <Route index element={<FamilyView />} />
        <Route path="patient/:patientId" element={<CaregiverPatientDetail />} />
        <Route path="patient/:patientId/ml" element={<CaregiverPatientML />} />
      </Route>
      <Route 
        path="/admin" 
        element={
          <ProtectedRoute>
            <RoleProtectedRoute allowedRoles={['admin']}>
              <AdminView />
            </RoleProtectedRoute>
          </ProtectedRoute>
        } 
      />
    </Routes>
  );
}

export default function App() {
  return (
    <Router>
      <AppRoutes />
    </Router>
  );
}
