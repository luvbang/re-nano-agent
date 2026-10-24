import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import type { Session } from "../api/types";
import { Badge, Card, Empty, ErrorBox, PageTitle, Spinner } from "../components/ui";
import { useKeys } from "../hooks/keys";

export function Sessions() {
  const { projectKey } = useKeys();
  const query = useQuery({
    queryKey: ["sessions"],
    queryFn: () => api<Session[]>("/v1/sessions?limit=50", projectKey),
    enabled: Boolean(projectKey),
  });

  if (!projectKey) {
    return <Empty>需要项目 key（Keys 页创建后可用）。</Empty>;
  }
  if (query.isLoading) return <Spinner />;
  if (query.error) return <ErrorBox>{String(query.error)}</ErrorBox>;

  return (
    <div>
      <PageTitle>Sessions</PageTitle>
      {query.data && query.data.length === 0 ? (
        <Empty>还没有会话；去 Playground 发一条消息。</Empty>
      ) : (
        <div className="space-y-2">
          {query.data?.map((session) => (
            <Card key={session.id} className="flex items-center gap-3 py-3">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm">{session.title ?? session.id}</p>
                <p className="text-xs text-dim">
                  {session.id} · 创建于 {session.created_at.slice(0, 19).replace("T", " ")}
                </p>
              </div>
              <Badge tone="muted">{session.external_user_id ?? "—"}</Badge>
              <Link
                to={`/playground?session=${session.id}`}
                className="rounded border border-line px-3 py-1.5 text-xs text-dim hover:text-ink"
              >
                查看消息
              </Link>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
