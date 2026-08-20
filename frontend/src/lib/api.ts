import type { RawCandle } from "./liveState";

export type HealthStatus = {
  symbol: string;
  ws_connected: boolean;
  last_trade_at: string | null;
  last_backfill_at: string | null;
  backfill_covered_from: string | null;
  reconnect_count: number;
  error_count: number;
  stale: boolean;
};

export type StatsResponse = {
  symbol: string;
  last_price: string | null;
  change_pct: number | null;
  high: string | null;
  low: string | null;
  volume: string | null;
  taker_buy_volume: string;
  taker_sell_volume: string;
};

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`${path} → HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

export function fetchCandles(symbol: string, limit = 1440): Promise<RawCandle[]> {
  return getJson<RawCandle[]>(`/api/candles?symbol=${symbol}&limit=${limit}`);
}

export function fetchStats(symbol: string): Promise<StatsResponse> {
  return getJson<StatsResponse>(`/api/stats?symbol=${symbol}`);
}

export function fetchHealth(): Promise<HealthStatus[]> {
  return getJson<HealthStatus[]>("/api/health");
}

export type ConfigResponse = { symbols: string[] };

export function fetchConfig(): Promise<ConfigResponse> {
  return getJson<ConfigResponse>("/api/config");
}
