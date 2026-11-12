import {
  companyMappingListSchema,
  databaseConnectionListSchema,
  databaseConnectionSchema,
  databaseTestSchema,
  dictionaryListSchema,
  dictionaryEntrySchema,
  schemaPageSchema,
  type DatabaseConnectionInput,
} from "@/types/erp";
import { api } from "@/services/api";

export const erpApi = {
  async listConnections() {
    return databaseConnectionListSchema.parse((await api.get("/databases")).data).items;
  },
  async createConnection(payload: DatabaseConnectionInput) {
    return databaseConnectionSchema.parse((await api.post("/databases", payload)).data);
  },
  async updateConnection(id: string, payload: Record<string, unknown>) {
    return databaseConnectionSchema.parse((await api.put(`/databases/${id}`, payload)).data);
  },
  async deleteConnection(id: string) {
    await api.delete(`/databases/${id}`);
  },
  async testConnection(payload: { database_id: string } | { connection: DatabaseConnectionInput }) {
    return databaseTestSchema.parse((await api.post("/databases/test", payload)).data);
  },
  async listSchema(id: string, search = "") {
    const params: Record<string, string | number> = { limit: 1000 };
    if (search) params.search = search;
    return schemaPageSchema.parse((await api.get(`/schema/${id}`, { params })).data);
  },
  async refreshSchema(id: string) {
    return (await api.post("/schema/refresh", { database_id: id })).data as {
      objects_discovered: number;
      columns_discovered: number;
      relationships_discovered: number;
      captions_applied: number;
    };
  },
  async updateObjectDescription(databaseId: string, objectId: string, description: string) {
    return (await api.put(`/schema/${databaseId}/objects/${objectId}`, { description })).data;
  },
  async updateColumnDescription(databaseId: string, columnId: string, description: string) {
    return (await api.put(`/schema/${databaseId}/columns/${columnId}`, { description })).data;
  },
  async listCompanyMappings(databaseId?: string) {
    return companyMappingListSchema.parse((await api.get("/company-mappings", {
      params: databaseId ? { database_connection_id: databaseId } : {},
    })).data).items;
  },
  async createCompanyMapping(payload: Record<string, unknown>) {
    return (await api.post("/company-mappings", payload)).data;
  },
  async updateCompanyMapping(id: string, payload: Record<string, unknown>) {
    return (await api.put(`/company-mappings/${id}`, payload)).data;
  },
  async deleteCompanyMapping(id: string) {
    await api.delete(`/company-mappings/${id}`);
  },
  async listDictionary(databaseId?: string, companyMappingId?: string) {
    return dictionaryListSchema.parse((await api.get("/business-dictionary", {
      params: {
        ...(databaseId ? { database_connection_id: databaseId } : {}),
        ...(companyMappingId ? { company_mapping_id: companyMappingId } : {}),
      },
    })).data).items;
  },
  async createDictionaryEntry(payload: Record<string, unknown>) {
    return dictionaryEntrySchema.parse((await api.post("/business-dictionary", payload)).data);
  },
  async updateDictionaryEntry(id: string, payload: Record<string, unknown>) {
    return dictionaryEntrySchema.parse((await api.put(`/business-dictionary/${id}`, payload)).data);
  },
  async deleteDictionaryEntry(id: string) {
    await api.delete(`/business-dictionary/${id}`);
  },
};
