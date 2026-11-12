import { useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { NavLink, useNavigate } from "react-router-dom";
import {
  Activity, ArrowUpRight, BookOpenText, Bookmark, ChevronDown, CircleHelp, Command,
  Database, LayoutDashboard, LogOut, MessageSquareText, Moon, MoreHorizontal, GitCompareArrows,
  Network, Settings2, ShieldCheck, Sparkles, Sun, Table2,
} from "lucide-react";
import { Card, StatusDot } from "@/components/ui";
import { authApi, systemApi } from "@/services/api";
import { erpApi } from "@/services/erp-api";
import { useAuthStore } from "@/stores/auth-store";
import { cn } from "@/lib/utils";

const workspaceNav = [
  { label: "AI Workspace", to: "/ai-workspace", icon: MessageSquareText },
  { label: "Database Connections", to: "/connections", icon: Database },
  { label: "Database Schema", to: "/schema", icon: Network },
  { label: "Company Mappings", to: "/company-mappings", icon: Table2 },
  { label: "Business Dictionary", to: "/business-dictionary", icon: BookOpenText },
  { label: "Dynamic Dashboards", to: "/dashboards", icon: LayoutDashboard },
  { label: "Conversations & Insights", to: "/analysis", icon: GitCompareArrows },
  { label: "Saved Dashboards", to: "/saved-dashboards", icon: Bookmark },
];

function SettingBadge({ ready, label }: { ready: boolean; label: string }) {
  return <span className={cn("inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium", ready ? "border-emerald-400/15 bg-emerald-400/[.07] text-emerald-300" : "border-amber-300/15 bg-amber-300/[.06] text-amber-200")}>
    <StatusDot tone={ready ? "good" : "warn"} />{label}
  </span>;
}

export function WorkspacePage({ children, title = "Overview" }: { children?: ReactNode; title?: string }) {
  const user = useAuthStore((state) => state.user);
  const setUser = useAuthStore((state) => state.setUser);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [light, setLight] = useState(() => window.localStorage.getItem("insightgpt-theme") === "light");
  const status = useQuery({ queryKey: ["system-status"], queryFn: systemApi.status, refetchInterval: 30_000 });
  const connections = useQuery({ queryKey: ["databases"], queryFn: erpApi.listConnections });
  const logout = useMutation({
    mutationFn: authApi.logout,
    onSettled: () => {
      setUser(null);
      queryClient.removeQueries({ queryKey: ["session"] });
      navigate("/login", { replace: true });
    },
  });

  const toggleTheme = () => {
    const next = !light;
    setLight(next);
    document.documentElement.classList.toggle("light", next);
    document.documentElement.classList.toggle("dark", !next);
    window.localStorage.setItem("insightgpt-theme", next ? "light" : "dark");
  };

  return (
    <div className="workspace-shell min-h-screen bg-background text-foreground">
      <aside className="sidebar fixed inset-y-0 left-0 z-20 hidden w-[252px] flex-col border-r border-border bg-[#0b0c12] lg:flex">
        <div className="flex h-[72px] items-center gap-3 border-b border-border px-5">
          <div className="brand-mark size-9 rounded-xl"><Sparkles size={17} /></div>
          <div className="leading-tight"><div className="font-display text-[15px] font-bold tracking-[-.045em] text-white">InsightGPT <span className="text-violet-300">AI</span></div><div className="mt-1 text-[9px] font-semibold uppercase tracking-[.2em] text-slate-600">Analytics platform</div></div>
          <button aria-label="Workspace menu" className="ml-auto rounded-lg p-1.5 text-slate-600 hover:bg-white/[.05] hover:text-slate-300"><MoreHorizontal size={16} /></button>
        </div>

        <div className="px-3 pt-5">
          <p className="sidebar-label px-3">WORKSPACE</p>
          <NavLink to="/" end className={({ isActive }) => cn("nav-item mt-2", isActive && "nav-item-active")}><LayoutDashboard size={16} /><span>Dashboard Home</span></NavLink>
          {workspaceNav.map(({ label, to, icon: Icon }) => <NavLink key={label} to={to} className={({ isActive }) => cn("nav-item", isActive && "nav-item-active")}><Icon size={16} /><span>{label}</span></NavLink>)}
        </div>

        <div className="mx-5 my-5 border-t border-border" />
        <div className="px-3">
          <p className="sidebar-label px-3">ADMINISTRATION</p>
          <div className="nav-item nav-item-disabled mt-2"><Settings2 size={16} /><span>Settings</span></div>
          <div className="nav-item nav-item-disabled"><ShieldCheck size={16} /><span>User Management</span><span className="ml-auto text-[9px] font-semibold text-slate-600">P1</span></div>
        </div>

        <div className="mt-auto p-3">
          <div className="phase-card rounded-2xl border border-violet-300/10 bg-gradient-to-br from-violet-500/[.10] to-indigo-500/[.035] p-4">
            <div className="flex items-center justify-between"><span className="rounded-md border border-violet-300/15 bg-violet-300/[.08] px-2 py-1 text-[9px] font-bold uppercase tracking-[.12em] text-violet-200">Phase 6</span><Activity size={14} className="text-violet-300/70" /></div>
            <p className="mt-3 text-xs font-semibold text-white">Saved dashboards are ready</p>
            <p className="mt-1 text-[11px] leading-[1.6] text-slate-500">Keep versioned views, favorites, and exportable live reports.</p>
            <div className="mt-3 h-1 overflow-hidden rounded-full bg-white/[.08]"><div className="h-full w-[86%] rounded-full bg-violet-400" /></div>
            <p className="mt-2 text-[9px] font-medium text-slate-600">6 OF 7 PHASES</p>
          </div>
          <button className="mt-3 flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left hover:bg-white/[.035]">
            <span className="flex size-8 items-center justify-center rounded-full bg-gradient-to-br from-indigo-400 to-violet-500 text-[11px] font-bold text-white">{user?.full_name?.slice(0, 1).toUpperCase() ?? "U"}</span>
            <span className="min-w-0 flex-1"><span className="block truncate text-xs font-semibold text-slate-200">{user?.full_name ?? "User"}</span><span className="mt-0.5 block truncate text-[10px] capitalize text-slate-600">{user?.role.replace("_", " ") ?? "Viewer"}</span></span>
            <ChevronDown size={14} className="text-slate-600" />
          </button>
        </div>
      </aside>

      <main className="lg:pl-[252px]">
        <header className="sticky top-0 z-10 flex h-[72px] items-center justify-between border-b border-border bg-background/90 px-5 backdrop-blur-xl sm:px-8">
          <div className="flex items-center gap-2 text-xs"><span className="text-slate-500">Workspace</span><span className="text-slate-700">/</span><span className="font-medium text-slate-200">{title}</span><span className="ml-2 hidden rounded-md border border-white/[.07] bg-white/[.03] px-2 py-1 text-[10px] text-slate-500 sm:inline-flex">Development</span></div>
          <div className="flex items-center gap-2 sm:gap-3">
            <button onClick={toggleTheme} className="icon-button" aria-label={light ? "Switch to dark theme" : "Switch to light theme"}>{light ? <Moon size={16} /> : <Sun size={16} />}</button>
            <button className="icon-button hidden sm:inline-flex" aria-label="Help"><CircleHelp size={16} /></button>
            <div className="mx-1 hidden h-6 w-px bg-border sm:block" />
            <button onClick={() => logout.mutate()} className="inline-flex h-9 items-center gap-2 rounded-lg px-2.5 text-xs font-medium text-slate-400 transition hover:bg-white/[.05] hover:text-white" disabled={logout.isPending}>
              <LogOut size={15} /><span className="hidden sm:inline">Sign out</span>
            </button>
            <span className="flex size-8 items-center justify-center rounded-full border border-white/[.1] bg-white/[.05] text-[11px] font-semibold text-slate-200 sm:hidden">{user?.full_name.slice(0, 1).toUpperCase()}</span>
          </div>
        </header>

        <div className="mx-auto max-w-[1450px] px-5 pb-12 pt-9 sm:px-8 sm:pt-11 xl:px-12">
          {children ?? <>
          <div className="flex flex-wrap items-end justify-between gap-5">
            <div>
              <div className="mb-3 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[.19em] text-violet-300"><span className="size-1.5 rounded-full bg-violet-300" /> INSIGHTGPT WORKSPACE</div>
              <h1 className="font-display text-[32px] font-semibold tracking-[-.055em] text-white sm:text-[38px]">Good to have you here<span className="text-violet-300">.</span></h1>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">Ask plain-language questions over SQL Server data with schema-aware SQL generation and validation.</p>
            </div>
            <div className="flex items-center gap-2 rounded-xl border border-border bg-white/[.025] px-3.5 py-2.5 text-xs text-slate-400"><Database size={14} className="text-violet-300" /><span>No company selected</span><ChevronDown size={13} className="ml-1 text-slate-600" /></div>
          </div>

          <div className="mt-8 grid gap-3 sm:grid-cols-3">
            <Card className="status-card p-4 sm:p-5">
              <div className="flex items-center justify-between"><span className="text-[10px] font-semibold uppercase tracking-[.14em] text-slate-500">Application database</span><Database size={15} className="text-slate-600" /></div>
              <div className="mt-4 flex items-center gap-2"><StatusDot tone={status.data?.database === "connected" ? "good" : status.isLoading ? "neutral" : "warn"} /><span className="font-display text-xl font-semibold tracking-tight text-white">{status.isLoading ? "Checking" : status.data?.database === "connected" ? "Connected" : "Unavailable"}</span></div>
              <p className="mt-1.5 text-[11px] text-slate-600">PostgreSQL metadata store</p>
            </Card>
            <Card className="status-card p-4 sm:p-5">
              <div className="flex items-center justify-between"><span className="text-[10px] font-semibold uppercase tracking-[.14em] text-slate-500">Model provider</span><Sparkles size={15} className="text-slate-600" /></div>
              <div className="mt-4"><SettingBadge ready={Boolean(status.data?.openrouter_configured && status.data.configured_model_count)} label={status.data?.openrouter_configured && status.data.configured_model_count ? "Configured" : "Setup needed"} /></div>
              <p className="mt-3 text-[11px] text-slate-600">OpenRouter · {status.data?.configured_model_count ?? 0} model assignment{status.data?.configured_model_count === 1 ? "" : "s"}</p>
            </Card>
            <Card className="status-card p-4 sm:p-5">
              <div className="flex items-center justify-between"><span className="text-[10px] font-semibold uppercase tracking-[.14em] text-slate-500">Analytics sources</span><Table2 size={15} className="text-slate-600" /></div>
              <div className="mt-4"><SettingBadge ready={Boolean(connections.data?.length)} label={connections.data?.length ? `${connections.data.length} available` : "No access yet"} /></div>
              <p className="mt-3 text-[11px] text-slate-600">Authorized SQL Server connections</p>
            </Card>
          </div>

          <div className="mt-7 grid gap-5 xl:grid-cols-[1.45fr_.75fr]">
            <Card className="welcome-panel relative min-h-[330px] overflow-hidden p-6 sm:p-8">
              <div className="absolute -right-14 -top-24 size-[360px] rounded-full border border-violet-300/[.07]" />
              <div className="absolute -right-2 -top-12 size-[260px] rounded-full border border-violet-300/[.08]" />
              <div className="absolute right-12 top-14 size-[130px] rounded-full border border-violet-300/[.1] bg-violet-400/[.025]" />
              <div className="relative max-w-xl">
                <div className="flex items-center gap-2 text-xs font-medium text-violet-200"><span className="flex size-7 items-center justify-center rounded-lg bg-violet-300/[.1]"><Sparkles size={14} /></span> Your AI workspace</div>
                <h2 className="mt-7 max-w-md font-display text-[27px] font-semibold leading-[1.18] tracking-[-.05em] text-white sm:text-[34px]">Your business data,<br />ready for a <span className="gradient-text">conversation.</span></h2>
                <p className="mt-4 max-w-md text-sm leading-6 text-slate-400">Connect a reporting database to ask questions in plain language and turn answers into clear, trusted insights.</p>
                <button onClick={() => navigate("/ai-workspace")} className="mt-7 inline-flex h-11 items-center gap-2 rounded-xl border border-violet-300/15 bg-violet-300/[.08] px-4 text-xs font-semibold text-violet-100 transition hover:bg-violet-300/[.14]">
                  <MessageSquareText size={15} /> Open AI Workspace <ArrowUpRight size={14} />
                </button>
              </div>
              <div className="relative mt-8 rounded-xl border border-white/[.07] bg-black/20 p-3.5 opacity-70 sm:mt-10">
                <div className="flex items-center gap-3 text-xs text-slate-600"><Command size={14} /><span>Ask a question about your business…</span><span className="ml-auto hidden rounded border border-white/[.07] px-1.5 py-1 text-[9px] sm:inline">↵</span></div>
                <div className="mt-3 border-t border-white/[.06] pt-3 text-[10px] text-slate-600">Connect a database to get started <span className="float-right">AI workspace · Phase 3</span></div>
              </div>
            </Card>

            <Card className="p-5 sm:p-6">
              <div className="flex items-center justify-between"><div><h2 className="font-display text-[15px] font-semibold tracking-tight text-white">Platform roadmap</h2><p className="mt-1 text-[11px] text-slate-600">The foundation, step by step</p></div><button aria-label="Roadmap options" className="rounded-lg p-1.5 text-slate-600 hover:bg-white/[.05]"><MoreHorizontal size={16} /></button></div>
              <div className="mt-6 space-y-3.5">
                <RoadmapItem index="01" title="Core foundation" note="Workspace, API & sign-in" state="complete" />
                <RoadmapItem index="02" title="Data connections" note="SQL Server & schema discovery" state="complete" />
                <RoadmapItem index="03" title="Natural language SQL" note="Ask, validate, explain" state="complete" />
                <RoadmapItem index="04" title="Dashboards & filters" note="Charts and safe exploration" state="complete" />
                <RoadmapItem index="05" title="Conversation & comparisons" note="Contextual follow-ups across companies" state="complete" />
                <RoadmapItem index="06" title="Saved views & exports" note="Dashboard versions, Excel and PDF" state="complete" />
                <RoadmapItem index="07" title="Production hardening" note="Testing, security and deployment" state="later" />
              </div>
              <div className="mt-6 border-t border-border pt-4"><div className="flex items-center justify-between text-[10px]"><span className="text-slate-500">Overall progress</span><span className="font-semibold text-slate-300">Phase 6 of 7</span></div><div className="mt-2.5 h-1 overflow-hidden rounded-full bg-white/[.06]"><div className="h-full w-[85.7%] rounded-full bg-gradient-to-r from-indigo-400 to-violet-300" /></div></div>
            </Card>
          </div>

          <footer className="mt-8 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-5 text-[10px] text-slate-600">
            <div className="flex items-center gap-2"><ShieldCheck size={13} className="text-emerald-500/70" /><span>Secure session · {user?.email}</span></div>
            <div className="flex items-center gap-4"><span className="inline-flex items-center gap-1.5"><StatusDot tone={status.isError ? "warn" : "good"} /> {status.isError ? "API unavailable" : "API online"}</span><span>InsightGPT AI · Phase 6</span></div>
          </footer>
          </>}
        </div>
      </main>
    </div>
  );
}

function RoadmapItem({ index, title, note, state }: { index: string; title: string; note: string; state: "complete" | "next" | "later" }) {
  return <div className="flex items-center gap-3.5">
    <span className={cn("flex size-8 shrink-0 items-center justify-center rounded-xl border text-[10px] font-semibold", state === "complete" ? "border-emerald-400/15 bg-emerald-400/[.07] text-emerald-300" : state === "next" ? "border-violet-300/20 bg-violet-300/[.08] text-violet-200" : "border-white/[.06] bg-white/[.025] text-slate-600")}>{state === "complete" ? "✓" : index}</span>
    <div className="min-w-0 flex-1"><p className={cn("truncate text-xs font-semibold", state === "later" ? "text-slate-500" : "text-slate-200")}>{title}</p><p className="mt-1 truncate text-[10px] text-slate-600">{note}</p></div>
    {state === "next" && <ArrowUpRight size={14} className="text-violet-300/70" />}
  </div>;
}
