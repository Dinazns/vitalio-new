import React from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import CaregiverLayout from './components/CaregiverLayout';
import Login from './pages/Login';
import Home from './pages/Home';
import InviteAccept from './pages/InviteAccept';
import CaregiverInviteAccept from './pages/CaregiverInviteAccept';
import PatientView from './pages/PatientView';
import PatientOnboarding from './pages/PatientOnboarding';
import PatientMeasurement from './pages/PatientMeasurement';
import PatientMLView from './pages/PatientMLView';
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
import PatientOnboardingGuard from './components/PatientOnboardingGuard';

function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Login />} />
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
              <PatientOnboardingGuard>
                <PatientOnboarding />
              </PatientOnboardingGuard>
            </RoleProtectedRoute>
          </ProtectedRoute>
        }
      />
      <Route 
        path="/patient" 
        element={
          <ProtectedRoute>
            <RoleProtectedRoute allowedRoles={['patient']}>
              <PatientOnboardingGuard>
                <PatientView />
              </PatientOnboardingGuard>
            </RoleProtectedRoute>
          </ProtectedRoute>
        } 
      />
      <Route
        path="/patient/measure"
        element={
          <ProtectedRoute>
            <RoleProtectedRoute allowedRoles={['patient']}>
              <PatientOnboardingGuard>
                <PatientMeasurement />
              </PatientOnboardingGuard>
            </RoleProtectedRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/patient/ml"
        element={
          <ProtectedRoute>
            <RoleProtectedRoute allowedRoles={['patient']}>
              <PatientOnboardingGuard>
                <PatientMLView />
              </PatientOnboardingGuard>
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
