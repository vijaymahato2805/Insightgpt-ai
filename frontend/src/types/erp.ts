import { z } from "zod";

export const databaseConnectionSchema = z.object({
  id: z.string().uuid(),
  connection_name: z.string(),
  company_name: z.string().nullable(),
  server: z.string(),
  database: z.string(),
  authentication_type: z.enum(["sql_server", "windows"]),
  erp_version: z.enum(["nav_2013_r2", "nav_2018", "business_central", "sql_server"]),
  enabled: z.boolean(),
  connection_status: z.enum(["untested", "connected", "error"]),
  last_tested_at: z.string().nullable(),
  last_schema_refresh_at: z.string().nullable(),
  has_credentials: z.boolean(),
  created_at: z.string(),
});

export const databaseConnectionListSchema = z.object({ items: z.array(databaseConnectionSchema) });
export const databaseTestSchema = z.object({ success: z.boolean(), message: z.string() });
export const companyMappingSchema = z.object({
  id: z.string().uuid(),
  database_connection_id: z.string().uuid(),
  company_name: z.string(),
  erp_version: z.enum(["nav_2013_r2", "nav_2018", "business_central", "sql_server"]),
  table_mappings: z.record(z.string(), z.string()),
  field_mappings: z.record(z.string(), z.record(z.string(), z.string())),
    currency_code: z.string().nullable(),
  is_auto_generated: z.boolean(),
  created_at: z.string(),
  updated_at: z.string(),
});
export const companyMappingListSchema = z.object({ items: z.array(companyMappingSchema) });
export const dictionaryEntrySchema = z.object({
  id: z.string().uuid(),
  term: z.string(),
  definition: z.string(),
  entry_type: z.enum(["term", "table", "column", "metric", "rule"]),
  database_connection_id: z.string().uuid().nullable(),
  company_mapping_id: z.string().uuid().nullable(),
  enabled: z.boolean(),
  created_by: z.string().uuid(),
  created_at: z.string(),
  updated_at: z.string(),
});
export const dictionaryListSchema = z.object({ items: z.array(dictionaryEntrySchema) });
export const schemaColumnSchema = z.object({
  id: z.string().uuid(),
  column_name: z.string(),
  ordinal_position: z.number(),
  data_type: z.string(),
  nullable: z.boolean(),
  default_value: z.string().nullable(),
  is_primary_key: z.boolean(),
  is_foreign_key: z.boolean(),
  caption: z.string().nullable(),
  description: z.string().nullable(),
});
export const schemaObjectSchema = z.object({
  id: z.string().uuid(),
  schema_name: z.string(),
  object_name: z.string(),
  object_type: z.enum(["table", "view"]),
  description: z.string().nullable(),
  indexes: z.array(z.record(z.string(), z.unknown())),
  discovered_at: z.string(),
  columns: z.array(schemaColumnSchema),
  relationships: z.array(z.object({
    source_column: z.string(),
    target_schema: z.string(),
    target_table: z.string(),
    target_column: z.string(),
    constraint_name: z.string().nullable(),
  })),
});
export const schemaPageSchema = z.object({
  total: z.number(),
  offset: z.number(),
  limit: z.number(),
  items: z.array(schemaObjectSchema),
});

export type DatabaseConnection = z.infer<typeof databaseConnectionSchema>;
export type DatabaseConnectionInput = {
  connection_name: string;
  company_name?: string | null;
  server: string;
  database: string;
  authentication_type: "sql_server" | "windows";
  username?: string;
  password?: string;
  erp_version: "nav_2013_r2" | "nav_2018" | "business_central" | "sql_server";
  enabled?: boolean;
};
export type CompanyMapping = z.infer<typeof companyMappingSchema>;
export type DictionaryEntry = z.infer<typeof dictionaryEntrySchema>;
export type SchemaObject = z.infer<typeof schemaObjectSchema>;
