import { useEffect, useRef, useState } from "react";

import { api, ApiError } from "../api/client";
import { streamRun } from "../api/sse";
import type { MessageItem, Session } from "../api/types";
import { ChatView } from "../components/ChatView";
import { Button, Card, ErrorBox, Input } from "../components/ui";
import { useKeys } from "../hooks/keys";
import { applyEvent, fromHistory, initialState, type RunState } from "../projection/runProjection";

export function Playground() {
  const { projectKey } = useKeys();
  const [session, setSession] = useState<Session | null>(null);
  const [state, setState] = useState<RunState>(initialState);
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [state.items]);

  if (!projectKey) {
    return (
      <Card>
        <p className="text-sm text-dim">
          Playground 需要项目 key：到 <span className="text-ink">Keys</span> 页创建并点「用于 Playground」。
        </p>
      </Card>
    );
  }

  async function loadHistory(sessionId: string) {
    const page = await api<{ items: MessageItem[] }>(
      `/v1/sessions/${sessionId}/messages?limit=100`,
      projectKey,
    );
    setState({ ...initialState, items: fromHistory(page.items) });
  }

  async function newSession() {
    const created = await api<Session>("/v1/sessions", projectKey, {
      method: "POST",
      body: { title: `console-${new Date().toISOString().slice(0, 16)}` },
    });
    setSession(created);
    setState(initialState);
  }

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    setBusy(true);
    setError(null);
    setInput("");
    try {
      let current = session;
      if (!current) {
        current = await api<Session>("/v1/sessions", projectKey, {
          method: "POST",
          body: { title: "playground" },
        });
        setSession(current);
      }
      const created = await api<{ run_id: string }>(
        `/v1/sessions/${current.id}/runs`,
        projectKey,
        { method: "POST", body: { input: text } },
      );
      setState((prev) => applyEvent({ ...prev, error: null }, { seq: 0, type: "run.started", data: {} }));
      setState((prev) => ({
        ...prev,
        items: [...prev.items, { kind: "user", text }],
        streaming: true,
      }));
      for await (const event of streamRun(created.run_id, projectKey)) {
        setState((prev) => applyEvent(prev, event));
      }
    } catch (cause) {
      const message =
        cause instanceof ApiError ? `${cause.code}：${cause.message}` : String(cause);
      setError(message);
      setState((prev) => ({ ...prev, streaming: false }));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-xs text-dim">
        <span>{session ? `会话 ${session.id.slice(0, 14)}…` : "新会话（发送时自动创建）"}</span>
        <Button variant="ghost" onClick={() => void newSession()}>
          开新会话
        </Button>
        {session && (
          <Button variant="ghost" onClick={() => void loadHistory(session.id)}>
            重新载入历史
          </Button>
        )}
      </div>
      <Card className="min-h-[50vh]">
        {state.items.length === 0 ? (
          <p className="py-16 text-center text-sm text-dim">
            输入消息开始对话；流式回答与工具调用会实时出现在这里。
          </p>
        ) : (
          <ChatView items={state.items} streaming={state.streaming} />
        )}
        <div ref={bottomRef} />
      </Card>
      {error && <ErrorBox>{error}</ErrorBox>}
      {state.usage && (
        <p className="text-right text-xs text-dim">
          上轮用量：in={state.usage.input} / out={state.usage.output}
        </p>
      )}
      <form
        className="flex gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          void send();
        }}
      >
        <Input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="输入消息，回车发送"
          disabled={busy}
        />
        <Button type="submit" disabled={busy || !input.trim()}>
          {busy ? "流式中…" : "发送"}
        </Button>
      </form>
    </div>
  );
}
