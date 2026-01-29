import React from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { useAuth0 } from '@auth0/auth0-react';
import Login from './pages/Login';
import Home from './pages/Home';
import PatientView from './pages/PatientView';
import DoctorView from './pages/DoctorView';
import FamilyView from './pages/FamilyView';
import AdminView from './pages/AdminView';
import Consent from './pages/Consent';
import ProtectedRoute from './components/ProtectedRoute';

function AppRoutes() {
  const { isAuthenticated } = useAuth0();

  return (
    <Routes>
      <Route path="/" element={<Login />} />
      <Route path="/consent" element={<Consent />} />
      <Route 
        path="/home" 
        element={
          <ProtectedRoute>
            <Home />
          </ProtectedRoute>
        } 
      />
      <Route 
        path="/patient" 
        element={
          <ProtectedRoute>
            <PatientView />
          </ProtectedRoute>
        } 
      />
      <Route 
        path="/doctor" 
        element={
          <ProtectedRoute>
            <DoctorView />
          </ProtectedRoute>
        } 
      />
      <Route 
        path="/family" 
        element={
          <ProtectedRoute>
            <FamilyView />
          </ProtectedRoute>
        } 
      />
      <Route 
        path="/admin" 
        element={
          <ProtectedRoute>
            <AdminView />
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
