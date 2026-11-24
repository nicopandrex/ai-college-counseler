import { z } from "zod";

const EnvSchema = z.object({
  SOLVER_URL: z.string().url().default("http://localhost:8000"),
});

export type Env = z.infer<typeof EnvSchema>;

export function readEnv(source: Record<string, string | undefined>): Env {
  return EnvSchema.parse(source);
}
