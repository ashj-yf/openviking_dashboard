import { healthRequest, type HealthResponse } from "@/api/client";

export type Health = HealthResponse;

export function getHealth(signal?: AbortSignal): Promise<Health> {
  return healthRequest(signal);
}
