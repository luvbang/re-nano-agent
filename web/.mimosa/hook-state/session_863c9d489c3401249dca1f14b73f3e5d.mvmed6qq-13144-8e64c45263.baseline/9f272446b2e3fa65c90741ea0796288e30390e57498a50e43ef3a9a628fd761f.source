/**
 * API Keys 管理：创建（完整 key 只展示一次）/ 撤销（立即生效）。
 * 契约 §5.1：后端只存 hash，secret 只在创建响应出现一次。
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAdminKey } from "../hooks/useAdminKey";
import { EmptyState, ErrorState, LoadingState } from "../components/StateViews";
import { Badge, Button, Card, Input } from "../components/ui";
import { copy } from "../lib/copy";
import { formatDateTime } from "../lib/format";

export function KeysPage() {
  const { client, mode } = useAdminKey();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [created, setCreated] = useState<{ secret: string; name: string | null } | null>(null);
  const [copied, setCopied] = useState(false);

  const keysQuery = useQuery({
    queryKey: ["keys", mode],
    queryFn: () => client.listKeys(),
  });

  const createMutation = useMutation({
    mutationFn: () => client.createKey(name.trim() || null),
    onSuccess: async (result) => {
      setCreated({ secret: result.secret, name: result.key.name });
      setName("");
      await queryClient.invalidateQueries({ queryKey: ["keys", mode] });
    },
  });

  const revokeMutation = useMutation({
    mutationFn: (keyId: string) => client.revokeKey(keyId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["keys", mode] });
    },
  });

  const copySecret = async () => {
    if (!created) return;
    try {
      await navigator.clipboard.writeText(created.secret);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // 剪贴板不可用时用户可手动选择复制
    }
  };

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4">
      <h1 className="text-lg font-semibold">{copy.keys.title}</h1>

      <Card className="flex flex-wrap items-center gap-2 p-3">
        <Input
          className="max-w-xs flex-1"
          placeholder={copy.keys.namePlaceholder}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <Button onClick={() => createMutation.mutate()} disabled={createMutation.isPending}>
          {copy.keys.create}
        </Button>
      </Card>

      {created ? (
        <Card className="border-accent p-4">
          <div className="text-sm font-medium text-emerald-300">{copy.keys.created}</div>
          <p className="mt-1 text-xs text-amber-300">{copy.keys.secretOnce}</p>
          <div className="mt-2 flex items-center gap-2">
            <code className="flex-1 overflow-x-auto rounded bg-surface px-3 py-2 font-mono text-sm text-emerald-200">
              {created.secret}
            </code>
            <Button variant="ghost" onClick={() => void copySecret()}>
              {copied ? copy.keys.copied : copy.keys.copy}
            </Button>
          </div>
          <div className="mt-2 flex justify-end">
            <Button variant="ghost" onClick={() => setCreated(null)}>
              {copy.keys.close}
            </Button>
          </div>
        </Card>
      ) : null}

      {keysQuery.isPending ? (
        <LoadingState />
      ) : keysQuery.isError ? (
        <ErrorState message={keysQuery.error.message} onRetry={() => void keysQuery.refetch()} />
      ) : keysQuery.data.length === 0 ? (
        <EmptyState>{copy.keys.empty}</EmptyState>
      ) : (
        keysQuery.data.map((k) => (
          <Card key={k.id} className="flex items-center gap-3 p-3">
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium text-zinc-100">{k.name ?? "（未命名）"}</span>
                {k.revoked_at ? (
                  <Badge tone="error">{copy.keys.revoked}</Badge>
                ) : (
                  <Badge tone="success">{k.scopes}</Badge>
                )}
                <Badge>{k.rate_limit_per_min}/min</Badge>
              </div>
              <div className="mt-0.5 font-mono text-xs text-zinc-500">
                {k.key_prefix}… · 创建于 {formatDateTime(k.created_at)}
              </div>
            </div>
            {!k.revoked_at ? (
              <Button
                variant="danger"
                onClick={() => {
                  if (window.confirm(copy.keys.confirmRevoke)) {
                    revokeMutation.mutate(k.id);
                  }
                }}
              >
                {copy.keys.revoke}
              </Button>
            ) : null}
          </Card>
        ))
      )}
    </div>
  );
}
