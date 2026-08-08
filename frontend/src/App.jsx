import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from './store'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import CommandCenter from './pages/CommandCenter'
import OperationsCenter from './pages/OperationsCenter'
import SchedulerCenter from './pages/SchedulerCenter'
import PostApplicationCenter from './pages/PostApplicationCenter'
import CertificationCenter from './pages/CertificationCenter'
import ShadowCampaignCenter from './pages/ShadowCampaignCenter'
import RecoveryCenter from './pages/RecoveryCenter'
import ExecutionCenter from './pages/ExecutionCenter'
import HandoffReview from './pages/HandoffReview'
import FollowUpReview from './pages/FollowUpReview'
import JobSearch from './pages/JobSearch'
import Queue from './pages/Queue'
import Applications from './pages/Applications'
import ApplicationDetail from './pages/ApplicationDetail'
import EvidenceMaterials from './pages/EvidenceMaterials'
import AdapterHealth from './pages/AdapterHealth'
import Profile from './pages/Profile'
import Settings from './pages/Settings'
import Login from './pages/Login'
import Register from './pages/Register'

function PrivateRoute({ children }) {
  const token = useAuthStore((s) => s.token)
  return token ? children : <Navigate to="/login" replace />
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route
          path="/"
          element={
            <PrivateRoute>
              <Layout />
            </PrivateRoute>
          }
        >
          <Route index element={<Dashboard />} />
          <Route path="command-center" element={<CommandCenter />} />
          <Route path="operations" element={<OperationsCenter />} />
          <Route path="scheduler" element={<SchedulerCenter />} />
          <Route path="post-application" element={<PostApplicationCenter />} />
          <Route path="certification" element={<CertificationCenter />} />
          <Route path="shadow-campaigns" element={<ShadowCampaignCenter />} />
          <Route path="recovery" element={<RecoveryCenter />} />
          <Route path="execution" element={<ExecutionCenter />} />
          <Route path="handoff-review" element={<HandoffReview />} />
          <Route path="followup-review" element={<FollowUpReview />} />
          <Route path="search" element={<JobSearch />} />
          <Route path="queue" element={<Queue />} />
          <Route path="applications" element={<Applications />} />
          <Route path="applications/:id" element={<ApplicationDetail />} />
          <Route path="evidence-materials" element={<EvidenceMaterials />} />
          <Route path="adapter-health" element={<AdapterHealth />} />
          <Route path="profile" element={<Profile />} />
          <Route path="settings" element={<Settings />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}