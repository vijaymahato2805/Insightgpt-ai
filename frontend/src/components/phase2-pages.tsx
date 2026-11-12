import { useMemo, useState, type FormEvent, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Database, FileText, LoaderCircle, Plus, RefreshCw, Search, Trash2, X } from "lucide-react";
import { Button, Card, Input, StatusDot } from "@/components/ui";
import { erpApi } from "@/services/erp-api";
import type { DatabaseConnection, DatabaseConnectionInput } from "@/types/erp";
import { useAuthStore } from "@/stores/auth-store";
import { cn } from "@/lib/utils";

const emptyConnection = (): DatabaseConnectionInput => ({
  connection_name: "",
  company_name: "",
  server: "",
  database: "",
  authentication_type: "sql_server",
  username: "",
  password: "",
  erp_version: "business_central",
  enabled: true,
});

function useAdmin() {
  const role = useAuthStore((state) => state.user?.role);
  return role === "admin" || role === "super_admin";
}

function useConnections() {
  return useQuery({ queryKey: ["erp-connections"], queryFn: erpApi.listConnections });
}

function errorText(error: unknown) {
  const response = error as { response?: { data?: { detail?: string } } };
  return response.response?.data?.detail ?? "The request failed. Check your permissions and API connection.";
}

function PageHeading({ eyebrow, title, description, icon: Icon }: {
  eyebrow: string; title: string; description: string; icon: typeof Database;
}) {
  return <div className="mb-7 flex flex-wrap items-end justify-between gap-4">
    <div>
      <div className="mb-2.5 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[.18em] text-violet-300"><Icon size={13} />{eyebrow}</div>
      <h1 className="font-display text-[30px] font-semibold tracking-[-.055em] text-white sm:text-[35px]">{title}</h1>
      <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">{description}</p>
    </div>
  </div>;
}

function SelectField({ label, value, onChange, children }: {
  label: string; value: string; onChange: (value: string) => void; children: ReactNode;
}) {
  return <label className="block space-y-2 text-xs font-medium text-slate-400">{label}
    <select value={value} onChange={(event) => onChange(event.target.value)} className="h-11 w-full rounded-xl border border-border bg-[#11121a] px-3 text-sm text-slate-200 outline-none focus:border-violet-400/60">
      {children}
    </select>
  </label>;
}

