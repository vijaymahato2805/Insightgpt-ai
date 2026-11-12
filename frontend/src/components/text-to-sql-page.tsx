import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertCircle, ArrowRight, CheckCircle2, Database, LoaderCircle, Play, ShieldCheck, Sparkles, Table2 } from "lucide-react";
import { Button, Card } from "@/components/ui";
import { erpApi } from "@/services/erp-api";
import { sqlApi } from "@/services/sql-api";

const suggestions = [
  "Show sales quantity by posting month for MTD",
  "Compare sales quantity by item category using approved business rules",
  "Show the top 10 customers by posted sales quantity this quarter",
];

export function TextToSQLPage() {
  const connections = useQuery({ queryKey: ["databases"], queryFn: erpApi.listConnections });
  const [databaseId, setDatabaseId] = useState("");
  const [companyMappingId, setCompanyMappingId] = useState("");
  const [question, setQuestion] = useState("");
  const mappings = useQuery({
    queryKey: ["company-mappings", databaseId],
    queryFn: () => erpApi.listCompanyMappings(databaseId),
    enabled: Boolean(databaseId),
  });

  useEffect(() => {
    if (!databaseId && connections.data?.length) setDatabaseId(connections.data[0].id);
  }, [connections.data, databaseId]);

  useEffect(() => {
    if (companyMappingId && !mappings.data?.some((mapping) => mapping.id === companyMappingId)) {
      setCompanyMappingId("");
    }
  }, [companyMappingId, mappings.data]);

  const execute = useMutation({ mutationFn: sqlApi.execute });
  const generate = useMutation({
    mutationFn: sqlApi.generate,
    onSuccess: () => execute.reset(),
  });
  const clearAnswer = () => { generate.reset(); execute.reset(); };
  const selectedConnection = connections.data?.find((item) => item.id === databaseId);
  const canGenerate = Boolean(databaseId && question.trim()) && !generate.isPending;

  const submitQuestion = (value = question) => {
    if (!databaseId || !value.trim()) return;
    generate.mutate({
      database_id: databaseId,
      ...(companyMappingId ? { company_mapping_id: companyMappingId } : {}),
      question: value.trim(),
    });
  };

  const runQuery = () => {
    if (!generate.data?.sql) return;
    execute.mutate({
      database_id: databaseId,
      ...(companyMappingId ? { company_mapping_id: companyMappingId } : {}),
      sql: generate.data.sql,
    });
  };

  return <div className="space-y-6">
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div>
        <div className="mb-2 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[.19em] text-violet-300"><Sparkles size={13} /> Phase 3 · Text to SQL</div>
        <h1 className="font-display text-3xl font-semibold tracking-[-.05em] text-white">Ask your business data</h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">The assistant retrieves relevant schema and approved terminology, then validates its SQL against the selected database before it can run.</p>
      </div>
      <div className="flex items-center gap-2 rounded-xl border border-emerald-300/10 bg-emerald-300/[.04] px-3 py-2 text-[11px] text-emerald-200"><ShieldCheck size={14} /> Permission checked on every request</div>
    </div>

    <Card className="p-5 sm:p-6">
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="block space-y-2 text-xs font-medium text-slate-400">Database connection
          <select value={databaseId} onChange={(event) => { setDatabaseId(event.target.value); setCompanyMappingId(""); clearAnswer(); }} className="h-11 w-full rounded-xl border border-border bg-[#11131c] px-3.5 text-sm text-foreground outline-none focus:border-primary/70" disabled={connections.isLoading}>
            <option value="">Select an authorized database</option>
            {connections.data?.map((item) => <option key={item.id} value={item.id}>{item.connection_name} · {item.database}</option>)}
          </select>
        </label>
        <label className="block space-y-2 text-xs font-medium text-slate-400">Company mapping
          <select value={companyMappingId} onChange={(event) => { setCompanyMappingId(event.target.value); clearAnswer(); }} className="h-11 w-full rounded-xl border border-border bg-[#11131c] px-3.5 text-sm text-foreground outline-none focus:border-primary/70" disabled={!databaseId || mappings.isLoading}>
            <option value="">Use the database scope</option>
            {mappings.data?.map((item) => <option key={item.id} value={item.id}>{item.company_name}</option>)}
          </select>
        </label>
      </div>
      {connections.isError && <ErrorBox message={errorMessage(connections.error)} />}
      {!connections.isLoading && !connections.isError && !connections.data?.length && <div className="mt-4 rounded-xl border border-amber-200/10 bg-amber-200/[.035] p-3 text-xs text-amber-100">No database connections are available to your account. Ask an administrator to grant database access.</div>}
      <label className="mt-5 block space-y-2 text-xs font-medium text-slate-400">Question
        <textarea value={question} onChange={(event) => { setQuestion(event.target.value); clearAnswer(); }} onKeyDown={(event) => { if ((event.ctrlKey || event.metaKey) && event.key === "Enter") submitQuestion(); }} placeholder="For example: show monthly sales quantity by item category for MTD" rows={4} maxLength={4000} className="w-full resize-y rounded-xl border border-border bg-black/20 px-4 py-3 text-sm leading-6 text-white outline-none placeholder:text-slate-600 focus:border-primary/70" />
      </label>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
        <p className="text-[10px] text-slate-600">Try a suggestion or press Ctrl/⌘ + Enter. Schema and dictionary context is sent to OpenRouter; database credentials are not.</p>
        <Button onClick={() => submitQuestion()} disabled={!canGenerate || !selectedConnection}>
          {generate.isPending ? <><LoaderCircle size={15} className="animate-spin" />Generating…</> : <><Sparkles size={15} />Generate safe SQL</>}
        </Button>
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        {suggestions.map((item) => <button key={item} type="button" onClick={() => { setQuestion(item); clearAnswer(); }} className="rounded-full border border-white/[.07] bg-white/[.025] px-3 py-2 text-[10px] text-slate-400 transition hover:border-violet-300/20 hover:text-violet-200">{item}</button>)}
      </div>
      {generate.isError && <ErrorBox message={errorMessage(generate.error)} />}
    </Card>

    {generate.data?.needs_clarification && <Card className="border-amber-200/10 p-5">
      <div className="flex items-start gap-3 text-amber-100"><AlertCircle size={17} className="mt-0.5 shrink-0" /><div><h2 className="text-sm font-semibold">One clarification needed</h2><p className="mt-1 text-xs leading-5 text-amber-100/70">{generate.data.clarification}</p></div></div>
    </Card>}

    {generate.data?.sql && <div className="grid gap-5 xl:grid-cols-[1.05fr_.95fr]">
      <div className="space-y-5">
        <Card className="overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-4">
            <div className="flex items-center gap-2"><Table2 size={15} className="text-violet-300" /><h2 className="text-sm font-semibold text-white">Validated SQL preview</h2></div>
            <Button size="small" onClick={runQuery} disabled={execute.isPending}>
              {execute.isPending ? <><LoaderCircle size={14} className="animate-spin" />Running…</> : <><Play size={14} />Run query</>}
            </Button>
          </div>
          <pre className="max-h-[380px] overflow-auto whitespace-pre-wrap break-words bg-black/20 p-5 font-mono text-xs leading-6 text-emerald-100">{generate.data.sql}</pre>
          <div className="flex flex-wrap gap-2 border-t border-border px-5 py-3">{generate.data.selected_tables.map((table) => <span key={table} className="rounded-md border border-white/[.07] px-2 py-1 font-mono text-[9px] text-slate-500">{table}</span>)}</div>
        </Card>
        <Card className="p-5">
          <div className="flex items-center gap-2"><CheckCircle2 size={15} className="text-emerald-300" /><h2 className="text-sm font-semibold text-white">How it works</h2></div>
          <p className="mt-3 text-xs leading-6 text-slate-400">{generate.data.explanation}</p>
          {generate.data.explanation_notes.length > 0 && <ul className="mt-3 list-disc space-y-1 pl-5 text-[11px] text-slate-500">{generate.data.explanation_notes.map((note) => <li key={note}>{note}</li>)}</ul>}
          <div className="mt-4 flex flex-wrap gap-2">{generate.data.business_terms.map((term) => <span key={term} className="rounded-full bg-violet-300/[.08] px-2.5 py-1 text-[10px] text-violet-200">{term}</span>)}</div>
        </Card>
        {execute.isError && <ErrorBox message={errorMessage(execute.error)} />}
      </div>

      <Card className="min-h-[250px] overflow-hidden">
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <div className="flex items-center gap-2"><Database size={15} className="text-violet-300" /><h2 className="text-sm font-semibold text-white">Query results</h2></div>
          {execute.data && <span className="text-[10px] text-slate-500">{execute.data.row_count} rows{execute.data.truncated ? ` · limited to ${execute.data.max_rows}` : ""}</span>}
        </div>
        {!execute.data && <div className="flex min-h-[205px] flex-col items-center justify-center px-6 text-center"><span className="flex size-10 items-center justify-center rounded-xl border border-white/[.07] bg-white/[.025] text-slate-500"><ArrowRight size={17} /></span><p className="mt-3 text-xs font-medium text-slate-300">Review the SQL, then run it</p><p className="mt-1 max-w-xs text-[10px] leading-5 text-slate-600">The API validates the query again and rechecks your database permission before execution.</p></div>}
        {execute.data && execute.data.rows.length === 0 && <div className="p-8 text-center text-xs text-slate-500">The query returned no rows.</div>}
        {execute.data && execute.data.rows.length > 0 && <div className="max-h-[520px] overflow-auto"><table className="w-full min-w-max border-collapse text-left text-[11px]"><thead className="sticky top-0 bg-[#151722] text-slate-400"><tr>{execute.data.columns.map((column) => <th key={column} className="border-b border-border px-4 py-3 font-medium">{column}</th>)}</tr></thead><tbody>{execute.data.rows.map((row, index) => <tr key={index} className="border-b border-white/[.04] text-slate-300" data-row={index}>{execute.data!.columns.map((column) => <td key={column} className="max-w-[280px] truncate px-4 py-3">{formatCell(row[column])}</td>)}</tr>)}</tbody></table></div>}
      </Card>
    </div>}
  </div>;
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
  return "The request could not be completed. Check your connection and try again.";
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "—";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}
