import { requestJson } from "./client";

export type ClaudeConnection = "api_key" | "subscription";
export type ChainKind = "default" | "complex";
export type ProviderHealthStatus =
  | "ok"
  | "not_configured"
  | "disabled"
  | "auth_error"
  | "rate_limited"
  | "unavailable";

export interface ProviderInfo {
  name: string;
  enabled: boolean;
  experimental: boolean;
  needs_key: boolean;
  key_configured: boolean;
  model: string | null;
}

export interface ProvidersOverview {
  claude_connection: ClaudeConnection;
  subscription_available: boolean;
  chains: Record<ChainKind, string[]>;
  providers: ProviderInfo[];
  experimental_warning: string;
}

export interface ProviderHealth {
  name: string;
  status: ProviderHealthStatus;
  detail: string | null;
  latency_ms: number | null;
  experimental: boolean;
  extra: Record<string, unknown>;
}

export interface ProvidersConfigUpdate {
  claude_connection?: ClaudeConnection;
  chains?: Partial<Record<ChainKind, string[]>>;
  enabled?: Record<string, boolean>;
  models?: Record<string, string>;
}

export function getProviders(): Promise<ProvidersOverview> {
  return requestJson<ProvidersOverview>("/api/providers");
}

export function getProvidersHealth(): Promise<ProviderHealth[]> {
  return requestJson<ProviderHealth[]>("/api/providers/health");
}

export function updateProvidersConfig(update: ProvidersConfigUpdate): Promise<ProvidersOverview> {
  return requestJson<ProvidersOverview>("/api/providers/config", {
    method: "PUT",
    body: JSON.stringify(update),
  });
}

export function saveProviderKey(name: string, apiKey: string): Promise<ProvidersOverview> {
  return requestJson<ProvidersOverview>(`/api/providers/${encodeURIComponent(name)}/key`, {
    method: "POST",
    body: JSON.stringify({ api_key: apiKey }),
  });
}

export function deleteProviderKey(name: string): Promise<ProvidersOverview> {
  return requestJson<ProvidersOverview>(`/api/providers/${encodeURIComponent(name)}/key`, { method: "DELETE" });
}
