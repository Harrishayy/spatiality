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
  trace_id: string;
  span_name: string;
  start_timestamp: string;
  end_timestamp: string | null;
  duration_ms: number;
  /** Convenience field — `duration_ms / 1000`. Frontend prefers this; we
   *  keep `duration_ms` too for older clients. */
  duration: number;
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
  /** Number of model calls aggregated into the totals. The frontend's
   *  CostBadge surfaces this as "N calls" alongside the dollar figure. */
  call_count: number;
  total_tokens_in: number;
  total_tokens_out: number;
  by_span: CostByName[];
}

export async function spansForScene(sceneId: string): Promise<SpanRow[]> {
  if (!LOGFIRE_READ_TOKEN) return [];
  // sceneId is route-validated against /^[A-Za-z0-9_-]{1,64}$/, so the
  // single-quote escape below is belt-and-braces.
  const safe = sceneId.replace(/'/g, "''");
  // Fan out by trace_id, not by attribute. Only the top-level wrapper spans
  // (modal.process_video, segmentation.lift.project, agent.chat, …) tag
  // scene_id explicitly — OTel attributes don't auto-propagate to children,
  // so filtering on `attributes->>'scene_id'` would drop every gen_ai.* span
  // from `instrument_anthropic()`, every modal.subprocess, and every nested
  // segmentation.lift.* sub-stage. The inner SELECT collects the trace_ids
  // that touch this scene; the JOIN returns every span under those traces.
  //
  // INNER JOIN — not `WHERE trace_id IN (SELECT DISTINCT ...)`. DataFusion
  // (Logfire's query engine) returns
  //   `type_coercion: expressions have incompatible types`
  // for the IN-subquery form against `trace_id`, but handles JOIN cleanly.
  // Same semantics, no error.
  const sql = `SELECT r.span_id, r.parent_span_id, r.trace_id, r.span_name,
       r.start_timestamp, r.end_timestamp,
       EXTRACT(EPOCH FROM (r.end_timestamp - r.start_timestamp)) * 1000 AS duration_ms,
       EXTRACT(EPOCH FROM (r.end_timestamp - r.start_timestamp)) AS duration,
       r.attributes, r.level
FROM records AS r
INNER JOIN (
  SELECT DISTINCT trace_id
  FROM records
  WHERE attributes->>'scene_id' = '${safe}'
) AS t ON r.trace_id = t.trace_id
ORDER BY r.start_timestamp ASC`;

  // Logfire's /v1/query is GET-only and returns column-major JSON
  // (`{ columns: [{ name, values: [...] }, ...] }`). The endpoint caps the
  // response at 100 rows by default; `LIMIT N` inside the SQL is *ignored*.
  // Pass `?limit=` as a URL parameter to lift the cap — without this we'd
  // truncate any pipeline busier than ~3 stages and the trace drawer would
  // appear to show only the "top" spans (silently).
  const url = `${LOGFIRE_READ_URL}?limit=5000&sql=${encodeURIComponent(sql)}`;
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
  let callCount = 0;
  for (const r of rows) {
    const a = (r.attributes ?? {}) as Record<string, unknown>;
    // `gen_ai.usage.cost` is what `logfire.instrument_anthropic()` writes;
    // the older snake_case keys are what segmentation/vlm.py and the agent
    // chat span attach by hand. `est_cost_usd` is the segmentation labeler's
    // backstop estimate (used when the gateway hasn't auto-tagged the call).
    const usd = num(
      a["gen_ai.usage.cost"] ??
        a["cost_usd"] ??
        a["usage.cost"] ??
        a["est_cost_usd"],
    );
    const tin = num(a["gen_ai.usage.input_tokens"] ?? a["tokens_in"] ?? a["input_tokens"]);
    const tout = num(a["gen_ai.usage.output_tokens"] ?? a["tokens_out"] ?? a["output_tokens"]);
    if (!usd && !tin && !tout) continue;
    callCount += 1;
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
    call_count: callCount,
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
