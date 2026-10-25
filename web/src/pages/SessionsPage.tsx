/** Sessions 列表：分页加载，点击“续聊”携带会话跳转 Playground。 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router";
import { useAdminKey } from "../hooks/useAdminKey";
import { EmptyState, ErrorState, LoadingState } from "../components/StateViews";
import { Badge, Button, Card } from "../components/ui";
import { copy } from "../lib/copy";
import { formatDateTime } from "../lib/format";

export function SessionsPage() {
  const { client, mode } = useAdminKey();
  const navigate = useNavigate();
  const [limit, setLimit] = useState(20);

  const sessionsQuery = useQuery({
    queryKey: ["sessions", mode, limit],
    queryFn: () => client.listSessions(limit),
  });

  if (sessionsQuery.isPending) return <LoadingState />;
  if (sessionsQuery.isError)
    return (
      <ErrorState
        message={sessionsQuery.error.message}
        onRetry={() => void sessionsQuery.refetch()}
      />
    );

  const sessions = sessionsQuery.data;
  return (
    <div className="mx-auto max-w-3xl space-y-3 p-4">
      <h1 className="text-lg font-semibold">{copy.sessions.title}</h1>
      {sessions.length === 0 ? (
        <EmptyState>{copy.sessions.empty}</EmptyState>
      ) : (
        sessions.map((s) => (
          <Card key={s.id} className="flex items-center gap-3 p-3">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="truncate text-sm font-medium text-zinc-100">
                  {s.title ?? s.id}
                </span>
                {s.external_user_id ? <Badge>{s.external_user_id}</Badge> : null}
              </div>
              <div className="mt-0.5 font-mono text-xs text-zinc-500">
                {s.id} · 更新于 {formatDateTime(s.updated_at)}
              </div>
            </div>
            <Button
              variant="ghost"
              onClick={() => {
                navigate(`/playground?session=${s.id}`);
              }}
            >
              {copy.sessions.resume}
            </Button>
          </Card>
        ))
      )}
      {sessions.length >= limit ? (
        <div className="flex justify-center pt-2">
          <Button variant="ghost" onClick={() => setLimit((n) => n + 20)}>
            {copy.sessions.loadMore}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
