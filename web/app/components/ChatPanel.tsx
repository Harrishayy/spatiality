"use client";

import { useEffect, useRef, useState } from "react";
import { frameUrl } from "@/lib/api";
import type { ChatMessage } from "@/lib/types";

interface Props {
  sceneId: string;
  messages: ChatMessage[];
  onSend: (text: string) => void;
  disabled?: boolean;
}

export function ChatPanel({ sceneId, messages, onSend, disabled }: Props) {
  const [draft, setDraft] = useState("");
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages]);

  const submit = () => {
    const t = draft.trim();
    if (!t || disabled) return;
    onSend(t);
    setDraft("");
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div
        ref={scrollRef}
        className="scroll-thin flex-1 space-y-3 overflow-y-auto pb-3 pr-1"
      >
        {messages.map((m) => (
          <Message key={m.id} m={m} sceneId={sceneId} />
        ))}
      </div>
      <div className="flex gap-2 border-t border-ink-800 pt-3">
        <input
          type="text"
          inputMode="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          placeholder={disabled ? "Loading…" : "Ask about the scene…"}
          disabled={disabled}
          className={[
            "flex-1 rounded-lg border border-ink-700 bg-ink-900 px-3 py-2",
            "text-sm placeholder:text-ink-500 focus:border-accent-400",
            "focus:outline-none focus:ring-1 focus:ring-accent-400",
            "disabled:opacity-60",
          ].join(" ")}
        />
        <button
          onClick={submit}
          disabled={disabled || !draft.trim()}
          className={[
            "rounded-lg bg-accent-500 px-3 py-2 text-sm font-medium text-white",
            "transition active:scale-95 hover:bg-accent-400",
            "disabled:cursor-not-allowed disabled:opacity-50",
          ].join(" ")}
        >
          Send
        </button>
      </div>
    </div>
  );
}

function Message({ m, sceneId }: { m: ChatMessage; sceneId: string }) {
  const isUser = m.role === "user";
  const frames = m.frames_used ?? [];
  return (
    <div
      className={[
        "flex flex-col animate-slide-in",
        isUser ? "items-end" : "items-start",
      ].join(" ")}
    >
      <div
        className={[
          "max-w-[85%] rounded-2xl px-3 py-2 text-sm leading-snug",
          isUser
            ? "bg-accent-500/90 text-white"
            : "bg-ink-800 text-ink-100",
          m.pending ? "italic text-ink-400" : "",
        ].join(" ")}
      >
        {m.text}
      </div>
      {!isUser && frames.length > 0 && (
        <div className="mt-1 flex max-w-[85%] flex-col gap-1">
          <div className="text-[10px] uppercase tracking-wider text-ink-500">
            Looked at {frames.length} frame{frames.length === 1 ? "" : "s"}
          </div>
          <div className="flex gap-1 overflow-x-auto">
            {frames.map((name) => (
              <img
                key={name}
                src={frameUrl(sceneId, name)}
                alt={name}
                className="h-12 w-16 flex-none rounded border border-ink-700 object-cover"
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}