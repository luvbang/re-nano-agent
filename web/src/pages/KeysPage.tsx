/**
 * API Keys 管理：项目选择/创建 → 创建 key（明文只展示一次）→ 一键绑定 Playground → 撤销。
 * main 后端按 project 隔离（跨 project 一律 404），所以创建 key 前必须先选项目。
 * 布局：设置两列——左侧标签列（标题+说明），右侧面板；分区由 1px 结构线承担。
 */

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAdminKey } from "../hooks/useAdminKey";
import { EmptyState, ErrorState, LoadingState } from "../components/StateViews";
import { Badge, Button, Card, Input } from "../components/ui";
import { copy } from "../lib/copy";
import { formatDateTime } from "../lib/format";

function Section({
  title,
  desc,
  children,
}: {
  title: string;
  desc: string;
  children: React.ReactNode;
}) {
  return (
    <section className="grid grid-cols-1 gap-4 border-t border-line py-7 first:border-t-0 first:pt-0 lg:grid-cols-[300px_1fr] lg:gap-8">
      <div>
        <h2 className="text-lg font-semibold text-white">{title}</h2>
        <p className="mt-1 text-sm leading-relaxed text-mut">{desc}</p>
      </div>
      <div className="min-w-0">{children}</div>
    </section>
  );
}

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

  const selectCls =
    "h-9 rounded-lg border border-control bg-ground px-2.5 text-sm text-ink focus:border-accent focus:outline-none";

  return (
    <div className="mx-auto max-w-[1120px] px-5 pb-12 pt-7 sm:px-8">
      <h1 className="text-2xl font-semibold text-white">{copy.keys.title}</h1>

      <div className="mt-6">
        <Section title={copy.keys.create} desc={copy.keys.createDesc}>
          <Card className="space-y-3 p-4">
            <div className="flex flex-wrap items-center gap-2">
              <select
                className={selectCls}
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
                className="h-9 w-44"
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
                className="h-9 max-w-xs flex-1"
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
              {projectError ? <span className="text-sm text-neg">{projectError}</span> : null}
              {createMutation.isError ? (
                <span className="text-sm text-neg">{createMutation.error.message}</span>
              ) : null}
              {createProjectMutation.isError ? (
                <span className="text-sm text-neg">{createProjectMutation.error.message}</span>
              ) : null}
            </div>
          </Card>

          {created ? (
            <div className="mt-4 rounded-md border border-line bg-panel p-4 sel-left">
              <div className="text-sm font-medium text-white">{copy.keys.created}</div>
              <p className="mt-1 text-sm text-warn">{copy.keys.secretOnce}</p>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <code className="num min-w-0 flex-1 overflow-x-auto rounded-md bg-ground px-3 py-2 text-sm text-ink">
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
                <Button variant="text" onClick={() => setCreated(null)}>
                  {copy.keys.close}
                </Button>
              </div>
            </div>
          ) : null}
        </Section>

        <Section title={copy.keys.listTitle} desc={copy.keys.listDesc}>
          {playgroundKey ? (
            <div className="mb-4 flex items-center gap-2 text-sm text-mut">
              <Badge tone="warn">{copy.keys.bound}</Badge>
              <span className="num">{playgroundKey.slice(0, 12)}…</span>
              <button
                type="button"
                className="text-ink underline underline-offset-2 hover:text-accent"
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
            <ul>
              {keysQuery.data.map((k) => (
                <li key={k.id} className="border-t border-rule py-3 first:border-t-0">
                  <div className="flex items-center gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-medium text-white">{k.name ?? "（未命名）"}</span>
                        {k.revoked_at ? (
                          <Badge tone="error">{copy.keys.revoked}</Badge>
                        ) : (
                          <Badge tone="success">{k.scopes}</Badge>
                        )}
                        <Badge>
                          <span className="num">{k.rate_limit_per_min}/min</span>
                        </Badge>
                        <Badge>{projectName(k.project_id)}</Badge>
                        {playgroundKey && !k.revoked_at && playgroundKey.startsWith(k.key_prefix) ? (
                          <Badge tone="warn">{copy.keys.bound}</Badge>
                        ) : null}
                      </div>
                      <div className="num mt-0.5 text-xs text-mut">
                        {k.key_prefix}… · {copy.keys.createdAt(formatDateTime(k.created_at))}
                      </div>
                    </div>
                    {!k.revoked_at ? (
                      confirmingId === k.id ? (
                        <span className="flex shrink-0 items-center gap-2">
                          <span className="text-sm text-neg">{copy.keys.revokeConfirm}</span>
                          <Button
                            variant="danger"
                            disabled={revokeMutation.isPending}
                            onClick={() => revokeMutation.mutate(k.id)}
                          >
                            {copy.keys.revoke}
                          </Button>
                          <Button variant="text" onClick={() => setConfirmingId(null)}>
                            {copy.keys.close}
                          </Button>
                        </span>
                      ) : (
                        <Button
                          variant="text"
                          className="!text-neg hover:!text-neg"
                          onClick={() => setConfirmingId(k.id)}
                        >
                          {copy.keys.revoke}
                        </Button>
                      )
                    ) : null}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Section>
      </div>
    </div>
  );
}
