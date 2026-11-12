import { api } from "@/services/api";

export type AnalysisFilter = { field: string; value: string };
export type ConversationMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  sql: string | null;
  result_columns: string[];
  result_rows: Record<string, unknown>[];
  row_count: number;
  truncated: boolean;
  created_at: string;
};
export type ConversationSummary = {
  id: string;
  database_connection_id: string;
  company_mapping_id: string | null;
  title: string;
  active_filters: AnalysisFilter[];
  updated_at: string;
  message_count: number;
};
export type Conversation = ConversationSummary & { messages: ConversationMessage[] };

export const analysisApi = {
  async listConversations() {
    return (await api.get<{ items: ConversationSummary[] }>("/conversations")).data.items;
  },
  async getConversation(id: string) {
    return (await api.get<Conversation>(`/conversations/${id}`)).data;
  },
  async deleteConversation(id: string) {
    await api.delete(`/conversations/${id}`);
  },
  async ask(payload: {
    conversation_id?: string;
    database_id?: string;
    company_mapping_id?: string;
    question: string;
    active_filters?: AnalysisFilter[];
  }) {
    return (await api.post<Conversation>("/conversations/ask", payload)).data;
  },
  async insights(payload: { database_id: string; company_mapping_id?: string; question: string; max_insights?: number }) {
    return (await api.post<InsightResponse>("/insights/generate", payload)).data;
  },
  async comparePeriods(payload: {
    database_id: string;
    company_mapping_id?: string;
    question: string;
    date_field: string;
    metric_field: string;
    dimension_fields: string[];
    current_start: string;
    current_end: string;
    comparison_start: string;
    comparison_end: string;
  }) {
    return (await api.post<PeriodComparisonResponse>("/comparisons/periods", payload)).data;
  },
  async compareCompanies(payload: {
    database_id: string;
    company_mapping_ids: string[];
    question: string;
    metric_field: string;
    dimension_fields: string[];
    currency_fields: string[];
    target_currency_code?: string;
    exchange_rates?: Record<string, string>;
  }) {
    return (await api.post<CompanyComparisonResponse>("/comparisons/companies", payload)).data;
  },
};

export type InsightResponse = {
  database_id: string;
  company_mapping_id: string | null;
  company_name: string | null;
  question: string;
  sql: string;
  columns: string[];
  row_count: number;
  truncated: boolean;
  summary: string;
  insights: { title: string; observation: string; direction: "up" | "down" | "flat" | "notable" | "caution"; evidence: { field: string; value: unknown }[] }[];
};
export type PeriodComparisonResponse = {
  currency_code: string | null;
  metric_field: string;
  rows: { dimensions: Record<string, unknown>; current_value: string | null; comparison_value: string | null; absolute_change: string | null; percentage_change: string | null }[];
};
export type CompanyComparisonResponse = {
  metric_field: string;
  dimension_fields: string[];
  baseline_company: string;
  target_currency_code: string | null;
  companies: { company_mapping_id: string; company_name: string; source_currency_code: string | null; columns: string[]; rows: Record<string, unknown>[] }[];
  rows: { dimensions: Record<string, unknown>; values_by_company: Record<string, string | null>; changes_vs_baseline: Record<string, { absolute_change: string; percentage_change: string | null }> }[];
};
