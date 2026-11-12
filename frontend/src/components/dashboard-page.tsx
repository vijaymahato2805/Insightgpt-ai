import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { AlertCircle, BarChart3, Bookmark, Database, LoaderCircle, RefreshCw, Sparkles } from "lucide-react";
import { DashboardRenderer } from "@/components/dashboard-widgets";
import { Button, Card } from "@/components/ui";
import { dashboardApi } from "@/services/dashboard-api";
import { erpApi } from "@/services/erp-api";
import { savedDashboardApi } from "@/services/saved-dashboard-api";

const suggestions = [
  "Build a sales overview with monthly trends, top item categories, and headline sales quantity for MTD",
  "Show inventory value and item quantities by location, with a breakdown by item category",
  "Create a customer sales dashboard with quarterly trends and top customers",
];

export function DashboardPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const connections = useQuery({ queryKey: ["databases"], queryFn: erpApi.listConnections });
  const [databaseId, setDatabaseId] = useState("");
  const [companyMappingId, setCompanyMappingId] = useState("");
  const [question, setQuestion] = useState("");
  const mappings = useQuery({
    queryKey: ["company-mappings", databaseId],
    queryFn: () => erpApi.listCompanyMappings(databaseId),
    enabled: Boolean(databaseId),
  });
  const generate = useMutation({ mutationFn: dashboardApi.generate });
  const save = useMutation({
    mutationFn: savedDashboardApi.create,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["saved-dashboards"] });
      navigate("/saved-dashboards");
    },
  });

  useEffect(() => {
    if (!databaseId && connections.data?.length) setDatabaseId(connections.data[0].id);
  }, [connections.data, databaseId]);

  useEffect(() => {
    if (companyMappingId && !mappings.data?.some((mapping) => mapping.id === companyMappingId)) {
      setCompanyMappingId("");
    }
  }, [companyMappingId, mappings.data]);

  const selectedConnection = connections.data?.find((item) => item.id === databaseId);
  const submit = (prompt = question) => {
    if (!databaseId || !prompt.trim()) return;
    setQuestion(prompt);
    generate.mutate({
      database_id: databaseId,
      ...(companyMappingId ? { company_mapping_id: companyMappingId } : {}),
      question: prompt.trim(),
    });
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="mb-2 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[.19em] text-violet-300"><BarChart3 size={13} /> Phase 4 · Dynamic dashboards</div>
          <h1 className="font-display text-3xl font-semibold tracking-[-.05em] text-white">Build a dashboard from a question</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">Describe the business view you need. Every card and chart is backed by a generated, validated, and executed SQL query.</p>
        </div>
        <div className="flex items-center gap-2 rounded-xl border border-emerald-300/10 bg-emerald-300/[.04] px-3 py-2 text-[11px] text-emerald-200"><Database size={14} /> Live authorized query results</div>
      </div>

      <Card className="p-5 sm:p-6">
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block space-y-2 text-xs font-medium text-slate-400">Database connection
            <select value={databaseId} onChange={(event) => { setDatabaseId(event.target.value); setCompanyMappingId(""); generate.reset(); }} className="h-11 w-full rounded-xl border border-border bg-[#11131c] px-3.5 text-sm text-foreground outline-none focus:border-primary/70" disabled={connections.isLoading}>
              <option value="">Select an authorized database</option>
              {connections.data?.map((item) => <option key={item.id} value={item.id}>{item.connection_name} · {item.database}</option>)}
            </select>
          </label>
          <label className="block space-y-2 text-xs font-medium text-slate-400">Company scope
            <select value={companyMappingId} onChange={(event) => { setCompanyMappingId(event.target.value); generate.reset(); }} className="h-11 w-full rounded-xl border border-border bg-[#11131c] px-3.5 text-sm text-foreground outline-none focus:border-primary/70" disabled={!databaseId || mappings.isLoading}>
              <option value="">Use database scope</option>
              {mappings.data?.map((item) => <option key={item.id} value={item.id}>{item.company_name}</option>)}
            </select>
          </label>
        </div>
        {connections.isError && <ErrorBox message="Could not load database connections." />}
        {!connections.isLoading && !connections.isError && !connections.data?.length && <div className="mt-4 rounded-xl border border-amber-200/10 bg-amber-200/[.035] p-3 text-xs text-amber-100">No database connections are available to your account. Ask an administrator to grant database access.</div>}

        <label className="mt-5 block space-y-2 text-xs font-medium text-slate-400">Dashboard request
          <textarea value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="For example: build a sales overview with monthly trends, top item categories, and headline sales quantity for MTD" rows={3} maxLength={2000} className="w-full resize-y rounded-xl border border-border bg-black/20 px-4 py-3 text-sm leading-6 text-white outline-none placeholder:text-slate-600 focus:border-primary/70" />
        </label>
        <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
          <p className="max-w-2xl text-[10px] leading-5 text-slate-600">The model proposes dashboard structure only. The server generates and validates each read-only SQL query, then renders the returned database rows.</p>
          <Button onClick={() => submit()} disabled={!databaseId || !question.trim() || !selectedConnection || generate.isPending}>
            {generate.isPending ? <><LoaderCircle size={15} className="animate-spin" />Building dashboard…</> : <><Sparkles size={15} />Generate dashboard</>}
          </Button>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          {suggestions.map((item) => <button key={item} type="button" onClick={() => { setQuestion(item); generate.reset(); }} className="rounded-full border border-white/[.07] bg-white/[.025] px-3 py-2 text-left text-[10px] text-slate-400 transition hover:border-violet-300/20 hover:text-violet-200">{item}</button>)}
        </div>
        {generate.isError && <ErrorBox message={errorMessage(generate.error)} />}
        {save.isError && <ErrorBox message={errorMessage(save.error)} />}
      </Card>

      {generate.isPending && <Card className="flex items-center gap-3 p-6 text-sm text-slate-400"><LoaderCircle size={17} className="animate-spin text-violet-300" /><span>Generating safe queries and loading real database results…</span></Card>}

      {generate.data && (
        <section className="space-y-4">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div><h2 className="font-display text-2xl font-semibold tracking-tight text-white">{generate.data.title}</h2><p className="mt-1 max-w-3xl text-xs leading-5 text-slate-500">{generate.data.description}</p></div>
            <div className="flex gap-2"><Button variant="secondary" size="small" onClick={() => save.mutate(generate.data)} disabled={save.isPending}><Bookmark size={13} />{save.isPending ? "Saving…" : "Save dashboard"}</Button><Button variant="secondary" size="small" onClick={() => submit()} disabled={generate.isPending}><RefreshCw size={13} />Refresh data</Button></div>
          </div>
          <DashboardRenderer dashboard={generate.data} />
        </section>
      )}
    </div>
  );
}

function ErrorBox({ message }: { message: string }) {
  return <div role="alert" className="mt-4 flex items-start gap-2 rounded-xl border border-rose-300/10 bg-rose-300/[.04] p-3 text-xs text-rose-200"><AlertCircle size={15} className="mt-0.5 shrink-0" />{message}</div>;
}

function errorMessage(error: unknown): string {
  if (typeof error === "object" && error !== null && "response" in error) {
    const response = (error as { response?: { data?: { detail?: unknown } } }).response;
    const detail = response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (typeof detail === "object" && detail !== null && "issues" in detail) {
      const issues = (detail as { issues?: unknown }).issues;
      if (Array.isArray(issues)) return issues.join("; ");
    }
    if (typeof detail === "object" && detail !== null && "message" in detail) {
      const message = (detail as { message?: unknown }).message;
      if (typeof message === "string") return message;
    }
  }
  return "Dashboard generation failed. Check your connection and try again.";
}
