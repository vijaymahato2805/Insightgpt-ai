import { api } from "@/services/api";
import { dashboardResponseSchema, type Dashboard } from "@/types/dashboard";

export type DashboardRequest = {
  database_id: string;
  company_mapping_id?: string;
  question: string;
};

export const dashboardApi = {
  async generate(input: DashboardRequest): Promise<Dashboard> {
    const response = await api.post("/dashboards/generate", input);
    return dashboardResponseSchema.parse(response.data);
  },
};
