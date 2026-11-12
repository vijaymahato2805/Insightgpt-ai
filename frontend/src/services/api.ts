import axios from "axios";
import { authResponseSchema, systemStatusSchema, userSchema } from "@/types/auth";

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api",
  withCredentials: true,
  headers: { "Content-Type": "application/json" },
});

export const authApi = {
  async login(email: string, password: string) {
    const response = await api.post("/auth/login", { email, password });
    return authResponseSchema.parse(response.data).user;
  },
  async me() {
    const response = await api.get("/auth/me");
    return userSchema.parse(response.data);
  },
  async logout() {
    await api.post("/auth/logout");
  },
};

export const systemApi = {
  async status() {
    const response = await api.get("/system/status");
    return systemStatusSchema.parse(response.data);
  },
};
