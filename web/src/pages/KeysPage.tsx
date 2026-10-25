/**
 * API Keys 管理：项目选择/创建 → 创建 key（明文只展示一次）→ 一键绑定 Playground → 撤销。
 * main 后端按 project 隔离（跨 project 一律 404），所以创建 key 前必须先选项目。
 */

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAdminKey } from "../hooks/useAdminKey";
import { EmptyState, ErrorState, LoadingState } from "../components/StateViews";
import { Badge, Button, Card, Input } from "../components/ui";
import { copy } from "../lib/copy";
import { formatDateTime } from "../lib/format";

export function KeysPage() {
  const { client, mode, playgroundKey, setPlaygroundKey } = useAdminKey();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [newProject, setNewProject] = useState("");
  const [projectId, setProjectId] = useState<string>("");
  const [created, setCreated] = useState<{ secret: string; name: string | null } | null>(null);
  const [copied, setCopied] = useState(false);
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [projectError, setProjectError] = useState("");

  const projectsQuery = useQuery({
    queryKey: ["projects", mode],
    queryFn: () => client.listProjects(),
  });

  // 列表到达后回填默认选中项（创建 key 依赖 project_id）
  useEffect(() => {
    const data = projectsQuery.data;
    if (data && data.length > 0) setProjectId((prev) => prev || data[0]!.id);
  }, [projectsQuery.data]);

  const keysQuery = useQuery({
    queryKey: ["keys", mode],
    queryFn: () => client.listKeys(),
  });

  const createProjectMutation = useMutation({
    mutationFn: (projectName: string) => client.createProject(projectName),
    onSuccess: (project) => {
      setNewProject("");
      setProjectId(project.id);
      void queryClient.invalidateQueries({ queryKey: ["projects", mode] });
    },
  });

  const createMutation = useMutation({
    mutationFn: () => client.createKey(projectId, name.trim() || null),
    onSuccess: async (result) => {
      setCreated({ secret: result.key, name: result.detail.name });
      setName("");
      await queryClient.invalidateQueries({ queryKey: ["keys", mode] });
    },
  });

  const revokeMutation = useMutation({
    mutationFn: (keyId: string) => client.revokeKey(keyId),
    onSuccess: async () => {
      setConfirmingId(null);
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

  const projectName = (id: string) =>
    projectsQuery.data?.find((p) => p.id === id)?.name ?? id.slice(0, 8);

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4">
      <h1 className="text-lg font-semibold">{copy.keys.title}</h1>

      <Card className="space-y-3 p-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-zinc-400">{copy.keys.projectLabel}</span>
          <select
            className="rounded-md border border-surface-border bg-surface px-2 py-1.5 text-sm text-zinc-200"
            value={projectId}
            onChange={(e) => {
              setProjectId(e.target.value);
              setProjectError("");
            }}
          >
            <option value="">{copy.keys.projectPlaceholder}</option>
            {(projectsQuery.data ?? []).map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          <Input
            className="max-w-[12rem]"
            placeholder={copy.keys.newProjectPlaceholder}
            value={newProject}
            onChange={(e) => setNewProject(e.target.value)}
          />
          <Button
            variant="ghost"
            disabled={!newProject.trim() || createProjectMutation.isPending}
            onClick={() => createProjectMutation.mutate(newProject.trim())}
          >
            {copy.keys.createProject}
          </Button>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Input
            className="max-w-xs flex-1"
            placeholder={copy.keys.namePlaceholder}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <Button
            onClick={() => {
              if (!projectId) {
                setProjectError(copy.keys.needProject);
                return;
              }
              createMutation.mutate();
            }}
            disabled={createMutation.isPending || projectsQuery.isPending}
          >
            {copy.keys.create}
          </Button>
          {projectError ? <span className="text-xs text-red-400">{projectError}</span> : null}
          {createMutation.isError ? (
            <span className="text-xs text-red-400">{createMutation.error.message}</span>
          ) : null}
          {createProjectMutation.isError ? (
            <span className="text-xs text-red-400">{createProjectMutation.error.message}</span>
          ) : null}
        </div>
      </Card>

      {created ? (
        <Card className="border-accent p-4">
          <div className="text-sm font-medium text-emerald-300">{copy.keys.created}</div>
          <p className="mt-1 text-xs text-amber-300">{copy.keys.secretOnce}</p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <code className="flex-1 overflow-x-auto rounded bg-surface px-3 py-2 font-mono text-sm text-emerald-200">
              {created.secret}
            </code>
            <Button variant="ghost" onClick={() => void copySecret()}>
              {copied ? copy.keys.copied : copy.keys.copy}
            </Button>
            <Button
              onClick={() => {
                setPlaygroundKey(created.secret);
                setCreated(null);
              }}
            >
              {copy.keys.bindToPlayground}
            </Button>
            <Button variant="ghost" onClick={() => setCreated(null)}>
              {copy.keys.close}
            </Button>
          </div>
        </Card>
      ) : null}

      {playgroundKey ? (
        <div className="flex items-center gap-2 text-xs text-amber-300">
          <Badge tone="warn">{copy.keys.bound}</Badge>
          <code className="font-mono">{playgroundKey.slice(0, 12)}…</code>
          <button
            type="button"
            className="underline underline-offset-2 hover:text-amber-100"
            onClick={() => setPlaygroundKey(null)}
          >
            {copy.playground.useAdminKeyAgain}
          </button>
        </div>
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
                <Badge>{projectName(k.project_id)}</Badge>
                {playgroundKey && !k.revoked_at && playgroundKey.startsWith(k.key_prefix) ? (
                  <Badge tone="warn">{copy.keys.bound}</Badge>
                ) : null}
              </div>
              <div className="mt-0.5 font-mono text-xs text-zinc-500">
                {k.key_prefix}… · 创建于 {formatDateTime(k.created_at)}
              </div>
            </div>
            {!k.revoked_at ? (
              confirmingId === k.id ? (
                <span className="flex items-center gap-1">
                  <span className="text-xs text-red-300">{copy.keys.revokeConfirm}</span>
                  <Button
                    variant="danger"
                    disabled={revokeMutation.isPending}
                    onClick={() => revokeMutation.mutate(k.id)}
                  >
                    {copy.keys.revoke}
                  </Button>
                  <Button variant="ghost" onClick={() => setConfirmingId(null)}>
                    {copy.keys.close}
                  </Button>
                </span>
              ) : (
                <Button variant="danger" onClick={() => setConfirmingId(k.id)}>
                  {copy.keys.revoke}
                </Button>
              )
            ) : null}
          </Card>
        ))
      )}
    </div>
  );
}
