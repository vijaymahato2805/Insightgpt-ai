import { z } from "zod";

export const queryIntentSchema = z.object({
  intent: z.string(),
  metrics: z.array(z.string()),
  dimensions: z.array(z.string()),
  filters: z.array(z.string()),
  time_period: z.string().nullable(),
  requested_company: z.string().nullable(),
  needs_clarification: z.boolean(),
  clarification: z.string().nullable(),
});

export const tokenUsageSchema = z.object({
  prompt_tokens: z.number(),
  completion_tokens: z.number(),
  total_tokens: z.number(),
});

export const sqlGenerationSchema = z.object({
  database_id: z.string().uuid(),
  company_mapping_id: z.string().uuid().nullable(),
  question: z.string(),
  intent: queryIntentSchema,
  sql: z.string().nullable(),
  explanation: z.string().nullable(),
  explanation_notes: z.array(z.string()),
  selected_tables: z.array(z.string()),
  business_terms: z.array(z.string()),
  assumptions: z.array(z.string()),
  needs_clarification: z.boolean(),
  clarification: z.string().nullable(),
  token_usage: tokenUsageSchema,
});

export const sqlExecutionSchema = z.object({
  database_id: z.string().uuid(),
  sql: z.string(),
  tables: z.array(z.string()),
  columns: z.array(z.string()),
  rows: z.array(z.record(z.string(), z.unknown())),
  row_count: z.number(),
  truncated: z.boolean(),
  max_rows: z.number(),
});

export type SQLGeneration = z.infer<typeof sqlGenerationSchema>;
export type SQLExecution = z.infer<typeof sqlExecutionSchema>;