export function DatabaseConnectionsPage() {
  const isAdmin = useAdmin();
  const queryClient = useQueryClient();
  const connections = useConnections();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState<DatabaseConnectionInput>(emptyConnection());
  const [feedback, setFeedback] = useState("");
  const save = useMutation({
    mutationFn: () => editing ? erpApi.updateConnection(editing, { ...draft, password: draft.password || undefined, username: draft.username || undefined }) : erpApi.createConnection(draft),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["erp-connections"] });
      setDraft(emptyConnection()); setEditing(null); setOpen(false); setFeedback("Connection saved. Credentials remain encrypted on the server.");
    },
  });
  const testDraft = useMutation({
    mutationFn: () => erpApi.testConnection({ connection: draft }),
    onSuccess: (result) => setFeedback(result.message),
    onError: (error) => setFeedback(errorText(error)),
  });
  const deleteConnection = useMutation({
    mutationFn: erpApi.deleteConnection,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["erp-connections"] }),
  });
  const testSaved = useMutation({
    mutationFn: erpApi.testConnection,
    onSuccess: async (result) => { setFeedback(result.message); await queryClient.invalidateQueries({ queryKey: ["erp-connections"] }); },
    onError: (error) => setFeedback(errorText(error)),
  });

  const patch = (key: keyof DatabaseConnectionInput, value: string | boolean) => setDraft((current) => ({ ...current, [key]: value }));
  const startEdit = (connection: DatabaseConnection) => {
    setDraft({
      connection_name: connection.connection_name,
      company_name: connection.company_name ?? "",
      server: connection.server,
      database: connection.database,
      authentication_type: connection.authentication_type,
      erp_version: connection.erp_version,
      enabled: connection.enabled,
      username: "",
      password: "",
    });
    setEditing(connection.id); setOpen(true); setFeedback("Leave password blank to retain the stored credential.");
  };
  const submit = (event: FormEvent) => { event.preventDefault(); setFeedback(""); save.mutate(); };

  return <>
    <PageHeading eyebrow="PHASE 2 · CONNECTIONS" title="Database connections" description="Register SQL Server reporting databases for NAV, Business Central, and other ERP environments. Credentials are encrypted before they are stored." icon={Database} />
    <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
      <p className="text-xs text-slate-500">{connections.data?.length ?? 0} configured source{connections.data?.length === 1 ? "" : "s"}</p>
      {isAdmin && <Button onClick={() => { setDraft(emptyConnection()); setEditing(null); setOpen((value) => !value); }}><Plus size={15} /> Add connection</Button>}
    </div>

    {open && isAdmin && <Card className="mb-6 p-5 sm:p-6">
      <div className="mb-5 flex items-center justify-between"><div><h2 className="font-display text-base font-semibold text-white">{editing ? "Update connection" : "Register a database"}</h2><p className="mt-1 text-[11px] text-slate-500">Use a dedicated read-only SQL Server account for analytics.</p></div><button onClick={() => setOpen(false)} className="rounded-lg p-2 text-slate-500 hover:bg-white/[.05]" aria-label="Close form"><X size={16} /></button></div>
      <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <TextField label="Connection name" value={draft.connection_name} onChange={(value) => patch("connection_name", value)} placeholder="Northwind NAV" required />
        <TextField label="Company name" value={draft.company_name ?? ""} onChange={(value) => patch("company_name", value)} placeholder="Northwind Ltd." />
        <TextField label="SQL Server" value={draft.server} onChange={(value) => patch("server", value)} placeholder="sqlserver.company.internal,1433" required />
        <TextField label="Database" value={draft.database} onChange={(value) => patch("database", value)} placeholder="NAV_Production" required />
        <SelectField label="ERP version" value={draft.erp_version} onChange={(value) => patch("erp_version", value as DatabaseConnectionInput["erp_version"])}>
          <option value="business_central">Dynamics 365 Business Central</option><option value="nav_2018">Dynamics NAV 2018</option><option value="nav_2013_r2">Dynamics NAV 2013 R2</option><option value="sql_server">SQL Server reporting database</option>
        </SelectField>
        <SelectField label="Authentication" value={draft.authentication_type} onChange={(value) => patch("authentication_type", value as DatabaseConnectionInput["authentication_type"])}>
          <option value="sql_server">SQL Server authentication</option><option value="windows">Windows / integrated authentication</option>
        </SelectField>
        {draft.authentication_type === "sql_server" && <>
          <TextField label="Username" value={draft.username ?? ""} onChange={(value) => patch("username", value)} placeholder="read_only_user" required={!editing} autoComplete="off" />
          <TextField label={editing ? "Password · optional to retain" : "Password"} value={draft.password ?? ""} onChange={(value) => patch("password", value)} placeholder={editing ? "Leave blank to keep saved password" : "Database password"} type="password" required={!editing} autoComplete="new-password" />
        </>}
        <div className="flex items-center gap-2 self-end pb-3 text-xs text-slate-400"><input id="connection-enabled" type="checkbox" checked={draft.enabled ?? true} onChange={(event) => patch("enabled", event.target.checked)} className="accent-violet-400" /><label htmlFor="connection-enabled">Connection enabled</label></div>
        {feedback && <p className="sm:col-span-2 xl:col-span-3 text-xs text-violet-200">{feedback}</p>}
        {(save.isError || testDraft.isError) && <p role="alert" className="sm:col-span-2 xl:col-span-3 text-xs text-rose-300">{errorText(save.error ?? testDraft.error)}</p>}
        <div className="flex flex-wrap gap-2 sm:col-span-2 xl:col-span-3">
          {!editing && <Button type="button" variant="secondary" onClick={() => testDraft.mutate()} disabled={testDraft.isPending}>{testDraft.isPending ? <LoaderCircle className="animate-spin" size={14} /> : <CheckCircle2 size={14} />} Test connection</Button>}
          <Button type="submit" disabled={save.isPending}>{save.isPending ? "Saving…" : editing ? "Save changes" : "Save connection"}</Button>
        </div>
      </form>
    </Card>}

    {feedback && !open && <p className="mb-4 text-xs text-violet-200">{feedback}</p>}
    {connections.isLoading ? <LoadingState /> : connections.isError ? <ErrorState message={errorText(connections.error)} /> : connections.data?.length ? <div className="grid gap-3 xl:grid-cols-2">
      {connections.data.map((item) => <Card key={item.id} className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-start gap-3"><span className="flex size-10 items-center justify-center rounded-xl border border-violet-300/10 bg-violet-300/[.06] text-violet-200"><Database size={17} /></span><div><h3 className="font-display text-sm font-semibold text-white">{item.connection_name}</h3><p className="mt-1 text-[11px] text-slate-500">{item.company_name || "Company not specified"} · {item.erp_version.replaceAll("_", " ")}</p></div></div>
          <StatusBadge state={item.connection_status} />
        </div>
        <div className="mt-4 grid gap-3 rounded-xl border border-border bg-black/10 p-3 text-[11px] sm:grid-cols-2"><div><span className="text-slate-600">SERVER</span><p className="mt-1 text-slate-300">{item.server}</p></div><div><span className="text-slate-600">DATABASE</span><p className="mt-1 text-slate-300">{item.database}</p></div><div><span className="text-slate-600">AUTHENTICATION</span><p className="mt-1 text-slate-300">{item.authentication_type.replaceAll("_", " ")}</p></div><div><span className="text-slate-600">CREDENTIALS</span><p className="mt-1 text-slate-300">{item.has_credentials ? "Encrypted and stored" : "Integrated authentication"}</p></div></div>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button size="small" variant="secondary" onClick={() => testSaved.mutate({ database_id: item.id })} disabled={testSaved.isPending}>{testSaved.isPending ? "Testing…" : "Test saved connection"}</Button>
          {isAdmin && <Button size="small" variant="ghost" onClick={() => startEdit(item)}>Edit</Button>}
          {isAdmin && <Button size="small" variant="ghost" className="text-rose-300 hover:text-rose-200" onClick={() => window.confirm(`Delete ${item.connection_name} and its schema metadata?`) && deleteConnection.mutate(item.id)}><Trash2 size={13} /> Delete</Button>}
        </div>
      </Card>)}
    </div> : <EmptyState title="No database connections" detail="Add a SQL Server reporting database to discover tables, fields, and NAV or Business Central company mappings." />}
  </>;
}

