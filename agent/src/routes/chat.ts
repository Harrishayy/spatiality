// /api/agent/chat — multimodal chat about a 3D scene.
//
// Tool-use loop with four tools:
//   - get_frames_for_object: fetches up to 4 keyframes where an object
//     appears and feeds them back as image content for visual reasoning
//     (e.g. "what's next to Stitch?" → looks at Stitch's frames → "a penguin").
//   - locate_object: returns annotation centroid/bbox; web client highlights it.
//   - move_camera_to: returns a camera target; web client animates the view.
//   - describe_scene: returns the labeled object inventory.

import type { FastifyPluginAsync } from "fastify";
import type { MessageParam, ToolUnion } from "@anthropic-ai/sdk/resources/messages.js";
import { z } from "zod";

import { recordModelCall } from "../lib/agent-cost.js";
import { anthropicClient } from "../lib/gateway.js";
import {
  type AnnotationLite,
  type FrameImage,
  fetchFramesForAnnotation,
  loadAnnotations,
  resolveAnnotation,
} from "../lib/frames.js";
import { SceneIdSchema } from "../schemas.js";

const Vec3 = z.tuple([z.number(), z.number(), z.number()]);

const ChatBody = z.object({
  scene_id: SceneIdSchema,
  message: z.string().min(1).max(2000),
  camera_pos: Vec3.optional(),
});
type ChatBody = z.infer<typeof ChatBody>;

const MODEL = process.env.AGENT_MODEL ?? "claude-haiku-4-5";
const MAX_TOOL_ITERS = 3;
const FRAMES_PER_CALL = 4;

const SYSTEM_PROMPT = (
  objectsList: string,
) => `You answer questions about a 3D scene of a real room.

Objects in this scene (id — label):
${objectsList || "(none yet)"}

When the user asks something that needs visual evidence about a specific labelled object — what it looks like, what's next to it, what colour it is, what's on top of it — call the \`get_frames_for_object\` tool with the matching label or id. The tool returns photos of that object; reason from them.

When the user asks where an object is, call \`locate_object\` so the viewer can highlight it.
When the user asks to look at or fly to an object, call \`move_camera_to\`.
When the user asks what's in the scene, call \`describe_scene\`.

Otherwise answer briefly from the labels alone. Keep answers to one or two sentences.`;

const TOOLS: ToolUnion[] = [
  {
    name: "get_frames_for_object",
    description:
      "Fetch up to 4 keyframes from the scene where a specific object appears, so you can look at the photos and answer visual questions about that object (what it is, what's near it, colour, etc.).",
    input_schema: {
      type: "object",
      properties: {
        label_or_id: {
          type: "string",
          description:
            "The object's label (e.g. 'Stitch') or its id (e.g. 'obj_004'). Match is case-insensitive and tolerates substrings.",
        },
      },
      required: ["label_or_id"],
    },
  },
  {
    name: "locate_object",
    description:
      "Highlight a specific labelled object in the 3D viewer. Returns its centroid + bbox.",
    input_schema: {
      type: "object",
      properties: {
        label_or_id: { type: "string" },
      },
      required: ["label_or_id"],
    },
  },
  {
    name: "move_camera_to",
    description:
      "Move the user's camera to look at a specific labelled object.",
    input_schema: {
      type: "object",
      properties: {
        label_or_id: { type: "string" },
      },
      required: ["label_or_id"],
    },
  },
  {
    name: "describe_scene",
    description: "List all labelled objects in the scene.",
    input_schema: {
      type: "object",
      properties: {},
    },
  },
];

interface ToolOutcome {
  // Anthropic accepts either a plain string or an array of content blocks
  // (text + image) inside a tool_result. Image blocks are what makes the
  // multimodal flow work.
  content: string | Array<
    | { type: "text"; text: string }
    | {
        type: "image";
        source: { type: "base64"; media_type: "image/jpeg"; data: string };
      }
  >;
  framesUsed: string[];
  isError?: boolean;
}

