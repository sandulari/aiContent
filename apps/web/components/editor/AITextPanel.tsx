"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Loading } from "@/components/shared/loading";

interface AITextPanelProps {
  reelId: string;
  userPageId?: string;
  onSelectHeadline: (text: string) => void;
  onSelectSubtitle: (text: string) => void;
  onCaptionGenerated?: (caption: string) => void;
}

interface ChatMsg {
  role: "user" | "assistant";
  content: string;
  suggestions?: {
    headlines: string[];
    subtitles: string[];
    caption: string;
  };
}

// ── Chat interface for the AI text assistant ──────────────────────────
// Works like ChatGPT / Claude: the user sends a message, we call the
// backend /api/ai/chat endpoint with the full conversation history and
// page + reel context, the backend returns Claude's reply + structured
// headline/subtitle/caption suggestions. Suggestions render inline with
// each assistant message as clickable chips that apply to the canvas.

export function AITextPanel({
  reelId,
  userPageId,
  onSelectHeadline,
  onSelectSubtitle,
  onCaptionGenerated,
}: AITextPanelProps) {
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const bootstrapped = useRef(false);
  // Mirror of `messages` so sendMessage doesn't read a stale snapshot
  // from its closure on rapid sends. Without this, two clicks fired in
  // the same tick would both compute `[...messages, userMsg]` from the
  // same prior list, dropping the first user turn from history.
  const messagesRef = useRef<ChatMsg[]>([]);
  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  // Autoscroll to the newest message
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages, loading]);

  const sendMessage = useCallback(
    async (content: string, isInitial = false) => {
      if (!userPageId) {
        setError("Connect your own Instagram page in Settings first.");
        return;
      }
      const trimmed = content.trim();
      if (!trimmed && !isInitial) return;

      const userMsg: ChatMsg = { role: "user", content: trimmed };
      const kickoffMsg: ChatMsg = {
        role: "user",
        content:
          "Analyze this reel and give me 3 headline options, 3 subtitles, and a caption tailored to my page's audience. Explain briefly what direction you picked.",
      };
      // Read the live messages from the ref (synced via effect) instead
      // of the closure; this prevents two rapid sends from dropping the
      // first user turn. Update the ref optimistically so a second send
      // arriving before React commits the first still sees the appended
      // turn.
      const nextMessages: ChatMsg[] = isInitial
        ? [kickoffMsg]
        : [...messagesRef.current, userMsg];
      messagesRef.current = nextMessages;
      setMessages(nextMessages);
      setInput("");
      setLoading(true);
      setError(null);

      try {
        const res = await api.ai.chat({
          viral_reel_id: reelId,
          user_page_id: userPageId,
          messages: nextMessages.map((m) => ({ role: m.role, content: m.content })),
        });
        const msgLower = (res.assistant_message || "").toLowerCase();
        const isBridgeDown =
          msgLower.includes("bridge unreachable") ||
          msgLower.includes("bridge isn't running") ||
          msgLower.includes("claude cli failed");

        if (isBridgeDown) {
          // Don't push a confusing assistant bubble AND an error banner.
          // Rollback the optimistic user message so the input box keeps
          // their text, and surface the error prominently. Also pop
          // from the ref so a retry click between this rollback and the
          // next render doesn't re-send the bridge-down turn as history.
          messagesRef.current = messagesRef.current.slice(0, -1);
          setMessages((prev) => prev.slice(0, -1));
          setInput(userMsg.content);
          setError(
            "Claude bridge isn't running on your host. Start it with `bash infra/start_claude_bridge.sh` in a terminal, or install the persistent LaunchAgent with `bash infra/install_bridge_launchd.sh`."
          );
        } else {
          const assistantMsg: ChatMsg = {
            role: "assistant",
            content: res.assistant_message || "(no text returned)",
            suggestions: res.suggestions,
          };
          messagesRef.current = [...messagesRef.current, assistantMsg];
          setMessages((prev) => [...prev, assistantMsg]);
        }
      } catch (e: any) {
        setError(e?.message || "AI chat failed. Try again.");
      } finally {
        setLoading(false);
      }
    },
    [reelId, userPageId]
  );

  const retryLastMessage = useCallback(() => {
    // Retry by re-sending the last user message. If the last message
    // was the auto-kickoff, re-trigger that instead.
    const lastUser = [...messagesRef.current].reverse().find((m) => m.role === "user");
    if (!lastUser) {
      messagesRef.current = [];
      setMessages([]);
      bootstrapped.current = false;
      setTimeout(() => sendMessage("", true), 10);
      return;
    }
    // Drop the failed assistant turn (if any) and retry the user turn.
    const cut = [...messagesRef.current];
    while (cut.length && cut[cut.length - 1].role === "assistant") cut.pop();
    // Also drop the user message we're about to re-send — sendMessage
    // will re-append it.
    if (cut.length && cut[cut.length - 1].role === "user") cut.pop();
    messagesRef.current = cut;
    setMessages(cut);
    setTimeout(() => sendMessage(lastUser.content, false), 50);
  }, [sendMessage]);

  // Auto-kick an initial analysis when the panel opens for the first time
  useEffect(() => {
    if (bootstrapped.current) return;
    if (!userPageId) return;
    bootstrapped.current = true;
    sendMessage("", true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userPageId]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  };

  const resetChat = () => {
    messagesRef.current = [];
    setMessages([]);
    bootstrapped.current = false;
    setError(null);
    setTimeout(() => sendMessage("", true), 10);
  };

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-[#30363d] flex-shrink-0">
        <span className="text-xs font-medium text-[#e6edf3]">AI Assistant</span>
        {messages.length > 0 && (
          <button
            onClick={resetChat}
            className="text-[10px] text-[#58a6ff] hover:underline"
            title="Start a fresh conversation"
          >
            Reset
          </button>
        )}
      </div>

      {/* No-own-page warning */}
      {!userPageId && (
        <div className="m-3 p-2 text-[11px] text-[#f0a500] bg-[#f0a500]/10 border border-[#f0a500]/30 rounded">
          Connect one of your own Instagram pages in Settings so the AI knows your voice.
        </div>
      )}

      {/* Message list */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-3 py-3 space-y-3 min-h-0">
        {messages.length === 0 && !loading && (
          <p className="text-[11px] text-[#484f58] text-center py-6">
            Ask for headlines, subtitles, or a caption. Refine with follow-ups.
          </p>
        )}

        {messages.map((m, i) => (
          <ChatBubble
            key={i}
            msg={m}
            onApplyHeadline={onSelectHeadline}
            onApplySubtitle={onSelectSubtitle}
            onApplyCaption={onCaptionGenerated}
          />
        ))}

        {loading && (
          <div className="flex items-center gap-2 px-2 py-2 text-[11px] text-[#8b949e]">
            <Loading size="sm" />
            <span>Thinking…</span>
          </div>
        )}

        {error && (
          <div className="text-[11px] text-[#f85149] bg-[#f85149]/10 border border-[#f85149]/30 rounded px-2 py-2 space-y-2">
            <p className="leading-snug whitespace-pre-wrap">{error}</p>
            <button
              onClick={retryLastMessage}
              className="text-[10px] px-2 py-1 rounded border border-[#f85149]/40 text-[#f85149] hover:bg-[#f85149]/10"
            >
              Retry
            </button>
          </div>
        )}
      </div>

      {/* Input */}
      <div className="border-t border-[#30363d] p-2 flex-shrink-0">
        <textarea
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder='Ask for changes… e.g. "more urgent" or "reference AI more"'
          rows={2}
          disabled={loading || !userPageId}
          className="w-full bg-[#0d1117] border border-[#30363d] rounded px-2 py-1.5 text-xs text-[#c9d1d9] focus:border-[#58a6ff] focus:outline-none resize-none disabled:opacity-60"
        />
        <div className="flex items-center justify-between mt-1.5">
          <span className="text-[9px] text-[#484f58]">Enter to send · Shift+Enter for newline</span>
          <Button
            size="sm"
            onClick={() => sendMessage(input)}
            loading={loading}
            disabled={loading || !userPageId || !input.trim()}
          >
            Send
          </Button>
        </div>
      </div>
    </div>
  );
}

// ── A single chat bubble ─────────────────────────────────────────────

function ChatBubble({
  msg,
  onApplyHeadline,
  onApplySubtitle,
  onApplyCaption,
}: {
  msg: ChatMsg;
  onApplyHeadline: (t: string) => void;
  onApplySubtitle: (t: string) => void;
  onApplyCaption?: (t: string) => void;
}) {
  const isUser = msg.role === "user";
  const [copied, setCopied] = useState(false);

  const handleCopyCaption = async (text: string) => {
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // Fallback for non-HTTPS or older browsers
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
      } catch {}
      document.body.removeChild(ta);
    }
    // Also push into the export's saved caption so it ships with the render
    if (onApplyCaption) onApplyCaption(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[92%] space-y-2 ${
          isUser
            ? "bg-[#58a6ff]/15 border border-[#58a6ff]/30 text-[#c9d1d9] rounded-lg rounded-br-sm px-3 py-2"
            : "bg-[#161b22] border border-[#30363d] text-[#e6edf3] rounded-lg rounded-bl-sm px-3 py-2"
        }`}
      >
        {msg.content && (
          <p className="text-[12px] leading-snug whitespace-pre-wrap">{msg.content}</p>
        )}

        {!isUser && msg.suggestions && (
          <div className="space-y-2 pt-1">
            {msg.suggestions.headlines?.length > 0 && (
              <div>
                <p className="text-[9px] text-[#484f58] uppercase tracking-wider mb-1">
                  Headlines · click to apply
                </p>
                <div className="space-y-1">
                  {msg.suggestions.headlines.map((h, i) => (
                    <button
                      key={i}
                      onClick={() => onApplyHeadline(h)}
                      className="block w-full text-left px-2 py-1.5 text-[11px] text-[#e6edf3] bg-[#0d1117] rounded border border-[#21262d] hover:border-[#58a6ff] hover:bg-[#58a6ff]/5 leading-snug"
                    >
                      {h}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {msg.suggestions.subtitles?.length > 0 && (
              <div>
                <p className="text-[9px] text-[#484f58] uppercase tracking-wider mb-1">
                  Subtitles · click to apply
                </p>
                <div className="space-y-1">
                  {msg.suggestions.subtitles.map((s, i) => (
                    <button
                      key={i}
                      onClick={() => onApplySubtitle(s)}
                      className="block w-full text-left px-2 py-1.5 text-[11px] text-[#7d8590] bg-[#0d1117] rounded border border-[#21262d] hover:border-[#58a6ff] hover:bg-[#58a6ff]/5 leading-snug"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {msg.suggestions.caption && (
              <div>
                <div className="flex items-center justify-between mb-1">
                  <p className="text-[9px] text-[#484f58] uppercase tracking-wider">Caption</p>
                  <button
                    onClick={() => handleCopyCaption(msg.suggestions!.caption)}
                    className={`text-[10px] px-1.5 py-0.5 rounded transition-colors ${
                      copied
                        ? "text-[#3fb950] bg-[#3fb950]/10"
                        : "text-[#58a6ff] hover:bg-[#58a6ff]/10"
                    }`}
                    title="Copy the caption to your clipboard and save it to this export"
                  >
                    {copied ? "Copied ✓" : "Copy caption"}
                  </button>
                </div>
                <p className="text-[10px] text-[#7d8590] bg-[#0d1117] rounded p-2 border border-[#21262d] whitespace-pre-wrap leading-relaxed">
                  {msg.suggestions.caption}
                </p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