export function DatabaseSchemaPage() {
  const isAdmin = useAdmin();
  const queryClient = useQueryClient();
  const connections = useConnections();
  const [databaseId, setDatabaseId] = useState("");
  const [search, setSearch] = useState("");
  const activeId = databaseId || connections.data?.[0]?.id || "";
  const schema = useQuery({
    queryKey: ["database-schema", activeId, search],
    queryFn: () => erpApi.listSchema(activeId, search),
    enabled: Boolean(activeId),
  });
  const refresh = useMutation({
    mutationFn: () => erpApi.refreshSchema(activeId),
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: ["database-schema", activeId] }),
  });
  const [descriptionEdit, setDescriptionEdit] = useState<{ id: string; value: string } | null>(null);
  const saveDescription = useMutation({
    mutationFn: () => erpApi.updateObjectDescription(activeId, descriptionEdit!.id, descriptionEdit!.value),
    onSuccess: async () => { setDescriptionEdit(null); await queryClient.invalidateQueries({ queryKey: ["database-schema", activeId] }); },
  });

  return <>
    <PageHeading eyebrow="PHASE 2 · SCHEMA" title="Database schema" description="Browse discovered SQL Server tables, views, columns, keys, indexes, relationships, and available NAV / Business Central field captions." icon={FileText} />
    <div className="mb-5 flex flex-wrap gap-3">
      <div className="min-w-[240px] flex-1"><SelectField label="Database connection" value={activeId} onChange={setDatabaseId}><option value="">Choose a connection</option>{connections.data?.map((connection) => <option key={connection.id} value={connection.id}>{connection.connection_name} · {connection.database}</option>)}</SelectField></div>
      <label className="relative min-w-[220px] flex-1 space-y-2 text-xs font-medium text-slate-400">Search schema
        <Search size={15} className="absolute bottom-3 left-3 text-slate-600" /><Input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Table, view, or schema name" className="pl-9" />
      </label>
      {isAdmin && <Button className="self-end" onClick={() => refresh.mutate()} disabled={!activeId || refresh.isPending}>{refresh.isPending ? <LoaderCircle size={14} className="animate-spin" /> : <RefreshCw size={14} />} Refresh schema</Button>}
    </div>
    {refresh.isSuccess && <p className="mb-4 text-xs text-emerald-300">Discovered {refresh.data.objects_discovered} objects, {refresh.data.columns_discovered} columns, and {refresh.data.relationships_discovered} relationships; applied {refresh.data.captions_applied} NAV/BC captions.</p>}
    {refresh.isError && <p role="alert" className="mb-4 text-xs text-rose-300">{errorText(refresh.error)}</p>}
    {!activeId ? <EmptyState title="Select a database" detail="Add a connection first, then refresh its schema to browse metadata." /> : schema.isLoading ? <LoadingState /> : schema.isError ? <ErrorState message={errorText(schema.error)} /> : schema.data?.items.length ? <>
      <p className="mb-3 text-[11px] text-slate-600">{schema.data.total} objects found</p>
      <div className="space-y-3">{schema.data.items.map((object) => <Card key={object.id} className="overflow-hidden">
        <details className="group">
          <summary className="flex cursor-pointer list-none flex-wrap items-center justify-between gap-3 px-5 py-4">
            <div className="flex min-w-0 items-center gap-3"><span className="rounded-md border border-white/[.08] bg-white/[.03] px-2 py-1 text-[9px] uppercase text-slate-500">{object.object_type}</span><div className="min-w-0"><p className="truncate text-sm font-semibold text-slate-200">{object.schema_name}.{object.object_name}</p><p className="mt-1 text-[10px] text-slate-600">{object.columns.length} columns · {object.relationships.length} relationships · {object.indexes.length} indexes</p></div></div>
            {object.description && <span className="max-w-[320px] truncate text-[10px] text-slate-500">{object.description}</span>}
          </summary>
          <div className="border-t border-border px-5 py-4">
            {isAdmin && <form className="mb-4 flex gap-2" onSubmit={(event) => { event.preventDefault(); if (descriptionEdit?.id === object.id) saveDescription.mutate(); else { setDescriptionEdit({ id: object.id, value: object.description ?? "" }); } }}>
              <Input value={descriptionEdit?.id === object.id ? descriptionEdit.value : object.description ?? ""} onChange={(event) => setDescriptionEdit({ id: object.id, value: event.target.value })} placeholder="Add a table description" className="h-9 text-xs" />
              <Button size="small" variant="secondary" type="submit" disabled={saveDescription.isPending}>{descriptionEdit?.id === object.id ? "Save" : "Edit"}</Button>
            </form>}
            <div className="overflow-x-auto"><table className="w-full min-w-[680px] text-left text-[11px]"><thead className="text-[9px] uppercase tracking-wider text-slate-600"><tr><th className="pb-2 pr-4">Column</th><th className="pb-2 pr-4">Caption</th><th className="pb-2 pr-4">Type</th><th className="pb-2 pr-4">Flags</th><th className="pb-2">Description</th></tr></thead><tbody>{object.columns.map((column) => <tr key={column.id} className="border-t border-white/[.045]"><td className="py-2.5 pr-4 font-medium text-slate-300">{column.column_name}</td><td className="py-2.5 pr-4 text-violet-200/80">{column.caption || "—"}</td><td className="py-2.5 pr-4 text-slate-500">{column.data_type}</td><td className="py-2.5 pr-4 text-slate-500">{[column.is_primary_key && "PK", column.is_foreign_key && "FK", column.nullable && "Nullable"].filter(Boolean).join(" · ") || "—"}</td><td className="py-2.5 text-slate-500">{column.description || "—"}</td></tr>)}</tbody></table></div>
            {object.relationships.length > 0 && <div className="mt-4 border-t border-border pt-3"><p className="mb-2 text-[9px] font-semibold uppercase tracking-wider text-slate-600">Relationships</p>{object.relationships.map((relationship, index) => <p key={`${relationship.source_column}-${index}`} className="text-[10px] text-slate-400">{relationship.source_column} <span className="text-slate-600">→</span> {relationship.target_schema}.{relationship.target_table}.{relationship.target_column}</p>)}</div>}
          </div>
        </details>
      </Card>)}</div>
    </> : <EmptyState title="No schema metadata yet" detail="Refresh this connection to discover its tables, columns, indexes, and relationships." />}
  </>;
}

