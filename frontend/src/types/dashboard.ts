import { z } from "zod";

export const dashboardVisualizationSchema = z.enum([
  "kpi",
  "bar",
  "line",
  "area",
  "pie",
  "donut",
  "table",
]);

export const dashboardFilterSchema = z.object({
  filter_id: z.string(),
  label: z.string(),
  field: z.string(),
  options: z.array(z.string()),
});

export const dashboardWidgetSchema = z.object({
  widget_id: z.string(),
  title: z.string(),
  visualization: dashboardVisualizationSchema,
  question: z.string(),
  layout_span: z.union([z.literal(1), z.literal(2), z.literal(4)]),
  sql: z.string(),
  explanation: z.string(),
  columns: z.array(z.string()),
  rows: z.array(z.record(z.string(), z.unknown())),
  row_count: z.number(),
  truncated: z.boolean(),
  category_field: z.string().nullable(),
  value_field: z.string().nullable(),
  series_field: z.string().nullable(),
  drilldown_field: z.string().nullable(),
});

export const dashboardResponseSchema = z.object({
  database_id: z.string().uuid(),
  company_mapping_id: z.string().uuid().nullable(),
  question: z.string(),
  title: z.string(),
  description: z.string(),
  filters: z.array(dashboardFilterSchema),
  widgets: z.array(dashboardWidgetSchema),
});

export type Dashboard = z.infer<typeof dashboardResponseSchema>;
export type DashboardWidget = z.infer<typeof dashboardWidgetSchema>;
export type DashboardFilter = z.infer<typeof dashboardFilterSchema>;
