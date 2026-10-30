import { healthRequest } from "@/api/client";
import type { Schema } from "@/types/api";

export type Health = Schema["HealthResponse"];

export function getHealth(signal?: AbortSignal): Promise<Health> {
  return healthRequest(signal);
}