export function CompanyMappingsPage() {
  const isAdmin = useAdmin();
  const queryClient = useQueryClient();
  const connections = useConnections();
  const [databaseId, setDatabaseId] = useState("");
  const activeId = databaseId || connections.data?.[0]?.id || "";
  const mappings = useQuery({ queryKey: ["company-mappings", activeId], queryFn: () => erpApi.listCompanyMappings(activeId), enabled: Boolean(activeId) });
  const [editingId, setEditingId] = useState<string | null>(null);
  const [companyName, setCompanyName] = useState("");
  const [currencyCode, setCurrencyCode] = useState("");
  const [tableJson, setTableJson] = useState("{}");
  const [fieldJson, setFieldJson] = useState("{}");
  const [message, setMessage] = useState("");
  const writeMapping = useMutation({
    mutationFn: () => {
      const payload = { database_connection_id: activeId, company_name: companyName, table_mappings: JSON.parse(tableJson), field_mappings: JSON.parse(fieldJson), currency_code: currencyCode || null };
      return editingId ? erpApi.updateCompanyMapping(editingId, payload) : erpApi.createCompanyMapping(payload);
    },
    onSuccess: async () => { reset(); await queryClient.invalidateQueries({ queryKey: ["company-mappings", activeId] }); },
  });
  const removeMapping = useMutation({ mutationFn: erpApi.deleteCompanyMapping, onSuccess: () => queryClient.invalidateQueries({ queryKey: ["company-mappings", activeId] }) });
  const reset = () => { setEditingId(null); setCompanyName(""); setCurrencyCode(""); setTableJson("{}"); setFieldJson("{}"); setMessage(""); };
  const edit = (item: NonNullable<typeof mappings.data>[number]) => { setEditingId(item.id); setCompanyName(item.company_name); setCurrencyCode(item.currency_code ?? ""); setTableJson(JSON.stringify(item.table_mappings, null, 2)); setFieldJson(JSON.stringify(item.field_mappings, null, 2)); };

  return <>
    <PageHeading eyebrow="PHASE 2 · COMPANY MAPPINGS" title="Company mappings" description="Map each NAV or Business Central company to canonical tables and fields. Refreshing a schema can infer common table names; administrator mappings stay authoritative." icon={Database} />
    <div className="mb-5 max-w-lg"><SelectField label="Database connection" value={activeId} onChange={(value) => { setDatabaseId(value); reset(); }}><option value="">Choose a connection</option>{connections.data?.map((connection) => <option key={connection.id} value={connection.id}>{connection.connection_name} · {connection.database}</option>)}</SelectField></div>
    {isAdmin && activeId && <Card className="mb-5 p-5">
      <h2 className="mb-4 font-display text-sm font-semibold text-white">{editingId ? "Edit company mapping" : "Add company mapping"}</h2>
      <form onSubmit={(event) => { event.preventDefault(); try { JSON.parse(tableJson); JSON.parse(fieldJson); setMessage(""); writeMapping.mutate(); } catch { setMessage("Table and field mappings must be valid JSON objects."); } }} className="grid gap-4 xl:grid-cols-3">
        <TextField label="Company name" value={companyName} onChange={setCompanyName} placeholder="Northwind Ltd." required />
        <TextField label="Currency code (optional)" value={currencyCode} onChange={(value) => setCurrencyCode(value.toUpperCase().slice(0, 3))} placeholder="USD" maxLength={3} />
        <JsonField label="Canonical → actual tables" value={tableJson} onChange={setTableJson} placeholder={'{ "sales_header": "dbo.Company$Sales Header" }'} />
        <JsonField label="Canonical → actual fields" value={fieldJson} onChange={setFieldJson} placeholder={'{ "sales_header": { "posting_date": "Posting Date" } }'} />
        {(message || writeMapping.isError) && <p role="alert" className="xl:col-span-3 text-xs text-rose-300">{message || errorText(writeMapping.error)}</p>}
        <div className="flex gap-2 xl:col-span-3"><Button type="submit" disabled={writeMapping.isPending}>{writeMapping.isPending ? "Saving…" : editingId ? "Save mapping" : "Add mapping"}</Button>{editingId && <Button type="button" variant="ghost" onClick={reset}>Cancel</Button>}</div>
      </form>
    </Card>}
    {!activeId ? <EmptyState title="Select a database" detail="Company mappings belong to a specific SQL Server connection." /> : mappings.isLoading ? <LoadingState /> : mappings.isError ? <ErrorState message={errorText(mappings.error)} /> : mappings.data?.length ? <div className="grid gap-3 xl:grid-cols-2">{mappings.data.map((item) => <Card key={item.id} className="p-5">
      <div className="flex items-start justify-between gap-3"><div><h3 className="text-sm font-semibold text-slate-200">{item.company_name}</h3><p className="mt-1 text-[10px] capitalize text-slate-600">{item.erp_version.replaceAll("_", " ")} · {item.is_auto_generated ? "inferred from schema" : "administrator mapping"}{item.currency_code ? ` · ${item.currency_code}` : ""}</p></div><span className={cn("rounded-full border px-2.5 py-1 text-[10px]", item.is_auto_generated ? "border-slate-400/10 text-slate-500" : "border-violet-300/15 text-violet-200")}>{Object.keys(item.table_mappings).length} tables</span></div>
      <div className="mt-4 space-y-2">{Object.entries(item.table_mappings).map(([key, value]) => <div key={key} className="flex justify-between gap-3 border-t border-white/[.045] pt-2 text-[11px]"><span className="text-slate-500">{key}</span><code className="truncate text-slate-300">{value}</code></div>)}</div>
      {isAdmin && <div className="mt-4 flex gap-2 border-t border-border pt-3"><Button size="small" variant="secondary" onClick={() => edit(item)}>Edit</Button><Button size="small" variant="ghost" className="text-rose-300" onClick={() => window.confirm(`Delete mappings for ${item.company_name}?`) && removeMapping.mutate(item.id)}><Trash2 size={13} /> Delete</Button></div>}
    </Card>)}</div> : <EmptyState title="No company mappings yet" detail="Refresh the SQL Server schema to infer standard company tables or add a mapping manually." />}
  </>;
}

