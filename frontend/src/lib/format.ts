export const DASH = "—";

/** 백엔드는 numeric을 정밀도 손실 없이 넘기려고 문자열로 직렬화한다. */
export function toNumber(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function formatPrice(value: number | string | null | undefined, digits = 2): string {
  const num = toNumber(value);
  if (num === null) return DASH;
  return num.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function formatChangePct(pct: number | string | null | undefined): string {
  const num = toNumber(pct);
  if (num === null) return DASH;
  const sign = num > 0 ? "+" : "";
  return `${sign}${num.toFixed(2)}%`;
}

export function formatCompact(value: number | string | null | undefined): string {
  const num = toNumber(value);
  if (num === null) return DASH;
  const abs = Math.abs(num);
  if (abs >= 1e9) return `${(num / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${(num / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${(num / 1e3).toFixed(2)}K`;
  return num.toFixed(2);
}

/** 데이터 신선도를 한눈에 보게 하는 상대 시간 표기. */
export function formatAge(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return DASH;
  if (seconds < 1) return "방금";
  if (seconds < 60) return `${Math.floor(seconds)}초 전`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}분 전`;
  return `${Math.floor(seconds / 3600)}시간 전`;
}

export function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return DASH;
  return new Date(ms).toISOString().replace("T", " ").slice(0, 19) + "Z";
}

export function formatDirection(pct: number | null | undefined): "up" | "down" | "flat" {
  const num = toNumber(pct);
  if (num === null || num === 0) return "flat";
  return num > 0 ? "up" : "down";
}
