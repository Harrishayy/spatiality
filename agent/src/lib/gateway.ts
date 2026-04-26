import Anthropic from "@anthropic-ai/sdk";

const GATEWAY_URL =
  process.env.PYDANTIC_GATEWAY_URL ?? "https://gateway-eu.pydantic.dev/proxy/anthropic/";
const GATEWAY_KEY =
  process.env.PYDANTIC_GATEWAY_KEY ?? process.env.PYDANTIC_API_KEY ?? "";

export function anthropicClient(): Anthropic {
  if (!GATEWAY_KEY) throw new Error("PYDANTIC_GATEWAY_KEY is not set");
  return new Anthropic({ baseURL: GATEWAY_URL, authToken: GATEWAY_KEY });
}
