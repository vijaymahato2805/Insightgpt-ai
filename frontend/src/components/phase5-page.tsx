import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, ArrowDownRight, ArrowUpRight, CalendarDays, CircleHelp, LoaderCircle, MessageSquareText, Plus, RefreshCw, Sparkles, Trash2 } from "lucide-react";
import { Button, Card, Input } from "@/components/ui";
import { erpApi } from "@/services/erp-api";
import { analysisApi, type AnalysisFilter, type CompanyComparisonResponse, type Conversation, type InsightResponse, type PeriodComparisonResponse } from "@/services/analysis-api";
import { cn } from "@/lib/utils";

type Tab = "conversation" | "insights" | "periods" | "companies";
const textAreaClass = "w-full rounded-xl border border-border bg-black/20 px-3.5 py-3 text-sm text-white outline-none placeholder:text-slate-600 focus:border-primary/70";
const selectClass = "h-11 w-full rounded-xl border border-border bg-[#11131c] px-3.5 text-sm text-foreground outline-none focus:border-primary/70";
const tabs: { id: Tab; label: string }[] = [
  { id: "conversation", label: "Conversation" },
  { id: "insights", label: "Business insights" },
  { id: "periods", label: "Period comparison" },
  { id: "companies", label: "Company comparison" },
];

