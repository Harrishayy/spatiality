"use client";

import { useEffect, useRef, useState } from "react";
import type { ChatMessage } from "@/lib/types";

interface Props {
  messages: ChatMessage[];
  onSend: (text: string) => void;
  disabled?: boolean;
}

export function ChatPanel({ messages, onSend, disabled }: Props) {
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
          <Message key={m.id} m={m} />
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

function Message({ m }: { m: ChatMessage }) {
  const isUser = m.role === "user";
  return (
    <div
      className={[
        "flex animate-slide-in",
        isUser ? "justify-end" : "justify-start",
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
    </div>
  );
}