/** Sessions 列表：完整列表屏——标题行报总数，行落在 1px 行线上，点「续聊」进 Playground。 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router";
import { useAdminKey } from "../hooks/useAdminKey";
import { EmptyState, ErrorState, LoadingState } from "../components/StateViews";
import { Badge, Button } from "../components/ui";
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
    <div className="mx-auto max-w-[1120px] px-5 pb-12 pt-7 sm:px-8">
      {/* 标题行：名词 h1 + 总数 */}
      <div className="flex items-baseline gap-3">
        <h1 className="text-2xl font-semibold text-white">{copy.sessions.title}</h1>
        <span className="num text-sm text-mut">{copy.sessions.total(sessions.length)}</span>
      </div>

      <div className="mt-5">
        {sessions.length === 0 ? (
          <EmptyState>{copy.sessions.empty}</EmptyState>
        ) : (
          <ul>
            {sessions.map((s) => (
              <li key={s.id} className="border-t border-rule py-3 first:border-t-0">
                {/* 手机：身份占整行，更新时间与动作落到第二行；桌面一行 */}
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
                  <div className="min-w-0 flex-1 basis-full sm:basis-0">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-sm font-medium text-white">
                        {s.title ?? s.id}
                      </span>
                      {s.external_user_id ? <Badge>{s.external_user_id}</Badge> : null}
                    </div>
                    <div className="num mt-0.5 truncate text-xs text-mut">{s.id}</div>
                  </div>
                  <span className="num text-xs text-mut">
                    {copy.sessions.updated(formatDateTime(s.updated_at))}
                  </span>
                  <Button
                    variant="ghost"
                    className="ml-auto !h-7 !px-3 !text-xs sm:ml-0"
                    onClick={() => {
                      navigate(`/playground?session=${s.id}`);
                    }}
                  >
                    {copy.sessions.resume}
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      {sessions.length >= limit ? (
        <div className="mt-4">
          <Button variant="ghost" onClick={() => setLimit((n) => n + 20)}>
            {copy.sessions.loadMore}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
