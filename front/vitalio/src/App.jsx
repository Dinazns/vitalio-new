import React from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Login from './pages/Login';
import Home from './pages/Home';
import PatientView from './pages/PatientView';
import DoctorView from './pages/DoctorView';
import FamilyView from './pages/FamilyView';
import AdminView from './pages/AdminView';

export default function App() {
  return (
    <Router>
      <Routes>
        <Route path="/" element={<Login />} />
        <Route path="/home" element={<Home />} />
        <Route path="/patient" element={<PatientView />} />
        <Route path="/doctor" element={<DoctorView />} />
        <Route path="/family" element={<FamilyView />} />
        <Route path="/admin" element={<AdminView />} />
      </Routes>
    </Router>
  );
}
