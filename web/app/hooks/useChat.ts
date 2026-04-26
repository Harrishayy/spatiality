import { useCallback, useRef, useState } from "react";
import { LOCAL_DEMO_SCENE_ID, postChat } from "@/lib/api";
import type { ChatMessage, Vec3 } from "@/lib/types";
import { useUI } from "@/store/ui";

let nextId = 0;
const newId = () => `msg_${++nextId}_${Date.now().toString(36)}`;

// Canned replies for the bundled local demo so chat is interactive without
// the agent service running. Cycled per turn.
const DEMO_REPLIES = [
  "This is the bundled demo room — three objects, six colored walls, no real VLM behind me. Spin the view, click an object marker, or open Pipeline / Objects from the rail.",
  "I can't actually call the model on the local demo, but in a real scene I'd answer here with the frames I looked at cited inline.",
  "Try clicking the side chair, low table, or table lamp on the right. Selecting an object auto-opens the Evidence drawer.",
];

export function useChat(sceneId: string) {
  const camera = useUI((s) => s.camera);
  const demoTurn = useRef(0);
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: newId(),
      role: "agent",
      text:
        "Loaded. Ask anything about the scene, or tap **Where am I?** to ground a question to your view.",
    },
  ]);

  const send = useCallback(
    async (text: string) => {
      const userMsg: ChatMessage = { id: newId(), role: "user", text };
      const pendingId = newId();
      setMessages((m) => [
        ...m,
        userMsg,
        { id: pendingId, role: "agent", text: "…", pending: true },
      ]);
      try {
        if (sceneId === LOCAL_DEMO_SCENE_ID) {
          const reply = DEMO_REPLIES[demoTurn.current % DEMO_REPLIES.length];
          demoTurn.current += 1;
          await new Promise((r) => setTimeout(r, 450));
          setMessages((m) =>
            m.map((msg) =>
              msg.id === pendingId
                ? { ...msg, text: reply, pending: false }
                : msg,
            ),
          );
          return;
        }
        const resp = await postChat({
          scene_id: sceneId,
          message: text,
          camera_pos: camera.position as Vec3,
        });
        setMessages((m) =>
          m.map((msg) =>
            msg.id === pendingId
              ? {
                  ...msg,
                  text: resp.text,
                  pending: false,
                  frames_used: resp.frames_used ?? [],
                  tools_called: resp.tools_called ?? [],
                }
              : msg,
          ),
        );
      } catch (e) {
        const err = e instanceof Error ? e.message : String(e);
        setMessages((m) =>
          m.map((msg) =>
            msg.id === pendingId
              ? { ...msg, text: `(error: ${err})`, pending: false }
              : msg,
          ),
        );
      }
    },
    [sceneId, camera.position],
  );

  const append = useCallback((msg: Omit<ChatMessage, "id">) => {
    setMessages((m) => [...m, { ...msg, id: newId() }]);
  }, []);

  return { messages, send, append };
}
