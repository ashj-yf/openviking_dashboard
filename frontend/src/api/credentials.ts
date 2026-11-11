import { apiRequest } from "@/api/client";
import type { Schema } from "@/types/api";

export type CredentialView = Schema["CredentialView"];
export type RevealedKey = Schema["RevealedKeyOut"];

export const credentialApi = {
  get(): Promise<CredentialView> {
    return apiRequest<CredentialView>("GET", "/credentials");
  },
  revealKey(): Promise<RevealedKey> {
    return apiRequest<RevealedKey>("POST", "/credentials/reveal");
  },
  copyKey(): Promise<RevealedKey> {
    return apiRequest<RevealedKey>("POST", "/credentials/copy");
  },
  regenerateOwnKey(seed?: string): Promise<RevealedKey> {
    return apiRequest<RevealedKey>("POST", "/credentials/regenerate", {
      body: { seed: seed || null },
    });
  },
};
