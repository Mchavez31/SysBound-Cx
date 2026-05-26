import { useEffect } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import useAuthStore from './hooks/useAuthStore'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import ProjectsPage from './pages/ProjectsPage'
import ProjectLayout from './components/ProjectLayout'
import DashboardPage from './pages/DashboardPage'
import PalettesPage from './pages/PalettesPage'
import SubsystemsPage from './pages/SubsystemsPage'
import DrawingsPage from './pages/DrawingsPage'
import ComparisonPage from './pages/ComparisonPage'
import TagTrainingPage from './pages/TagTrainingPage'
import TagReportPage from './pages/TagReportPage'

function RequireAuth({ children }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  if (!isAuthenticated) return <Navigate to="/login" replace />
  return children
}

export default function App() {
  const initAuth = useAuthStore((s) => s.initAuth)
  useEffect(() => { initAuth() }, [initAuth])

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/projects" element={<RequireAuth><ProjectsPage /></RequireAuth>} />
      <Route path="/project/:projectId" element={<RequireAuth><ProjectLayout /></RequireAuth>}>
        <Route index element={<DashboardPage />} />
        <Route path="palettes" element={<PalettesPage />} />
        <Route path="subsystems" element={<SubsystemsPage />} />
        <Route path="drawings" element={<DrawingsPage />} />
        <Route path="tag-training" element={<TagTrainingPage />} />
        <Route path="tag-report" element={<TagReportPage />} />
        <Route path="comparison/:comparisonId" element={<ComparisonPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/projects" replace />} />
    </Routes>
  )
}
