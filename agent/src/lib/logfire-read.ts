const LOGFIRE_READ_TOKEN = process.env.LOGFIRE_READ_TOKEN ?? "";
const LOGFIRE_READ_URL =
  process.env.LOGFIRE_READ_URL ?? "https://logfire-eu.pydantic.dev/v1/query";

export class LogfireReadError extends Error {
  status: number;
  body: string;
  constructor(message: string, status: number, body: string) {
    super(message);
    this.name = "LogfireReadError";
    this.status = status;
    this.body = body;
  }
}

export interface SpanRow {
  span_id: string;
  parent_span_id: string | null;
  span_name: string;
  start_timestamp: string;
  end_timestamp: string | null;
  duration_ms: number;
  attributes: Record<string, unknown>;
  level: string | null;
}

export interface SpanNode extends SpanRow {
  children: SpanNode[];
}

export interface CostByName {
  span_name: string;
  usd: number;
  tokens_in: number;
  tokens_out: number;
}

export interface CostAggregate {
  total_usd: number;
  total_tokens_in: number;
  total_tokens_out: number;
  by_span: CostByName[];
}

export async function spansForScene(sceneId: string): Promise<SpanRow[]> {
  if (!LOGFIRE_READ_TOKEN) return [];
  // sceneId is route-validated against /^[A-Za-z0-9_-]{1,64}$/, so the
  // single-quote escape below is belt-and-braces.
  const safe = sceneId.replace(/'/g, "''");
  const sql = `SELECT span_id, parent_span_id, span_name, start_timestamp, end_timestamp,
       EXTRACT(EPOCH FROM (end_timestamp - start_timestamp)) * 1000 AS duration_ms,
       attributes, level
FROM records
WHERE attributes->>'scene_id' = '${safe}'
ORDER BY start_timestamp ASC
LIMIT 2000`;

  // Logfire's /v1/query is GET-only and returns column-major JSON
  // (`{ columns: [{ name, values: [...] }, ...] }`).
  const url = `${LOGFIRE_READ_URL}?sql=${encodeURIComponent(sql)}`;
  const res = await fetch(url, {
    headers: { authorization: `Bearer ${LOGFIRE_READ_TOKEN}` },
  });
  if (!res.ok) {
    throw new LogfireReadError(`logfire read ${res.status}`, res.status, await res.text());
  }
  const data = (await res.json()) as {
    columns?: Array<{ name: string; values: unknown[] }>;
  };
  const cols = data.columns ?? [];
  const rowCount = cols[0]?.values.length ?? 0;
  const out: SpanRow[] = [];
  for (let i = 0; i < rowCount; i++) {
    const obj: Record<string, unknown> = {};
    for (const c of cols) obj[c.name] = c.values[i];
    out.push(obj as unknown as SpanRow);
  }
  return out;
}

export function toTree(rows: SpanRow[]): SpanNode[] {
  const byId = new Map<string, SpanNode>();
  rows.forEach((r) => byId.set(r.span_id, { ...r, children: [] }));
  const roots: SpanNode[] = [];
  byId.forEach((node) => {
    const parent = node.parent_span_id ? byId.get(node.parent_span_id) : null;
    if (parent) parent.children.push(node);
    else roots.push(node);
  });
  return roots;
}

export function aggregateCost(rows: SpanRow[]): CostAggregate {
  const bySpan = new Map<string, { usd: number; tokens_in: number; tokens_out: number }>();
  let totalUsd = 0;
  let totalIn = 0;
  let totalOut = 0;
  for (const r of rows) {
    const a = (r.attributes ?? {}) as Record<string, unknown>;
    const usd = num(a["gen_ai.usage.cost"] ?? a["cost_usd"] ?? a["usage.cost"]);
    const tin = num(a["gen_ai.usage.input_tokens"] ?? a["tokens_in"] ?? a["input_tokens"]);
    const tout = num(a["gen_ai.usage.output_tokens"] ?? a["tokens_out"] ?? a["output_tokens"]);
    if (!usd && !tin && !tout) continue;
    const cur = bySpan.get(r.span_name) ?? { usd: 0, tokens_in: 0, tokens_out: 0 };
    cur.usd += usd;
    cur.tokens_in += tin;
    cur.tokens_out += tout;
    bySpan.set(r.span_name, cur);
    totalUsd += usd;
    totalIn += tin;
    totalOut += tout;
  }
  return {
    total_usd: round(totalUsd),
    total_tokens_in: totalIn,
    total_tokens_out: totalOut,
    by_span: [...bySpan.entries()].map(([span_name, v]) => ({
      span_name,
      usd: round(v.usd),
      tokens_in: v.tokens_in,
      tokens_out: v.tokens_out,
    })),
  };
}

function num(v: unknown): number {
  if (typeof v === "number") return v;
  if (typeof v === "string") {
    const n = Number(v);
    return Number.isFinite(n) ? n : 0;
  }
  return 0;
}

function round(n: number): number {
  return Math.round(n * 1_000_000) / 1_000_000;
}
