import { z } from "zod";

export const userSchema = z.object({
  id: z.string().uuid(),
  email: z.string().email(),
  full_name: z.string(),
  role: z.enum(["super_admin", "admin", "analyst", "viewer"]),
});

export const authResponseSchema = z.object({ user: userSchema });
export const systemStatusSchema = z.object({
  database: z.string(),
  openrouter_configured: z.boolean(),
  configured_model_count: z.number(),
});

export type User = z.infer<typeof userSchema>;
export type SystemStatus = z.infer<typeof systemStatusSchema>;
