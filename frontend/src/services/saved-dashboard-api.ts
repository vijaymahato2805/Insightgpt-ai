import { z } from "zod";
import { api } from "@/services/api";
import { dashboardResponseSchema, type Dashboard } from "@/types/dashboard";

export const savedDashboardSchema = z.object({
  id: z.string().uuid(),
  database_id: z.string().uuid(),
  company_mapping_id: z.string().uuid().nullable(),
  title: z.string(),
  question: z.string(),
  is_favorite: z.boolean(),
  current_version: z.number(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type SavedDashboard = z.infer<typeof savedDashboardSchema>;
export type DashboardDefinition = {
  database_id: string;
  company_mapping_id: string | null;
  title: string;
  description: string;
  question: string;
  filters: { filter_id: string; label: string; field: string }[];
  widgets: {
    widget_id: string;
    title: string;
    visualization: Dashboard["widgets"][number]["visualization"];
    question: string;
    layout_span: 1 | 2 | 4;
    sql: string;
    explanation: string;
    category_field: string | null;
    value_field: string | null;
    series_field: string | null;
    drilldown_field: string | null;
  }[];
};

export function dashboardDefinition(dashboard: Dashboard): DashboardDefinition {
  return {
    database_id: dashboard.database_id,
    company_mapping_id: dashboard.company_mapping_id,
    title: dashboard.title,
    description: dashboard.description,
    question: dashboard.question,
    filters: dashboard.filters.map(({ filter_id, label, field }) => ({ filter_id, label, field })),
    widgets: dashboard.widgets.map((widget) => ({
      widget_id: widget.widget_id,
      title: widget.title,
      visualization: widget.visualization,
      question: widget.question,
      layout_span: widget.layout_span,
      sql: widget.sql,
      explanation: widget.explanation,
      category_field: widget.category_field,
      value_field: widget.value_field,
      series_field: widget.series_field,
      drilldown_field: widget.drilldown_field,
    })),
  };
}

export const savedDashboardApi = {
  async list() {
    return z.object({ items: z.array(savedDashboardSchema) }).parse((await api.get("/saved-dashboards")).data).items;
  },
  async create(dashboard: Dashboard) {
    return savedDashboardSchema.parse((await api.post("/saved-dashboards", { dashboard: dashboardDefinition(dashboard) })).data);
  },
  async update(id: string, expectedVersion: number, dashboard: DashboardDefinition) {
    return savedDashboardSchema.parse((await api.put(`/saved-dashboards/${id}`, { expected_version: expectedVersion, dashboard })).data);
  },
  async get(id: string, filters: Record<string, string> = {}) {
    const params = Object.keys(filters).length ? { filters: JSON.stringify(filters) } : undefined;
    return dashboardResponseSchema.parse((await api.get(`/saved-dashboards/${id}`, { params })).data);
  },
  async versions(id: string) {
    return z.object({
      dashboard_id: z.string().uuid(),
      current_version: z.number(),
      items: z.array(z.object({ version_number: z.number(), title: z.string(), created_by: z.string().uuid(), created_at: z.string() })),
    }).parse((await api.get(`/saved-dashboards/${id}/versions`)).data);
  },
  async restore(id: string, version: number) {
    return savedDashboardSchema.parse((await api.post(`/saved-dashboards/${id}/versions/${version}/restore`)).data);
  },
  async favorite(id: string, isFavorite: boolean) {
    return savedDashboardSchema.parse((await api.patch(`/saved-dashboards/${id}/favorite`, { is_favorite: isFavorite })).data);
  },
  async delete(id: string) {
    await api.delete(`/saved-dashboards/${id}`);
  },
  async export(id: string, format: "xlsx" | "pdf", filters: Record<string, string> = {}) {
    const params = Object.keys(filters).length ? { format, filters: JSON.stringify(filters) } : { format };
    return (await api.get(`/saved-dashboards/${id}/export`, { params, responseType: "blob" })).data as Blob;
  },
};