async function execTool(
  name: string,
  rawInput: unknown,
  ctx: { sceneId: string; annotations: AnnotationLite[] },
): Promise<ToolOutcome> {
  const input = (rawInput ?? {}) as Record<string, unknown>;

  if (name === "describe_scene") {
    if (ctx.annotations.length === 0) {
      return { content: "No labelled objects in this scene yet.", framesUsed: [] };
    }
    const lines = ctx.annotations.map(
      (a) => `- ${a.label} (${a.id})`,
    );
    return { content: lines.join("\n"), framesUsed: [] };
  }

  const labelOrId = typeof input.label_or_id === "string" ? input.label_or_id : "";
  const ann = resolveAnnotation(ctx.annotations, labelOrId);
  if (!ann) {
    return {
      content: `No labelled object matched "${labelOrId}". Known labels: ${ctx.annotations
        .map((a) => a.label)
        .join(", ") || "(none)"}.`,
      framesUsed: [],
      isError: true,
    };
  }

  if (name === "locate_object") {
    return {
      content: JSON.stringify({
        annotation_id: ann.id,
        label: ann.label,
        centroid: ann.centroid,
        bbox: ann.bbox,
      }),
      framesUsed: [],
    };
  }

  if (name === "move_camera_to") {
    return {
      content: JSON.stringify({
        annotation_id: ann.id,
        label: ann.label,
        look_at: ann.centroid,
      }),
      framesUsed: [],
    };
  }

  if (name === "get_frames_for_object") {
    let frames: FrameImage[] = [];
    try {
      frames = await fetchFramesForAnnotation(ctx.sceneId, ann, FRAMES_PER_CALL);
    } catch (err) {
      return {
        content: `Could not fetch frames for ${ann.label}: ${
          err instanceof Error ? err.message : String(err)
        }`,
        framesUsed: [],
        isError: true,
      };
    }
    if (frames.length === 0) {
      return {
        content: `No frames available for ${ann.label} (${ann.id}).`,
        framesUsed: [],
        isError: true,
      };
    }
    const blocks: ToolOutcome["content"] = [
      {
        type: "text",
        text: `Frames for ${ann.label} (${ann.id}); ${frames.length} returned.`,
      },
      ...frames.map((f) => ({
        type: "image" as const,
        source: {
          type: "base64" as const,
          media_type: f.media_type,
          data: f.data_b64,
        },
      })),
    ];
    return { content: blocks, framesUsed: frames.map((f) => f.frame_id) };
  }

  return {
    content: `Unknown tool: ${name}`,
    framesUsed: [],
    isError: true,
  };
}

export const chatRoute: FastifyPluginAsync = async (app) => {
  app.post("/api/agent/chat", async (request, reply) => {
    const t0 = performance.now();
    const parsed = ChatBody.safeParse(request.body);
    if (!parsed.success) {
      return reply.code(400).send({ error: parsed.error.message });
    }
    const body: ChatBody = parsed.data;

    let annotations: AnnotationLite[] = [];
    try {
      annotations = await loadAnnotations(body.scene_id);
    } catch (err) {
      request.log.warn({ err, scene: body.scene_id }, "annotations load failed");
    }

    let client;
    try {
      client = anthropicClient();
    } catch (err) {
      request.log.error({ err }, "gateway client construction failed");
      return reply.code(500).send({ error: "gateway not configured" });
    }

    const objectsList = annotations
      .map((a) => `${a.id} — ${a.label}`)
      .join("\n");
    const system = SYSTEM_PROMPT(objectsList);

    const messages: MessageParam[] = [
      { role: "user", content: body.message },
    ];
    const framesUsed: string[] = [];
    const toolsCalled: string[] = [];

    let finalText = "";
    for (let iter = 0; iter < MAX_TOOL_ITERS; iter++) {
      let resp;
      try {
        resp = await client.messages.create({
          model: MODEL,
          max_tokens: 1024,
          system,
          tools: TOOLS,
          messages,
        });
      } catch (err) {
        request.log.error({ err }, "anthropic call failed");
        return reply.code(502).send({ error: "model call failed" });
      }

      // Record the call for the scene-page CostBadge. Failures here must not
      // affect the chat response, so the helper is intentionally synchronous
      // and exception-free.
      recordModelCall({
        scene_id: body.scene_id,
        model: MODEL,
        tokens_in: resp.usage?.input_tokens ?? 0,
        tokens_out: resp.usage?.output_tokens ?? 0,
      });

      const toolUses = resp.content.filter((b) => b.type === "tool_use");
      const textBlocks = resp.content.filter((b) => b.type === "text");

      // Stop conditions: model is done (end_turn / no tool calls) — emit text.
      if (toolUses.length === 0 || resp.stop_reason === "end_turn") {
        finalText = textBlocks
          .map((b) => (b.type === "text" ? b.text : ""))
          .join("\n")
          .trim();
        break;
      }

      // Append assistant turn (must include the tool_use blocks verbatim) and
      // a single user turn carrying every tool_result, then loop.
      messages.push({ role: "assistant", content: resp.content });

      const toolResults: MessageParam["content"] = [];
      for (const block of toolUses) {
        if (block.type !== "tool_use") continue;
        toolsCalled.push(block.name);
        const outcome = await execTool(block.name, block.input, {
          sceneId: body.scene_id,
          annotations,
        });
        for (const f of outcome.framesUsed) framesUsed.push(f);
        toolResults.push({
          type: "tool_result",
          tool_use_id: block.id,
          content: outcome.content as never,
          is_error: outcome.isError,
        });
      }
      messages.push({ role: "user", content: toolResults });

      // If the model also produced text alongside tool_use, prefer the final
      // post-tool text — but stash this as a fallback for cap-out cases.
      if (textBlocks.length > 0 && !finalText) {
        finalText = textBlocks
          .map((b) => (b.type === "text" ? b.text : ""))
          .join("\n")
          .trim();
      }
    }

    if (!finalText) {
      finalText = "(no answer produced — tool loop hit the iteration cap)";
    }

    const latencyMs = Math.round(performance.now() - t0);
    return {
      text: finalText,
      frames_used: framesUsed,
      tools_called: toolsCalled,
      latency_ms: latencyMs,
      model: MODEL,
    };
  });
};
