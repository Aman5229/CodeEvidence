import { lazy } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router'
import { AppShell } from './components/layout/AppShell'
import { Empty } from './components/ui/States'

// Each page is its own chunk, loaded when first opened: the PR page (with the diff viewer and
// syntax highlighting) costs nothing until someone opens a pull request.
const OverviewPage = lazy(() => import('./pages/OverviewPage').then((module) => ({ default: module.OverviewPage })))
const RepositoriesPage = lazy(() => import('./pages/RepositoriesPage').then((module) => ({ default: module.RepositoriesPage })))
const RepositoryPage = lazy(() => import('./pages/RepositoryPage').then((module) => ({ default: module.RepositoryPage })))
const PullRequestPage = lazy(() => import('./pages/PullRequestPage').then((module) => ({ default: module.PullRequestPage })))
const JobsPage = lazy(() => import('./pages/JobsPage').then((module) => ({ default: module.JobsPage })))
const SettingsPage = lazy(() => import('./pages/SettingsPage').then((module) => ({ default: module.SettingsPage })))

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/" element={<OverviewPage />} />
          <Route path="/repositories" element={<RepositoriesPage />} />
          <Route path="/repositories/:repositoryId" element={<RepositoryPage />} />
          <Route path="/pull-requests/:pullRequestId" element={<PullRequestPage />} />
          <Route path="/jobs" element={<JobsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<Empty title="Page not found" />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
