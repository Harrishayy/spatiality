// /api/agent/locate — typed agent that answers "where am I looking?"
//
// TypeScript-equivalent of pydantic-ai's typed-agent pattern: zod-validated
// tools, structured-output JSON via Anthropic tool-use, every call routed
// through Pydantic AI Gateway. Logfire-node auto-instruments the SDK so each
// tool round-trip becomes a child span of `agent.locate`.

import type { FastifyPluginAsync } from "fastify";
import { z } from "zod";

import { anthropicClient } from "../lib/gateway.js";

const Vec3 = z.tuple([z.number(), z.number(), z.number()]);

const NearbyObject = z.object({
  id: z.string(),
  label: z.string(),
  centroid: Vec3,
});

const LocateBody = z.object({
  scene_id: z.string().min(1).max(64),
  image_b64: z.string().optional(),
  camera_pos: Vec3,
  camera_dir: Vec3,
  nearby: z.array(NearbyObject).max(64),
});
type LocateBody = z.infer<typeof LocateBody>;

// Closed-form output schema. The agent must emit a tool_use call to the
// `answer` tool with these exact fields — the Anthropic SDK enforces it.
const AnswerSchema = z.object({
  text: z.string().min(1).max(280),
  primary_object_id: z.string().nullable(),
});
type Answer = z.infer<typeof AnswerSchema>;

// JSON Schema for the answer tool. Anthropic SDK consumes JSON Schema, not
// zod directly, so we hand-write it. The shape mirrors AnswerSchema.
const ANSWER_TOOL = {
  name: "answer",
  description:
    "Provide the user-facing answer to 'where am I looking?' along with " +
    "the canonical object id this answer is centred on (null if no clear " +
    "single object). The text should be one short sentence.",
  input_schema: {
    type: "object" as const,
    properties: {
      text: {
        type: "string",
        description: "One-sentence natural-language answer for the user.",
      },
      primary_object_id: {
        type: ["string", "null"],
        description:
          "ID of the object the user is most likely looking at, or null.",
      },
    },
    required: ["text", "primary_object_id"],
  },
};

const SYSTEM = `You answer the question "where is the user looking right now?" in a 3D scan of a room.

You receive:
- camera_pos (x, y, z) and camera_dir (unit vector) in world coordinates
- nearby[]: a list of labelled objects with their centroids in the same frame

Pick the single object the camera is most plausibly facing, judging by the angle between camera_dir and the vector from camera_pos to each centroid. Answer with one short sentence. If the camera isn't facing any object clearly, say so. ALWAYS respond by calling the "answer" tool — never with plain text.`;

const MODEL = process.env.AGENT_MODEL ?? "claude-haiku-4-5";

export const locateRoute: FastifyPluginAsync = async (app) => {
  app.post("/api/agent/locate", async (request, reply) => {
    const t0 = performance.now();
    const parsed = LocateBody.safeParse(request.body);
    if (!parsed.success) {
      return reply.code(400).send({ error: parsed.error.message });
    }
    const body = parsed.data;

    const userMessage = JSON.stringify(
      {
        camera_pos: body.camera_pos,
        camera_dir: body.camera_dir,
        nearby: body.nearby,
      },
      null,
      2,
    );

    let client;
    try {
      client = anthropicClient();
    } catch (err) {
      request.log.error({ err }, "gateway client construction failed");
      return reply.code(500).send({ error: "gateway not configured" });
    }

    let resp;
    try {
      resp = await client.messages.create({
        model: MODEL,
        max_tokens: 400,
        system: SYSTEM,
        tools: [ANSWER_TOOL],
        tool_choice: { type: "tool", name: "answer" },
        messages: [{ role: "user", content: userMessage }],
      });
    } catch (err) {
      request.log.error({ err }, "anthropic call failed");
      return reply.code(502).send({ error: "model call failed" });
    }

    // Find the tool_use block; tool_choice forces it but be defensive.
    const toolBlock = resp.content.find(
      (b: (typeof resp.content)[number]) => b.type === "tool_use",
    );
    if (!toolBlock || toolBlock.type !== "tool_use") {
      request.log.error({ resp }, "no tool_use block returned");
      return reply.code(502).send({ error: "agent returned no tool call" });
    }
    const validated = AnswerSchema.safeParse(toolBlock.input);
    if (!validated.success) {
      request.log.error({ tool: toolBlock.input }, "tool args invalid");
      return reply.code(502).send({ error: "agent tool call malformed" });
    }
    const answer: Answer = validated.data;
    const latencyMs = Math.round(performance.now() - t0);

    return {
      text: answer.text,
      primary_object_id: answer.primary_object_id,
      latency_ms: latencyMs,
      // Echo the model so the UI can show "answered by Haiku 4.5 via Gateway".
      model: MODEL,
    };
  });
};
