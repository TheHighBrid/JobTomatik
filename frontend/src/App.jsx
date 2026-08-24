import { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from './store'
import Layout from './components/Layout'

const Dashboard = lazy(() => import('./pages/Dashboard'))
const CommandCenter = lazy(() => import('./pages/CommandCenter'))
const OperationsCenter = lazy(() => import('./pages/OperationsCenter'))
const SchedulerCenter = lazy(() => import('./pages/SchedulerCenter'))
const PostApplicationCenter = lazy(() => import('./pages/PostApplicationCenter'))
const CertificationCenter = lazy(() => import('./pages/CertificationCenter'))
const ShadowCampaignCenter = lazy(() => import('./pages/ShadowCampaignCenter'))
const RecoveryCenter = lazy(() => import('./pages/RecoveryCenter'))
const ExecutionCenter = lazy(() => import('./pages/ExecutionCenter'))
const HandoffReview = lazy(() => import('./pages/HandoffReview'))
const FollowUpReview = lazy(() => import('./pages/FollowUpReview'))
const JobSearch = lazy(() => import('./pages/JobSearch'))
const Queue = lazy(() => import('./pages/Queue'))
const Applications = lazy(() => import('./pages/Applications'))
const ApplicationDetail = lazy(() => import('./pages/ApplicationDetail'))
const EvidenceMaterials = lazy(() => import('./pages/EvidenceMaterials'))
const AdapterHealth = lazy(() => import('./pages/AdapterHealth'))
const Profile = lazy(() => import('./pages/Profile'))
const Settings = lazy(() => import('./pages/Settings'))
const Login = lazy(() => import('./pages/Login'))
const Register = lazy(() => import('./pages/Register'))

function PrivateRoute({ children }) {
  const token = useAuthStore((s) => s.token)
  return token ? children : <Navigate to="/login" replace />
}

export default function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<div className="p-6 text-sm text-gray-500">Loading…</div>}>
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
      </Suspense>
    </BrowserRouter>
  )
}
