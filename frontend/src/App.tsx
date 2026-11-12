import { lazy, Suspense, useEffect } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { LoaderCircle } from "lucide-react";
import { SignInPage } from "@/components/sign-in-page";
import {
  BusinessDictionaryPage,
  CompanyMappingsPage,
  DatabaseConnectionsPage,
  DatabaseSchemaPage,
} from "@/components/phase2-pages";
import { WorkspacePage } from "@/components/workspace-page";
import { TextToSQLPage } from "@/components/text-to-sql-page";
import { Phase5Page } from "@/components/phase5-page";
import { authApi } from "@/services/api";
import { useAuthStore } from "@/stores/auth-store";

const DashboardPage = lazy(() => import("@/components/dashboard-page").then((module) => ({ default: module.DashboardPage })));
const SavedDashboardsPage = lazy(() => import("@/components/saved-dashboards-page").then((module) => ({ default: module.SavedDashboardsPage })));

function LoadingScreen() {
  return <div className="flex min-h-screen items-center justify-center bg-background text-slate-400"><LoaderCircle className="animate-spin" size={20} /><span className="ml-3 text-sm">Loading workspace…</span></div>;
}

export default function App() {
  const setUser = useAuthStore((state) => state.setUser);
  const session = useQuery({ queryKey: ["session"], queryFn: authApi.me, retry: false, staleTime: 60_000 });

  useEffect(() => {
    if (session.data) setUser(session.data);
    if (session.isError) setUser(null);
  }, [session.data, session.isError, setUser]);

  if (session.isLoading) return <LoadingScreen />;

  return <Routes>
    <Route path="/login" element={session.data ? <Navigate to="/" replace /> : <SignInPage />} />
    <Route path="/" element={session.data ? <WorkspacePage /> : <Navigate to="/login" replace />} />
    <Route path="/ai-workspace" element={session.data ? <WorkspacePage title="AI Workspace"><TextToSQLPage /></WorkspacePage> : <Navigate to="/login" replace />} />
    <Route path="/dashboards" element={session.data ? <WorkspacePage title="Dynamic Dashboards"><Suspense fallback={<LoadingScreen />}><DashboardPage /></Suspense></WorkspacePage> : <Navigate to="/login" replace />} />
    <Route path="/saved-dashboards" element={session.data ? <WorkspacePage title="Saved Dashboards"><Suspense fallback={<LoadingScreen />}><SavedDashboardsPage /></Suspense></WorkspacePage> : <Navigate to="/login" replace />} />
    <Route path="/analysis" element={session.data ? <WorkspacePage title="Conversations & Comparisons"><Phase5Page /></WorkspacePage> : <Navigate to="/login" replace />} />
    <Route path="/connections" element={session.data ? <WorkspacePage title="Database Connections"><DatabaseConnectionsPage /></WorkspacePage> : <Navigate to="/login" replace />} />
    <Route path="/schema" element={session.data ? <WorkspacePage title="Database Schema"><DatabaseSchemaPage /></WorkspacePage> : <Navigate to="/login" replace />} />
    <Route path="/company-mappings" element={session.data ? <WorkspacePage title="Company Mappings"><CompanyMappingsPage /></WorkspacePage> : <Navigate to="/login" replace />} />
    <Route path="/business-dictionary" element={session.data ? <WorkspacePage title="Business Dictionary"><BusinessDictionaryPage /></WorkspacePage> : <Navigate to="/login" replace />} />
    <Route path="*" element={<Navigate to="/" replace />} />
  </Routes>;
}
