import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDownToLine, Bookmark, Check, Clock3, LoaderCircle, RefreshCw, Star, Trash2 } from "lucide-react";
import { DashboardRenderer } from "@/components/dashboard-widgets";
import { Button, Card, Input } from "@/components/ui";
import { dashboardApi } from "@/services/dashboard-api";
import { dashboardDefinition, savedDashboardApi } from "@/services/saved-dashboard-api";
import { erpApi } from "@/services/erp-api";
import type { Dashboard } from "@/types/dashboard";

const textAreaClass = "w-full rounded-xl border border-border bg-black/20 px-3.5 py-3 text-sm text-white outline-none focus:border-primary/70";

export function SavedDashboardsPage() {
  const queryClient = useQueryClient();
  const saved = useQuery({ queryKey: ["saved-dashboards"], queryFn: savedDashboardApi.list });
  const [selectedId, setSelectedId] = useState("");
  const [filterResetKey, setFilterResetKey] = useState(0);
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [titleDraft, setTitleDraft] = useState("");
  const [descriptionDraft, setDescriptionDraft] = useState("");
  const [questionDraft, setQuestionDraft] = useState("");
  const detail = useQuery({
    queryKey: ["saved-dashboard", selectedId],
    queryFn: () => savedDashboardApi.get(selectedId),
    enabled: Boolean(selectedId),
  });
  const selected = saved.data?.find((item) => item.id === selectedId);
  const versions = useQuery({
    queryKey: ["saved-dashboard-versions", selectedId],
    queryFn: () => savedDashboardApi.versions(selectedId),
    enabled: Boolean(selectedId),
  });
  const connections = useQuery({ queryKey: ["databases"], queryFn: erpApi.listConnections });
  const mappings = useQuery({
    queryKey: ["company-mappings", detail.data?.database_id],
    queryFn: () => erpApi.listCompanyMappings(detail.data!.database_id),
    enabled: Boolean(detail.data?.database_id),
  });

  useEffect(() => {
    if (!selectedId && saved.data?.length) setSelectedId(saved.data[0].id);
    if (selectedId && !saved.data?.some((item) => item.id === selectedId)) setSelectedId("");
  }, [saved.data, selectedId]);
  useEffect(() => {
    if (!detail.data) return;
    setTitleDraft(detail.data.title);
    setDescriptionDraft(detail.data.description);
    setQuestionDraft(detail.data.question);
  }, [detail.data]);

  const favorite = useMutation({
    mutationFn: ({ id, value }: { id: string; value: boolean }) => savedDashboardApi.favorite(id, value),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["saved-dashboards"] }),
  });
  const remove = useMutation({
    mutationFn: savedDashboardApi.delete,
    onSuccess: async (_, id) => {
      setSelectedId((current) => current === id ? "" : current);
      await queryClient.invalidateQueries({ queryKey: ["saved-dashboards"] });
    },
  });
  const restore = useMutation({
    mutationFn: ({ id, version }: { id: string; version: number }) => savedDashboardApi.restore(id, version),
    onSuccess: async () => {
      await refreshQueries(queryClient, selectedId);
    },
  });
  const rebuild = useMutation({
    mutationFn: async (input: { dashboard: Dashboard; expectedVersion: number; question: string; title: string; description: string }) => {
      const generated = await dashboardApi.generate({
        database_id: input.dashboard.database_id,
        ...(input.dashboard.company_mapping_id ? { company_mapping_id: input.dashboard.company_mapping_id } : {}),
        question: input.question,
      });
      return savedDashboardApi.update(
        selectedId,
        input.expectedVersion,
        { ...dashboardDefinition(generated), title: input.title, description: input.description },
      );
    },
    onSuccess: async () => {
      setFilters({});
      await refreshQueries(queryClient, selectedId);
    },
  });
  const exportFile = useMutation({
    mutationFn: ({ format }: { format: "xlsx" | "pdf" }) => savedDashboardApi.export(selectedId, format, filters),
    onSuccess: (blob, variables) => {
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${safeFilename(detail.data?.title ?? "dashboard")}.${variables.format}`;
      anchor.click();
      URL.revokeObjectURL(url);
    },
  });

  const connection = connections.data?.find((item) => item.id === detail.data?.database_id);
  const company = mappings.data?.find((item) => item.id === detail.data?.company_mapping_id);

  return <div className="space-y-6">
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div><div className="mb-2 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[.19em] text-violet-300"><Bookmark size={13} /> Phase 6 · Saved dashboards</div><h1 className="font-display text-3xl font-semibold tracking-[-.05em] text-white">Saved dashboards</h1><p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">Configurations are versioned in PostgreSQL. Every view and export rechecks access and queries the authorized data source again.</p></div>
      <div className="flex flex-wrap gap-2"><Button variant="secondary" size="small" onClick={() => exportFile.mutate({ format: "xlsx" })} disabled={!selectedId || exportFile.isPending}><ArrowDownToLine size={14} />Excel</Button><Button variant="secondary" size="small" onClick={() => exportFile.mutate({ format: "pdf" })} disabled={!selectedId || exportFile.isPending}><ArrowDownToLine size={14} />PDF</Button></div>
    </div>

    <div className="grid gap-5 xl:grid-cols-[.7fr_1.3fr]">
      <Card className="p-4 sm:p-5">
        <div className="mb-4 flex items-center justify-between"><h2 className="text-sm font-semibold text-white">Library</h2><span className="text-[10px] text-slate-600">{saved.data?.length ?? 0} saved</span></div>
        <div className="max-h-[650px] space-y-2 overflow-auto">
          {saved.data?.map((dashboard) => <div key={dashboard.id} className={`flex items-center gap-2 rounded-xl border p-3 ${dashboard.id === selectedId ? "border-violet-300/25 bg-violet-300/[.06]" : "border-white/[.06] bg-white/[.015]"}`}>
            <button className="min-w-0 flex-1 text-left" onClick={() => { setSelectedId(dashboard.id); setFilters({}); setFilterResetKey((value) => value + 1); }}><span className="block truncate text-xs font-medium text-slate-200">{dashboard.title}</span><span className="mt-1 block text-[10px] text-slate-600">v{dashboard.current_version} · {dashboard.question}</span></button>
            <button aria-label={dashboard.is_favorite ? "Remove favorite" : "Add favorite"} title={dashboard.is_favorite ? "Remove favorite" : "Add favorite"} onClick={() => favorite.mutate({ id: dashboard.id, value: !dashboard.is_favorite })} className="rounded-md p-1.5 text-amber-300 hover:bg-white/[.05]"><Star size={14} fill={dashboard.is_favorite ? "currentColor" : "none"} /></button>
            <button aria-label="Delete dashboard" title="Delete dashboard" onClick={() => remove.mutate(dashboard.id)} className="rounded-md p-1.5 text-slate-600 hover:bg-rose-300/10 hover:text-rose-200"><Trash2 size={13} /></button>
          </div>)}
          {!saved.isLoading && !saved.data?.length && <p className="rounded-xl border border-dashed border-white/[.08] p-5 text-xs leading-5 text-slate-600">No saved dashboards. Generate a dashboard in Dynamic Dashboards, then choose “Save dashboard”.</p>}
          {saved.isError && <ErrorBox message={errorMessage(saved.error)} />}
        </div>
      </Card>

      <div className="space-y-5">
        {detail.data && selected && <>
          <Card className="p-5">
            <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-sm font-semibold text-white">Dashboard settings & versions</h2><p className="mt-1 text-[10px] text-slate-600">{connection?.connection_name ?? "Authorized connection"}{company ? ` · ${company.company_name}` : " · Database default scope"} · version {selected.current_version}</p></div><span className="inline-flex items-center gap-1.5 text-[10px] text-slate-500"><Clock3 size={13} />Updated {new Date(selected.updated_at).toLocaleString()}</span></div>
            <div className="mt-4 grid gap-3 sm:grid-cols-2"><Field label="Dashboard title"><Input value={titleDraft} onChange={(event) => setTitleDraft(event.target.value)} /></Field><Field label="Refresh question"><Input value={questionDraft} onChange={(event) => setQuestionDraft(event.target.value)} /></Field><Field label="Description"><textarea className={textAreaClass} rows={2} value={descriptionDraft} onChange={(event) => setDescriptionDraft(event.target.value)} /></Field><div className="flex items-end"><Button onClick={() => rebuild.mutate({ dashboard: detail.data!, expectedVersion: selected.current_version, question: questionDraft, title: titleDraft, description: descriptionDraft })} disabled={rebuild.isPending || !questionDraft.trim() || !titleDraft.trim()} className="w-full">{rebuild.isPending ? <><LoaderCircle size={14} className="animate-spin" />Generating version…</> : <><RefreshCw size={14} />Generate & save new version</>}</Button></div></div>
            {rebuild.isError && <ErrorBox message={errorMessage(rebuild.error)} />}
            {restore.isError && <ErrorBox message={errorMessage(restore.error)} />}
            {exportFile.isError && <ErrorBox message={errorMessage(exportFile.error)} />}
            <div className="mt-5 border-t border-border pt-4"><h3 className="text-xs font-semibold text-slate-300">Version history</h3><div className="mt-2 flex flex-wrap gap-2">{versions.data?.items.map((version) => <span key={version.version_number} className="inline-flex items-center gap-2 rounded-lg border border-white/[.07] px-2.5 py-2 text-[10px] text-slate-400"><span>v{version.version_number} · {version.title}</span>{version.version_number === selected.current_version ? <Check size={12} className="text-emerald-300" /> : <button type="button" onClick={() => restore.mutate({ id: selected.id, version: version.version_number })} disabled={restore.isPending} className="text-violet-200 hover:text-white">Restore</button>}</span>)}{versions.isLoading && <LoaderCircle size={14} className="animate-spin text-slate-500" />}</div></div>
          </Card>
          <DashboardRenderer key={`${selected.id}-${selected.current_version}-${filterResetKey}`} dashboard={detail.data} onFiltersChange={setFilters} />
        </>}
        {detail.isLoading && selectedId && <Card className="flex items-center gap-3 p-8 text-sm text-slate-400"><LoaderCircle size={17} className="animate-spin text-violet-300" />Loading fresh authorized results…</Card>}
        {detail.isError && <ErrorBox message={errorMessage(detail.error)} />}
        {!selectedId && <Card className="flex min-h-56 items-center justify-center p-8 text-center text-xs text-slate-500">Select a saved dashboard to refresh its data and manage versions.</Card>}
      </div>
    </div>
  </div>;
}

async function refreshQueries(queryClient: ReturnType<typeof useQueryClient>, id: string) {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: ["saved-dashboards"] }),
    queryClient.invalidateQueries({ queryKey: ["saved-dashboard", id] }),
    queryClient.invalidateQueries({ queryKey: ["saved-dashboard-versions", id] }),
  ]);
}
function Field({ label, children }: { label: string; children: React.ReactNode }) { return <label className="block space-y-1.5 text-[10px] font-medium text-slate-500">{label}{children}</label>; }
function ErrorBox({ message }: { message: string }) { return <div role="alert" className="mt-3 rounded-xl border border-rose-300/10 bg-rose-300/[.04] p-3 text-xs text-rose-200">{message}</div>; }
function errorMessage(error: unknown) { if (typeof error === "object" && error !== null && "response" in error) { const detail = (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail; if (typeof detail === "string") return detail; if (detail && typeof detail === "object" && "message" in detail) return String((detail as { message: unknown }).message); } return "The request failed. Check access to the saved dashboard's database."; }
function safeFilename(value: string) { return value.replace(/[^a-z0-9_-]+/gi, "_").replace(/^_+|_+$/g, "").slice(0, 80) || "dashboard"; }
