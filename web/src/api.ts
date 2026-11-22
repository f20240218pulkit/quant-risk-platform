const base = "/api/workbench/v1";

export class RequestError extends Error {
  constructor(message: string, public readonly status: number) {
    super(message);
  }
}

export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(base + path, { ...options, cache: "no-store" });
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: unknown } | null;
    const message = typeof body?.detail === "string" ? body.detail : "The request could not be completed.";
    throw new RequestError(message, response.status);
  }
  return (response.status === 204 ? undefined : await response.json()) as T;
}

export type Sample = { csv: string; dates: string[] };
export type Session = { workspace_id: string };
export type Draft = {
  id: string;
  snapshot_date: string;
  positions: { instrument: string; quantity: string }[];
  issues: { row: number | null; message: string }[];
};
export type ReviewSummary = { id: string; snapshot_date: string; status: "complete" | "partial" };
export type Evidence = {
  instrument: string;
  label: string;
  currency: string;
  quantity: string;
  local_price: string | null;
  aud_fx: string;
  aud_value: string | null;
  weight: string | null;
  issue: string | null;
};
export type Review = ReviewSummary & {
  method: string;
  source: string;
  aud_total: string | null;
  aud_covered_subtotal: string;
  positions: Evidence[];
};
export type Comparison =
  | { eligible: true; aud_change: string; effects: Record<"price" | "fx" | "quantity" | "cash", string> }
  | { eligible: false; reason: string };