export function BusinessDictionaryPage() {
  const isAdmin = useAdmin();
  const queryClient = useQueryClient();
  const connections = useConnections();
  const [databaseId, setDatabaseId] = useState("");
  const [companyMappingId, setCompanyMappingId] = useState("");
  const activeId = databaseId || undefined;
  const entries = useQuery({ queryKey: ["business-dictionary", activeId, companyMappingId], queryFn: () => erpApi.listDictionary(activeId, companyMappingId || undefined) });
  const mappings = useQuery({ queryKey: ["company-mappings", activeId], queryFn: () => erpApi.listCompanyMappings(activeId), enabled: Boolean(activeId) });
  const [editingId, setEditingId] = useState<string | null>(null);
  const [term, setTerm] = useState("");
  const [definition, setDefinition] = useState("");
  const [entryType, setEntryType] = useState("term");
  const [message, setMessage] = useState("");
  const writeEntry = useMutation({
    mutationFn: () => {
      const payload = { term, definition, entry_type: entryType, database_connection_id: activeId ?? null, company_mapping_id: companyMappingId || null, enabled: true };
      return editingId ? erpApi.updateDictionaryEntry(editingId, payload) : erpApi.createDictionaryEntry(payload);
    },
    onSuccess: async () => { reset(); await queryClient.invalidateQueries({ queryKey: ["business-dictionary"] }); },
  });
  const removeEntry = useMutation({ mutationFn: erpApi.deleteDictionaryEntry, onSuccess: () => queryClient.invalidateQueries({ queryKey: ["business-dictionary"] }) });
  const reset = () => { setEditingId(null); setTerm(""); setDefinition(""); setEntryType("term"); setMessage(""); };
  const edit = (item: NonNullable<typeof entries.data>[number]) => { setEditingId(item.id); setTerm(item.term); setDefinition(item.definition); setEntryType(item.entry_type); setDatabaseId(item.database_connection_id ?? ""); setCompanyMappingId(item.company_mapping_id ?? ""); };
  const currentMappingOptions = useMemo(() => mappings.data ?? [], [mappings.data]);

  return <>
    <PageHeading eyebrow="PHASE 2 · BUSINESS DICTIONARY" title="Business dictionary" description="Define company-aware terminology, table and field descriptions, approved metrics, and business rules for future natural language analysis." icon={FileText} />
    <div className="mb-5 grid gap-3 sm:grid-cols-2">
      <SelectField label="Scope to database" value={databaseId} onChange={(value) => { setDatabaseId(value); setCompanyMappingId(""); }}><option value="">All connections / global terms</option>{connections.data?.map((connection) => <option key={connection.id} value={connection.id}>{connection.connection_name} · {connection.database}</option>)}</SelectField>
      <SelectField label="Company scope" value={companyMappingId} onChange={setCompanyMappingId}><option value="">All companies in this scope</option>{currentMappingOptions.map((mapping) => <option key={mapping.id} value={mapping.id}>{mapping.company_name}</option>)}</SelectField>
    </div>
    {isAdmin && <Card className="mb-5 p-5">
      <h2 className="mb-4 font-display text-sm font-semibold text-white">{editingId ? "Edit terminology" : "Add terminology"}</h2>
      <form onSubmit={(event) => { event.preventDefault(); writeEntry.mutate(); }} className="grid gap-4 sm:grid-cols-[1fr_1fr_1.4fr_auto]">
        <TextField label="Term" value={term} onChange={setTerm} placeholder="ILE" required />
        <SelectField label="Entry type" value={entryType} onChange={setEntryType}><option value="term">Term</option><option value="table">Table</option><option value="column">Column</option><option value="metric">Metric</option><option value="rule">Business rule</option></SelectField>
        <TextField label="Definition" value={definition} onChange={setDefinition} placeholder="Item Ledger Entry" required />
        <div className="flex items-end"><Button type="submit" disabled={writeEntry.isPending}>{writeEntry.isPending ? "Saving…" : editingId ? "Save" : "Add term"}</Button></div>
        {(message || writeEntry.isError) && <p role="alert" className="sm:col-span-4 text-xs text-rose-300">{message || errorText(writeEntry.error)}</p>}
        {editingId && <Button size="small" type="button" variant="ghost" onClick={reset} className="sm:col-span-4 justify-self-start">Cancel edit</Button>}
      </form>
    </Card>}
    {entries.isLoading ? <LoadingState /> : entries.isError ? <ErrorState message={errorText(entries.error)} /> : entries.data?.length ? <div className="space-y-2">{entries.data.map((item) => <Card key={item.id} className="flex flex-wrap items-start justify-between gap-4 p-4 sm:p-5">
      <div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><h3 className="font-display text-sm font-semibold text-white">{item.term}</h3><span className="rounded-md border border-white/[.07] px-2 py-0.5 text-[9px] uppercase tracking-wider text-slate-500">{item.entry_type}</span>{!item.enabled && <span className="text-[10px] text-amber-300">Disabled</span>}</div><p className="mt-2 text-xs leading-5 text-slate-400">{item.definition}</p><p className="mt-2 text-[10px] text-slate-600">{item.company_mapping_id ? "Company-specific" : item.database_connection_id ? "Database-specific" : "Global"}</p></div>
      {isAdmin && <div className="flex gap-1"><Button size="small" variant="ghost" onClick={() => edit(item)}>Edit</Button><Button size="small" variant="ghost" className="text-rose-300" onClick={() => window.confirm(`Delete ${item.term}?`) && removeEntry.mutate(item.id)}><Trash2 size={13} /></Button></div>}
    </Card>)}</div> : <EmptyState title="Dictionary is empty" detail="Add approved definitions and company-specific rules before building natural language analytics." />}
  </>;
}

