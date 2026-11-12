import { lazy, Suspense, useState } from "react";
import type { Dashboard, DashboardWidget } from "@/types/dashboard";
import { Card } from "@/components/ui";

const ChartCard = lazy(() => import("@/components/dashboard-chart").then((module) => ({ default: module.ChartCard })));

type DrillSelection = { field: string; value: string } | null;

export function DashboardRenderer({ dashboard, onFiltersChange }: { dashboard: Dashboard; onFiltersChange?: (filters: Record<string, string>) => void }) {
  const [filterValues, setFilterValues] = useState<Record<string, string>>({});
  const [drillSelection, setDrillSelection] = useState<DrillSelection>(null);

  const activeFilters = dashboard.filters.filter((filter) => filterValues[filter.filter_id]);
  const filters = activeFilters.map((filter) => ({
    field: filter.field,
    value: filterValues[filter.filter_id],
  }));

  return (
    <div className="space-y-5">
      {(dashboard.filters.length > 0 || drillSelection) && (
        <Card className="flex flex-wrap items-end gap-3 p-4 sm:p-5">
          {dashboard.filters.map((filter) => (
            <label key={filter.filter_id} className="min-w-[170px] flex-1 space-y-1.5 text-[10px] font-semibold uppercase tracking-[.12em] text-slate-500">
              {filter.label}
              <select
                value={filterValues[filter.filter_id] ?? ""}
                onChange={(event) => setFilterValues((current) => {
                  const next = { ...current, [filter.filter_id]: event.target.value };
                  onFiltersChange?.(Object.fromEntries(Object.entries(next).filter(([, value]) => value)));
                  return next;
                })}
                className="h-10 w-full rounded-lg border border-border bg-[#11131c] px-3 text-xs font-normal normal-case tracking-normal text-white outline-none focus:border-primary/70"
              >
                <option value="">All {filter.label.toLowerCase()}</option>
                {filter.options.map((option) => <option key={option} value={option}>{option}</option>)}
              </select>
            </label>
          ))}
          {drillSelection && (
            <div className="flex h-10 items-center gap-2 rounded-lg border border-violet-300/15 bg-violet-300/[.06] px-3 text-xs text-violet-100">
              <span className="max-w-[220px] truncate">Drill-down · {drillSelection.field}: {drillSelection.value}</span>
              <button type="button" onClick={() => setDrillSelection(null)} className="rounded px-1 text-violet-200/70 hover:text-white" aria-label="Clear drill-down">×</button>
            </div>
          )}
          {(activeFilters.length > 0 || drillSelection) && (
            <button type="button" onClick={() => { setFilterValues({}); onFiltersChange?.({}); setDrillSelection(null); }} className="h-10 px-2 text-xs text-slate-500 hover:text-white">Clear all</button>
          )}
        </Card>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {dashboard.widgets.map((widget) => {
          const rows = widget.rows.filter((row) => {
            const matchesFilters = filters.every(({ field, value }) => (
              !widget.columns.includes(field) || stringify(row[field]) === value
            ));
            const matchesDrill = !drillSelection
              || !widget.columns.includes(drillSelection.field)
              || stringify(row[drillSelection.field]) === drillSelection.value;
            return matchesFilters && matchesDrill;
          });
          return (
            <DashboardWidgetCard
              key={widget.widget_id}
              widget={widget}
              rows={rows}
              onDrillDown={(field, value) => setDrillSelection({ field, value })}
            />
          );
        })}
      </div>
    </div>
  );
}

function DashboardWidgetCard({
  widget,
  rows,
  onDrillDown,
}: {
  widget: DashboardWidget;
  rows: Array<Record<string, unknown>>;
  onDrillDown: (field: string, value: string) => void;
}) {
  const spanClass = widget.layout_span === 4
    ? "sm:col-span-2 xl:col-span-4"
    : widget.layout_span === 2
      ? "sm:col-span-2 xl:col-span-2"
      : "sm:col-span-1 xl:col-span-1";

  return (
    <Card className={`min-w-0 overflow-hidden ${spanClass}`}>
      <div className="flex items-start justify-between gap-3 border-b border-border px-4 py-3.5 sm:px-5">
        <div className="min-w-0">
          <h2 className="truncate text-sm font-semibold text-white">{widget.title}</h2>
          <p className="mt-1 text-[10px] text-slate-600">{rows.length} rows{widget.truncated ? " · query result capped" : ""}</p>
        </div>
        <span className="shrink-0 rounded-md border border-white/[.07] bg-white/[.025] px-2 py-1 text-[9px] uppercase tracking-[.1em] text-slate-500">{widget.visualization}</span>
      </div>

      <div className="min-h-[190px] p-4 sm:p-5">
        {widget.visualization === "kpi" ? (
          <KpiCard widget={widget} rows={rows} />
        ) : widget.visualization === "table" ? (
          <DataTable widget={widget} rows={rows} onDrillDown={onDrillDown} />
        ) : (
          <Suspense fallback={<div className="flex min-h-[150px] items-center justify-center text-xs text-slate-500">Loading chart…</div>}>
            <ChartCard widget={widget} rows={rows} onDrillDown={onDrillDown} />
          </Suspense>
        )}
      </div>

      <details className="border-t border-border px-4 py-3 sm:px-5">
        <summary className="cursor-pointer text-[10px] font-medium text-slate-500 hover:text-slate-300">Query details</summary>
        <p className="mt-2 text-[10px] leading-5 text-slate-500">{widget.explanation}</p>
        <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-black/20 p-3 font-mono text-[10px] leading-5 text-emerald-100">{widget.sql}</pre>
      </details>
    </Card>
  );
}

export function KpiCard({ widget, rows }: { widget: DashboardWidget; rows: Array<Record<string, unknown>> }) {
  const raw = rows[0] && widget.value_field ? rows[0][widget.value_field] : undefined;
  const numeric = numericValue(raw);
  return (
    <div className="flex min-h-[145px] flex-col justify-center">
      {numeric === null ? (
        <p className="text-sm text-slate-500">No metric value for the current filters.</p>
      ) : (
        <p className="font-display text-4xl font-semibold tracking-[-.06em] text-white sm:text-5xl">{formatNumber(numeric)}</p>
      )}
      <p className="mt-2 truncate text-xs text-slate-500">{widget.value_field ?? "Query result"}</p>
      {widget.truncated && <p className="mt-2 text-[10px] text-amber-200/70">Showing the first rows returned by the safe query limit.</p>}
    </div>
  );
}

export function DataTable({
  widget,
  rows,
  onDrillDown,
}: {
  widget: DashboardWidget;
  rows: Array<Record<string, unknown>>;
  onDrillDown: (field: string, value: string) => void;
}) {
  if (rows.length === 0) return <EmptyState />;
  return (
    <div className="max-h-[360px] overflow-auto rounded-xl border border-white/[.05]">
      <table className="w-full min-w-max border-collapse text-left text-[11px]">
        <thead className="sticky top-0 bg-[#151722] text-slate-400"><tr>{widget.columns.map((column) => <th key={column} className="border-b border-border px-3 py-2.5 font-medium">{column}</th>)}</tr></thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index} className="border-b border-white/[.04] text-slate-300 last:border-0">
              {widget.columns.map((column) => (
                <td key={column} className="max-w-[280px] truncate px-3 py-2.5">
                  {column === widget.drilldown_field && widget.drilldown_field ? (
                    <button type="button" className="text-left text-violet-200 hover:underline" onClick={() => onDrillDown(column, stringify(row[column]))}>
                      {stringify(row[column])}
                    </button>
                  ) : stringify(row[column])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EmptyState({ message = "No rows for the current filters." }: { message?: string }) {
  return <div className="flex min-h-[150px] items-center justify-center rounded-xl border border-dashed border-white/[.07] px-5 text-center text-xs text-slate-600">{message}</div>;
}

function numericValue(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value !== "string") return null;
  const parsed = Number(value.replaceAll(",", ""));
  return Number.isFinite(parsed) ? parsed : null;
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value);
}

function stringify(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}
