"use client";

import { useEffect, useRef, useState } from "react";
import { Send, X } from "lucide-react";
import type { RoomMessage } from "@/lib/interview-room/api";

interface Props {
  messages: RoomMessage[];
  myUserId: string;
  onSend: (content: string) => void;
  onClose: () => void;
}

export function ChatSidebar({ messages, myUserId, onSend, onClose }: Props) {
  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  function handleSend() {
    const text = input.trim();
    if (!text) return;
    onSend(text);
    setInput("");
  }

  function formatTime(iso: string) {
    return new Date(iso).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
  }

  return (
    <aside className="w-72 flex flex-col bg-gray-950 border-l border-gray-800">
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
        <span className="text-sm font-semibold text-white">Chat</span>
        <button onClick={onClose} className="text-gray-400 hover:text-white">
          <X size={16} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-3">
        {messages.length === 0 && (
          <p className="text-center text-xs text-gray-600 py-8">Noch keine Nachrichten.</p>
        )}
        {messages.map((msg) => {
          const isMine = msg.sender_id === myUserId;
          return (
            <div key={msg.id} className={`flex flex-col ${isMine ? "items-end" : "items-start"}`}>
              <span className="text-xs text-gray-500 mb-0.5">
                {isMine ? "Du" : msg.sender_name} · {formatTime(msg.created_at)}
              </span>
              <div
                className={`max-w-[90%] rounded-2xl px-3 py-2 text-sm break-words ${
                  isMine
                    ? "bg-blue-600 text-white rounded-br-sm"
                    : "bg-gray-800 text-gray-100 rounded-bl-sm"
                }`}
              >
                {msg.content}
              </div>
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>

      <div className="px-3 py-3 border-t border-gray-800 flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
          placeholder="Nachricht…"
          className="flex-1 rounded-lg bg-gray-800 px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        />
        <button
          onClick={handleSend}
          disabled={!input.trim()}
          className="rounded-lg bg-blue-600 p-2 text-white hover:bg-blue-500 disabled:opacity-40 transition-colors"
        >
          <Send size={16} />
        </button>
      </div>
    </aside>
  );
}