export function Phase5Page() {
  const queryClient = useQueryClient();
  const connections = useQuery({ queryKey: ["databases"], queryFn: erpApi.listConnections });
  const histories = useQuery({ queryKey: ["conversations"], queryFn: analysisApi.listConversations });
  const [tab, setTab] = useState<Tab>("conversation");
  const [databaseId, setDatabaseId] = useState("");
  const [mappingId, setMappingId] = useState("");
  const [conversationId, setConversationId] = useState("");
  const [filters, setFilters] = useState<AnalysisFilter[]>([]);
  const [filterField, setFilterField] = useState("");
  const [filterValue, setFilterValue] = useState("");
  const [question, setQuestion] = useState("");
  const [metricField, setMetricField] = useState("Sales Amount");
  const [dateField, setDateField] = useState("Posting Date");
  const [dimensionText, setDimensionText] = useState("Item Category");
  const [currentStart, setCurrentStart] = useState("2026-01-01");
  const [currentEnd, setCurrentEnd] = useState("2026-01-31");
  const [previousStart, setPreviousStart] = useState("2025-12-01");
  const [previousEnd, setPreviousEnd] = useState("2025-12-31");
  const [companyIds, setCompanyIds] = useState<string[]>([]);
  const [currencyFieldsText, setCurrencyFieldsText] = useState("");
  const [targetCurrency, setTargetCurrency] = useState("");
  const [exchangeRatesText, setExchangeRatesText] = useState("{}");

  const mappings = useQuery({
    queryKey: ["company-mappings", databaseId],
    queryFn: () => erpApi.listCompanyMappings(databaseId),
    enabled: Boolean(databaseId),
  });
  const currentConversation = useQuery({
    queryKey: ["conversation", conversationId],
    queryFn: () => analysisApi.getConversation(conversationId),
    enabled: Boolean(conversationId),
  });
  const dimensionFields = useMemo(() => splitFields(dimensionText), [dimensionText]);

  useEffect(() => {
    if (!databaseId && connections.data?.length) setDatabaseId(connections.data[0].id);
  }, [connections.data, databaseId]);
  useEffect(() => {
    if (mappingId && !mappings.data?.some((item) => item.id === mappingId)) setMappingId("");
    setCompanyIds((selected) => selected.filter((id) => mappings.data?.some((item) => item.id === id)));
  }, [mappingId, mappings.data]);
  useEffect(() => {
    if (!conversationId) return;
    const conversation = currentConversation.data;
    if (conversation) {
      setDatabaseId(conversation.database_connection_id);
      setMappingId(conversation.company_mapping_id ?? "");
      setFilters(conversation.active_filters);
    }
  }, [conversationId, currentConversation.data]);

  const ask = useMutation({
    mutationFn: analysisApi.ask,
    onSuccess: (conversation) => {
      setConversationId(conversation.id);
      setFilters(conversation.active_filters);
      queryClient.setQueryData(["conversation", conversation.id], conversation);
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
  });
  const insight = useMutation({ mutationFn: analysisApi.insights });
  const period = useMutation({ mutationFn: analysisApi.comparePeriods });
  const companies = useMutation({ mutationFn: analysisApi.compareCompanies });

  const beginConversation = () => {
    setConversationId("");
    setFilters([]);
    setQuestion("");
    ask.reset();
  };
  const submitQuestion = (event: FormEvent) => {
    event.preventDefault();
    if (!question.trim() || !databaseId) return;
    ask.mutate({
      ...(conversationId ? { conversation_id: conversationId } : { database_id: databaseId, ...(mappingId ? { company_mapping_id: mappingId } : {}) }),
      question: question.trim(),
      active_filters: filters,
    });
    setQuestion("");
  };
  const addFilter = () => {
    if (!filterField.trim() || !filterValue.trim()) return;
    setFilters((current) => [...current.filter((item) => item.field.toLowerCase() !== filterField.trim().toLowerCase()), { field: filterField.trim(), value: filterValue.trim() }]);
    setFilterField("");
    setFilterValue("");
  };
  const deleteConversation = useMutation({
    mutationFn: analysisApi.deleteConversation,
    onSuccess: async (_, id) => {
      if (conversationId === id) beginConversation();
      await queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
  });

  const runInsights = (event: FormEvent) => {
    event.preventDefault();
    if (!question.trim() || !databaseId) return;
    insight.mutate({ database_id: databaseId, ...(mappingId ? { company_mapping_id: mappingId } : {}), question: question.trim() });
  };
  const runPeriods = (event: FormEvent) => {
    event.preventDefault();
    if (!question.trim() || !databaseId) return;
    period.mutate({
      database_id: databaseId,
      ...(mappingId ? { company_mapping_id: mappingId } : {}),
      question: question.trim(), date_field: dateField.trim(), metric_field: metricField.trim(), dimension_fields: dimensionFields,
      current_start: currentStart, current_end: currentEnd, comparison_start: previousStart, comparison_end: previousEnd,
    });
  };
  const runCompanies = (event: FormEvent) => {
    event.preventDefault();
    if (!question.trim() || !databaseId) return;
    let exchangeRates: Record<string, string>;
    try {
      exchangeRates = JSON.parse(exchangeRatesText) as Record<string, string>;
      if (!exchangeRates || Array.isArray(exchangeRates) || typeof exchangeRates !== "object") throw new Error("Rates must be a JSON object");
    } catch {
      companies.reset();
      return;
    }
    companies.mutate({
      database_id: databaseId, company_mapping_ids: companyIds, question: question.trim(), metric_field: metricField.trim(),
      dimension_fields: dimensionFields, currency_fields: splitFields(currencyFieldsText),
      ...(targetCurrency.trim() ? { target_currency_code: targetCurrency.trim().toUpperCase() } : {}), exchange_rates: exchangeRates,
    });
  };

  return <div className="space-y-6">
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div><div className="mb-2 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[.19em] text-violet-300"><Sparkles size={13} /> Phase 5 · Context and comparisons</div><h1 className="font-display text-3xl font-semibold tracking-[-.05em] text-white">Explore the business context</h1><p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">Continue a conversation with its database, company scope, and exact filters intact, or generate grounded insights and comparisons.</p></div>
      <div className="inline-flex items-center gap-2 rounded-xl border border-emerald-300/10 bg-emerald-300/[.04] px-3 py-2 text-[11px] text-emerald-200"><Activity size={14} /> Access is rechecked for every request</div>
    </div>

    <Card className="p-5">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Authorized database"><select className={selectClass} value={databaseId} onChange={(event) => { setDatabaseId(event.target.value); setMappingId(""); setConversationId(""); setFilters([]); }}><option value="">Choose a database</option>{connections.data?.map((item) => <option key={item.id} value={item.id}>{item.connection_name} · {item.database}</option>)}</select></Field>
        <Field label="Company scope"><select className={selectClass} value={mappingId} onChange={(event) => { setMappingId(event.target.value); if (!conversationId) setFilters([]); }} disabled={!databaseId || Boolean(conversationId)}><option value="">Database default scope</option>{mappings.data?.map((item) => <option key={item.id} value={item.id}>{item.company_name}{item.currency_code ? ` · ${item.currency_code}` : ""}</option>)}</select></Field>
      </div>
      {connections.isError && <ErrorMessage error={connections.error} />}
      {!connections.isLoading && !connections.data?.length && <p className="mt-4 rounded-xl border border-amber-200/10 p-3 text-xs text-amber-100">No authorized database is available. Ask an administrator for access.</p>}
    </Card>

    <div className="flex flex-wrap gap-2 border-b border-border pb-3">{tabs.map((item) => <button key={item.id} type="button" onClick={() => setTab(item.id)} className={cn("rounded-lg px-3 py-2 text-xs font-medium transition", tab === item.id ? "bg-violet-300/[.12] text-violet-100" : "text-slate-500 hover:bg-white/[.04] hover:text-slate-200")}>{item.label}</button>)}</div>

    {tab === "conversation" && <div className="grid gap-5 xl:grid-cols-[.72fr_1.28fr]">
      <Card className="p-4 sm:p-5">
        <div className="flex items-center justify-between"><div><h2 className="text-sm font-semibold text-white">Conversation history</h2><p className="mt-1 text-[10px] text-slate-600">Private to your account</p></div><Button size="small" variant="secondary" onClick={beginConversation}><Plus size={13} />New</Button></div>
        <div className="mt-4 max-h-[560px] space-y-2 overflow-auto">{histories.data?.map((item) => <div key={item.id} className={cn("flex items-center gap-2 rounded-xl border p-3", item.id === conversationId ? "border-violet-300/25 bg-violet-300/[.06]" : "border-white/[.06] bg-white/[.015]")}><button className="min-w-0 flex-1 text-left" onClick={() => { setConversationId(item.id); ask.reset(); }}><span className="block truncate text-xs font-medium text-slate-200">{item.title}</span><span className="mt-1 block text-[10px] text-slate-600">{item.message_count} turns · {item.active_filters.length} filters</span></button><button title="Delete conversation" aria-label="Delete conversation" onClick={() => deleteConversation.mutate(item.id)} className="rounded-md p-1.5 text-slate-600 hover:bg-rose-300/10 hover:text-rose-200"><Trash2 size={13} /></button></div>)}{!histories.data?.length && <p className="rounded-xl border border-dashed border-white/[.08] p-4 text-xs text-slate-600">No saved conversations yet.</p>}</div>
      </Card>
      <div className="space-y-5">
        <Card className="p-5 sm:p-6">
          <div className="flex items-center gap-2"><MessageSquareText size={15} className="text-violet-300" /><h2 className="text-sm font-semibold text-white">{conversationId ? "Continue this conversation" : "Start a conversation"}</h2></div>
          <p className="mt-2 text-xs leading-5 text-slate-500">Follow-ups retain the selected database and company. Exact-match filters below are applied to every generated query until you remove them.</p>
          <form onSubmit={submitQuestion}>
            <div className="mt-4 grid gap-2 sm:grid-cols-[1fr_1fr_auto]"><Input placeholder="Filter field e.g. Item Category" value={filterField} onChange={(event) => setFilterField(event.target.value)} /><Input placeholder="Exact value" value={filterValue} onChange={(event) => setFilterValue(event.target.value)} /><Button type="button" size="small" variant="secondary" onClick={addFilter}><Plus size={13} />Add filter</Button></div>
            <div className="mt-2 flex flex-wrap gap-2">{filters.map((item) => <button type="button" key={`${item.field}-${item.value}`} title="Remove filter" onClick={() => setFilters((current) => current.filter((filter) => filter !== item))} className="rounded-full border border-violet-300/15 bg-violet-300/[.06] px-3 py-1.5 text-[10px] text-violet-100">{item.field} = {item.value} ×</button>)}{filters.length === 0 && <span className="text-[10px] text-slate-600">No active filters</span>}</div>
            <textarea className={`${textAreaClass} mt-4 resize-y`} rows={3} maxLength={2000} value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Ask a business question or a follow-up like ‘break that down by item category’" />
            <div className="mt-3 flex justify-end"><Button disabled={!databaseId || !question.trim() || ask.isPending}>{ask.isPending ? <><LoaderCircle className="animate-spin" size={15} />Thinking…</> : <><Sparkles size={15} />Ask</>}</Button></div>
          </form>
          {ask.isError && <ErrorMessage error={ask.error} />}
        </Card>
        <ConversationResult conversation={currentConversation.data ?? ask.data} loading={currentConversation.isLoading} />
      </div>
    </div>}

    {tab === "insights" && <div className="grid gap-5 xl:grid-cols-[.72fr_1.28fr]">
      <Card className="p-5"><div className="mb-4 flex items-center gap-2"><Sparkles size={15} className="text-violet-300" /><h2 className="text-sm font-semibold text-white">Grounded business insights</h2></div><form onSubmit={runInsights} className="space-y-3"><textarea className={`${textAreaClass} resize-y`} rows={5} value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Ask for trends, outliers, or drivers in a business result" /><Button disabled={!databaseId || !question.trim() || insight.isPending} className="w-full">{insight.isPending ? <><LoaderCircle className="animate-spin" size={15} />Analyzing results…</> : <><Sparkles size={15} />Generate insights</>}</Button></form>{insight.isError && <ErrorMessage error={insight.error} />}</Card>
      <InsightResult result={insight.data} />
    </div>}

    {tab === "periods" && <div className="grid gap-5 xl:grid-cols-[.75fr_1.25fr]">
      <Card className="p-5"><div className="mb-4 flex items-center gap-2"><CalendarDays size={15} className="text-violet-300" /><h2 className="text-sm font-semibold text-white">Compare two periods</h2></div><form onSubmit={runPeriods} className="space-y-3"><textarea className={`${textAreaClass} resize-y`} rows={3} value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="What should be compared? e.g. Posted sales amount by item category" /><div className="grid gap-3 sm:grid-cols-2"><Field label="Date field"><Input value={dateField} onChange={(event) => setDateField(event.target.value)} /></Field><Field label="Metric field"><Input value={metricField} onChange={(event) => setMetricField(event.target.value)} /></Field></div><Field label="Dimensions (comma separated)"><Input value={dimensionText} onChange={(event) => setDimensionText(event.target.value)} placeholder="Item Category, Location" /></Field><div className="grid gap-3 sm:grid-cols-2"><DateRange title="Current period" start={currentStart} end={currentEnd} setStart={setCurrentStart} setEnd={setCurrentEnd} /><DateRange title="Comparison period" start={previousStart} end={previousEnd} setStart={setPreviousStart} setEnd={setPreviousEnd} /></div><Button disabled={!databaseId || !question.trim() || period.isPending} className="w-full">{period.isPending ? <><LoaderCircle className="animate-spin" size={15} />Comparing…</> : "Run period comparison"}</Button></form>{period.isError && <ErrorMessage error={period.error} />}</Card>
      <PeriodResult result={period.data} />
    </div>}

    {tab === "companies" && <div className="grid gap-5 xl:grid-cols-[.75fr_1.25fr]">
      <Card className="p-5"><div className="mb-4 flex items-center gap-2"><RefreshCw size={15} className="text-violet-300" /><h2 className="text-sm font-semibold text-white">Compare companies</h2></div><form onSubmit={runCompanies} className="space-y-3"><textarea className={`${textAreaClass} resize-y`} rows={3} value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Describe the metric to compare across the selected NAV/BC companies" /><Field label="Metric field"><Input value={metricField} onChange={(event) => setMetricField(event.target.value)} /></Field><Field label="Dimensions (comma separated)"><Input value={dimensionText} onChange={(event) => setDimensionText(event.target.value)} /></Field><fieldset className="rounded-xl border border-white/[.07] p-3"><legend className="px-1 text-[11px] text-slate-400">Company series</legend><div className="grid gap-2 sm:grid-cols-2">{mappings.data?.map((item) => <label key={item.id} className="flex items-center gap-2 text-xs text-slate-300"><input type="checkbox" checked={companyIds.includes(item.id)} onChange={(event) => setCompanyIds((selected) => event.target.checked ? [...selected, item.id] : selected.filter((id) => id !== item.id))} />{item.company_name} <span className="text-slate-600">{item.currency_code ?? "currency not set"}</span></label>)}</div></fieldset><details className="rounded-xl border border-white/[.07] p-3"><summary className="cursor-pointer text-xs text-slate-400">Currency conversion (optional)</summary><div className="mt-3 space-y-3"><Field label="Currency fields to convert"><Input value={currencyFieldsText} onChange={(event) => setCurrencyFieldsText(event.target.value)} placeholder="Sales Amount, Cost Amount" /></Field><Field label="Target currency code"><Input maxLength={3} value={targetCurrency} onChange={(event) => setTargetCurrency(event.target.value.toUpperCase())} placeholder="USD" /></Field><Field label="Rates to target currency (JSON)"><textarea className={`${textAreaClass} font-mono text-xs`} rows={2} value={exchangeRatesText} onChange={(event) => setExchangeRatesText(event.target.value)} placeholder={'{"EUR":"1.08","INR":"0.012"}'} /></Field><p className="text-[10px] leading-4 text-slate-600">Each value is units of target currency per one source currency. Rates must be supplied for currencies that differ from the target.</p></div></details><Button disabled={!databaseId || !question.trim() || companyIds.length < 2 || companies.isPending} className="w-full">{companies.isPending ? <><LoaderCircle className="animate-spin" size={15} />Comparing…</> : "Run company comparison"}</Button></form>{companies.isError && <ErrorMessage error={companies.error} />}</Card>
      <CompanyResult result={companies.data} />
    </div>}
  </div>;
}

function ConversationResult({ conversation, loading }: { conversation?: Conversation; loading: boolean }) {
  if (loading) return <Card className="p-8 text-center text-xs text-slate-500"><LoaderCircle className="mx-auto animate-spin" size={18} /></Card>;
  if (!conversation) return <EmptyResult title="Your conversation will appear here" detail="Query results are saved with this thread so follow-ups can refer to previous answers." />;
  return <div className="space-y-4">{conversation.messages.map((message) => <Card key={message.id} className="overflow-hidden"><div className="border-b border-border px-4 py-3 text-[10px] font-semibold uppercase tracking-wider text-slate-500">{message.role === "user" ? "You" : "InsightGPT"}</div><p className="px-4 py-4 text-sm leading-6 text-slate-200">{message.content}</p>{message.sql && <details className="border-t border-border"><summary className="cursor-pointer px-4 py-3 text-[10px] text-violet-200">Validated SQL · {message.row_count} rows</summary><pre className="overflow-auto whitespace-pre-wrap bg-black/20 p-4 font-mono text-[10px] leading-5 text-emerald-100">{message.sql}</pre></details>}{message.result_rows.length > 0 && <ResultTable columns={message.result_columns} rows={message.result_rows} />}</Card>)}</div>;
}

function InsightResult({ result }: { result?: InsightResponse }) {
  if (!result) return <EmptyResult title="Insights use executed query results" detail="Each observation includes evidence values from the actual SQL result rows." />;
  return <div className="space-y-4"><Card className="p-5"><div className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-sm font-semibold text-white">{result.company_name ?? "Business summary"}</h2><span className="text-[10px] text-slate-500">{result.row_count} result rows{result.truncated ? " · bounded sample" : ""}</span></div><p className="mt-3 text-sm leading-6 text-slate-300">{result.summary}</p></Card>{result.insights.map((item, index) => <Card key={`${item.title}-${index}`} className="p-5"><div className="flex items-center gap-2">{item.direction === "up" ? <ArrowUpRight size={16} className="text-emerald-300" /> : item.direction === "down" ? <ArrowDownRight size={16} className="text-rose-300" /> : <CircleHelp size={15} className="text-violet-300" />}<h3 className="text-sm font-semibold text-white">{item.title}</h3></div><p className="mt-2 text-xs leading-5 text-slate-400">{item.observation}</p><div className="mt-3 flex flex-wrap gap-2">{item.evidence.map((evidence, evidenceIndex) => <span key={`${evidence.field}-${evidenceIndex}`} className="rounded-lg border border-white/[.07] bg-white/[.02] px-2.5 py-1.5 text-[10px] text-slate-400">{evidence.field}: <strong className="text-slate-200">{format(evidence.value)}</strong></span>)}</div></Card>)}<details><summary className="cursor-pointer text-xs text-slate-500">View source SQL</summary><pre className="mt-2 overflow-auto rounded-xl bg-black/20 p-4 font-mono text-[10px] leading-5 text-emerald-100">{result.sql}</pre></details></div>;
}

function PeriodResult({ result }: { result?: PeriodComparisonResponse }) {
  if (!result) return <EmptyResult title="Period results appear here" detail="Date limits are added to the validated query by the API and use inclusive calendar dates." />;
  return <Card className="overflow-hidden"><div className="border-b border-border px-5 py-4"><h2 className="text-sm font-semibold text-white">Period comparison</h2><p className="mt-1 text-[10px] text-slate-500">{result.metric_field}{result.currency_code ? ` · ${result.currency_code}` : ""}</p></div><div className="overflow-auto"><table className="w-full min-w-max text-left text-xs"><thead className="bg-white/[.025] text-[10px] text-slate-500"><tr><th className="px-4 py-3">Dimensions</th><th className="px-4 py-3">Current</th><th className="px-4 py-3">Comparison</th><th className="px-4 py-3">Change</th><th className="px-4 py-3">Change %</th></tr></thead><tbody>{result.rows.map((row, index) => <tr key={index} className="border-t border-white/[.05] text-slate-300"><td className="px-4 py-3">{format(row.dimensions)}</td><td className="px-4 py-3">{row.current_value ?? "—"}</td><td className="px-4 py-3">{row.comparison_value ?? "—"}</td><td className="px-4 py-3">{row.absolute_change ?? "—"}</td><td className="px-4 py-3">{row.percentage_change ? `${row.percentage_change}%` : "—"}</td></tr>)}</tbody></table></div>{!result.rows.length && <p className="p-8 text-center text-xs text-slate-500">No rows matched these periods.</p>}</Card>;
}

function CompanyResult({ result }: { result?: CompanyComparisonResponse }) {
  if (!result) return <EmptyResult title="Company comparison appears here" detail="Mapped NAV/BC fields are normalized before dimension and metric comparison. Cross-currency conversion uses your supplied rates." />;
  return <div className="space-y-5"><Card className="overflow-hidden"><div className="border-b border-border px-5 py-4"><h2 className="text-sm font-semibold text-white">Comparison by {result.dimension_fields.join(", ") || "total"}</h2><p className="mt-1 text-[10px] text-slate-500">Metric: {result.metric_field} · baseline: {result.baseline_company}{result.target_currency_code ? ` · normalized to ${result.target_currency_code}` : ""}</p></div><div className="overflow-auto"><table className="w-full min-w-max text-left text-xs"><thead className="bg-white/[.025] text-[10px] text-slate-500"><tr><th className="px-4 py-3">Dimensions</th>{result.companies.map((item) => <th key={item.company_mapping_id} className="px-4 py-3">{item.company_name}</th>)}</tr></thead><tbody>{result.rows.map((row, index) => <tr key={index} className="border-t border-white/[.05] text-slate-300"><td className="px-4 py-3">{format(row.dimensions)}</td>{result.companies.map((item) => <td key={item.company_mapping_id} className="px-4 py-3">{row.values_by_company[item.company_name] ?? "—"}{row.changes_vs_baseline[item.company_name] && <div className="mt-1 text-[10px] text-slate-500">Δ {row.changes_vs_baseline[item.company_name].absolute_change}{row.changes_vs_baseline[item.company_name].percentage_change ? ` (${row.changes_vs_baseline[item.company_name].percentage_change}%)` : ""}</div>}</td>)}</tr>)}</tbody></table></div></Card>{result.companies.map((item) => <Card key={item.company_mapping_id} className="overflow-hidden"><div className="border-b border-border px-5 py-3 text-xs font-medium text-slate-300">{item.company_name} · {item.source_currency_code ?? "currency unknown"}</div><ResultTable columns={item.columns} rows={item.rows} /></Card>)}</div>;
}

function ResultTable({ columns, rows }: { columns: string[]; rows: Record<string, unknown>[] }) {
  if (!columns.length || !rows.length) return null;
  return <div className="max-h-72 overflow-auto"><table className="w-full min-w-max text-left text-[10px]"><thead className="sticky top-0 bg-[#151722] text-slate-500"><tr>{columns.map((column) => <th key={column} className="px-3 py-2 font-medium">{column}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index} className="border-t border-white/[.04] text-slate-400">{columns.map((column) => <td key={column} className="max-w-64 truncate px-3 py-2">{format(row[column])}</td>)}</tr>)}</tbody></table></div>;
}

function DateRange({ title, start, end, setStart, setEnd }: { title: string; start: string; end: string; setStart: (value: string) => void; setEnd: (value: string) => void }) {
  return <fieldset className="rounded-xl border border-white/[.07] p-3"><legend className="px-1 text-[10px] text-slate-500">{title}</legend><div className="grid grid-cols-2 gap-2"><input aria-label={`${title} start`} type="date" className={selectClass} value={start} onChange={(event) => setStart(event.target.value)} /><input aria-label={`${title} end`} type="date" className={selectClass} value={end} onChange={(event) => setEnd(event.target.value)} /></div></fieldset>;
}
function Field({ label, children }: { label: string; children: React.ReactNode }) { return <label className="block space-y-1.5 text-[10px] font-medium text-slate-500">{label}{children}</label>; }
function EmptyResult({ title, detail }: { title: string; detail: string }) { return <Card className="flex min-h-52 flex-col items-center justify-center p-8 text-center"><span className="flex size-10 items-center justify-center rounded-xl border border-white/[.07] bg-white/[.025] text-violet-200"><Activity size={17} /></span><h2 className="mt-3 text-sm font-semibold text-slate-200">{title}</h2><p className="mt-2 max-w-sm text-xs leading-5 text-slate-500">{detail}</p></Card>; }
function ErrorMessage({ error }: { error: unknown }) { return <div role="alert" className="mt-3 rounded-xl border border-rose-300/10 bg-rose-300/[.04] p-3 text-xs text-rose-200">{errorText(error)}</div>; }
function errorText(error: unknown) { if (typeof error === "object" && error !== null && "response" in error) { const detail = (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail; if (typeof detail === "string") return detail; if (detail && typeof detail === "object" && "message" in detail) return String((detail as { message: unknown }).message); } return "Request failed. Check the selected database and try again."; }
function splitFields(value: string) { return value.split(",").map((item) => item.trim()).filter(Boolean); }
function format(value: unknown) { if (value === null || value === undefined || value === "") return "—"; return typeof value === "object" ? JSON.stringify(value) : String(value); }
