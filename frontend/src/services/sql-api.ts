import { api } from "@/services/api";
import {
  sqlExecutionSchema,
  sqlGenerationSchema,
  type SQLExecution,
  type SQLGeneration,
} from "@/types/sql";

export type SQLQuestionInput = {
  database_id: string;
  company_mapping_id?: string;
  question: string;
};

export const sqlApi = {
  async generate(input: SQLQuestionInput): Promise<SQLGeneration> {
    const response = await api.post("/sql/generate", input);
    return sqlGenerationSchema.parse(response.data);
  },
  async execute(input: { database_id: string; company_mapping_id?: string; sql: string }): Promise<SQLExecution> {
    const response = await api.post("/sql/execute", input);
    return sqlExecutionSchema.parse(response.data);
  },
};