function TextField({ label, value, onChange, placeholder, required = false, type = "text", autoComplete, maxLength }: {
  label: string; value: string; onChange: (value: string) => void; placeholder?: string; required?: boolean; type?: string; autoComplete?: string; maxLength?: number;
}) {
  return <label className="block space-y-2 text-xs font-medium text-slate-400">{label}<Input type={type} value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} required={required} autoComplete={autoComplete} maxLength={maxLength} /></label>;
}

function JsonField({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (value: string) => void; placeholder: string }) {
  return <label className="block space-y-2 text-xs font-medium text-slate-400">{label}<textarea value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} rows={4} className="w-full rounded-xl border border-border bg-black/20 px-3 py-2 font-mono text-[11px] text-slate-300 outline-none focus:border-violet-400/60" /></label>;
}

function StatusBadge({ state }: { state: DatabaseConnection["connection_status"] }) {
  const label = state === "connected" ? "Connected" : state === "error" ? "Connection error" : "Untested";
  return <span className={cn("inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px]", state === "connected" ? "border-emerald-400/15 bg-emerald-400/[.05] text-emerald-300" : state === "error" ? "border-rose-400/15 bg-rose-400/[.05] text-rose-300" : "border-white/[.08] text-slate-500")}><StatusDot tone={state === "connected" ? "good" : state === "error" ? "warn" : "neutral"} />{label}</span>;
}

function LoadingState() {
  return <div className="flex items-center justify-center gap-2 rounded-2xl border border-border py-14 text-xs text-slate-500"><LoaderCircle size={15} className="animate-spin" />Loading metadata…</div>;
}

function ErrorState({ message }: { message: string }) {
  return <div role="alert" className="rounded-2xl border border-rose-300/10 bg-rose-300/[.04] px-5 py-4 text-xs text-rose-200">{message}</div>;
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return <div className="rounded-2xl border border-dashed border-border px-5 py-14 text-center"><span className="mx-auto flex size-10 items-center justify-center rounded-xl border border-white/[.07] bg-white/[.025] text-slate-500"><Database size={17} /></span><h2 className="mt-4 font-display text-sm font-semibold text-slate-200">{title}</h2><p className="mx-auto mt-2 max-w-md text-xs leading-5 text-slate-500">{detail}</p></div>;
}
