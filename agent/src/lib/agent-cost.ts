// Per-scene cost accumulator for agent-side model calls (chat / tool-use
// turns). The agent service does not run Logfire / OTel, so without this
// store every model call routed through `agent/src/routes/chat.ts` is
// invisible to `/api/trace/:scene_id` and the scenes-page CostBadge shows
// the segmentation labeler's totals only — chat usage was a silent gap.
//
// This is in-memory and dies with the process. That's fine for the badge's
// "what did this scene cost while you were on it" UX. Per-call rows are
// also written into the trace endpoint's snapshot so the agent's view
// survives a restart, but the in-memory map is the live source of truth.

interface AgentCost {
  /** Number of model calls (one per messages.create) for this scene. */
  call_count: number;
  /** USD spent across those calls — sum of est cost for each call. */
  total_usd: number;
  total_tokens_in: number;
  total_tokens_out: number;
}

const EMPTY: AgentCost = {
  call_count: 0,
  total_usd: 0,
  total_tokens_in: 0,
  total_tokens_out: 0,
};

const byScene = new Map<string, AgentCost>();

interface ModelPrice {
  input_per_m: number;
  output_per_m: number;
}

// Per-model pricing (USD per 1M tokens). Mirrors the segmentation labeler's
// _HAIKU_INPUT_PER_M / _HAIKU_OUTPUT_PER_M numbers and adds the other models
// the SettingsPanel exposes. Update if Anthropic publishes new prices.
const PRICE: Record<string, ModelPrice> = {
  "claude-haiku-4-5":  { input_per_m: 1.0,  output_per_m: 5.0 },
  "claude-sonnet-4-6": { input_per_m: 3.0,  output_per_m: 15.0 },
  "claude-opus-4-7":   { input_per_m: 15.0, output_per_m: 75.0 },
};

const DEFAULT_PRICE: ModelPrice = PRICE["claude-haiku-4-5"];

function priceFor(model: string): ModelPrice {
  // Looser match — covers timestamped snapshots like
  // `claude-haiku-4-5-20251001` that some Anthropic responses report.
  for (const [prefix, p] of Object.entries(PRICE)) {
    if (model === prefix || model.startsWith(prefix)) return p;
  }
  return DEFAULT_PRICE;
}

export function estimateCallCost(
  model: string,
  tokensIn: number,
  tokensOut: number,
): number {
  const p = priceFor(model);
  return (
    (tokensIn / 1_000_000) * p.input_per_m +
    (tokensOut / 1_000_000) * p.output_per_m
  );
}

export interface RecordCallParams {
  scene_id: string;
  model: string;
  tokens_in: number;
  tokens_out: number;
  /** Optional override — when the SDK / gateway already knows the cost, pass
   *  it directly. Otherwise we fall back to `estimateCallCost`. */
  usd?: number;
}

export function recordModelCall(p: RecordCallParams): void {
  const usd = p.usd ?? estimateCallCost(p.model, p.tokens_in, p.tokens_out);
  const cur = byScene.get(p.scene_id) ?? { ...EMPTY };
  cur.call_count += 1;
  cur.total_usd += usd;
  cur.total_tokens_in += p.tokens_in;
  cur.total_tokens_out += p.tokens_out;
  byScene.set(p.scene_id, cur);
}

export function getAgentCost(sceneId: string): AgentCost {
  return byScene.get(sceneId) ?? EMPTY;
}
