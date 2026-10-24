import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import type { ApiKeyRow, Project } from "../api/types";
import {
  Badge,
  Button,
  Card,
  Empty,
  ErrorBox,
  Input,
  PageTitle,
  Spinner,
} from "../components/ui";
import { saveKeys, useKeys } from "../hooks/keys";

export function Keys({ onProjectKey }: { onProjectKey: (patch: { projectKey: string }) => void }) {
  const { adminKey } = useKeys();
  const queryClient = useQueryClient();
  const [newProject, setNewProject] = useState("");
  const [selectedProject, setSelectedProject] = useState<string>("");
  const [createdKey, setCreatedKey] = useState<string | null>(null);

  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: () => api<Project[]>("/v1/admin/projects", adminKey),
  });
  const keys = useQuery({
    queryKey: ["keys"],
    queryFn: () => api<ApiKeyRow[]>("/v1/admin/keys", adminKey),
  });

  const createProject = useMutation({
    mutationFn: (name: string) =>
      api<Project>("/v1/admin/projects", adminKey, { method: "POST", body: { name } }),
    onSuccess: (project) => {
      setNewProject("");
      setSelectedProject(project.id);
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });
  const createKey = useMutation({
    mutationFn: () =>
      api<{ key: string; detail: ApiKeyRow }>("/v1/admin/keys", adminKey, {
        method: "POST",
        body: { project_id: selectedProject },
      }),
    onSuccess: (created) => {
      setCreatedKey(created.key);
      void queryClient.invalidateQueries({ queryKey: ["keys"] });
    },
  });
  const revoke = useMutation({
    mutationFn: (keyId: string) =>
      api<ApiKeyRow>(`/v1/admin/keys/${keyId}/revoke`, adminKey, { method: "POST" }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["keys"] }),
  });

  if (projects.isLoading || keys.isLoading) return <Spinner />;
  if (projects.error) return <ErrorBox>{String(projects.error)}</ErrorBox>;

  return (
    <div>
      <PageTitle>API Keys</PageTitle>

      <Card className="mb-4 space-y-3">
        <div className="flex gap-2">
          <Input
            value={newProject}
            onChange={(event) => setNewProject(event.target.value)}
            placeholder="新 project 名称"
          />
          <Button
            disabled={!newProject.trim() || createProject.isPending}
            onClick={() => createProject.mutate(newProject.trim())}
          >
            建 project
          </Button>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            className="rounded border border-line bg-base px-2 py-1.5 text-sm"
            value={selectedProject}
            onChange={(event) => setSelectedProject(event.target.value)}
          >
            <option value="">选择 project…</option>
            {projects.data?.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
          <Button
            disabled={!selectedProject || createKey.isPending}
            onClick={() => createKey.mutate()}
          >
            创建 key
          </Button>
          {selectedProject && (
            <span className="text-xs text-dim">
              {projects.data?.find((p) => p.id === selectedProject)?.name}
            </span>
          )}
        </div>
        {createKey.error && <ErrorBox>{String(createKey.error)}</ErrorBox>}
        {createdKey && (
          <div className="rounded border border-accent/50 bg-accent/10 p-3 text-sm">
            <p className="mb-1 font-medium">新 key（仅此一次显示，请立即保存）：</p>
            <code className="block break-all text-xs">{createdKey}</code>
            <div className="mt-2 flex gap-2">
              <Button variant="ghost" onClick={() => void navigator.clipboard.writeText(createdKey)}>
                复制
              </Button>
              <Button
                onClick={() => {
                  saveKeys({ projectKey: createdKey });
                  onProjectKey({ projectKey: createdKey });
                  setCreatedKey(null);
                }}
              >
                用于 Playground
              </Button>
            </div>
          </div>
        )}
      </Card>

      {keys.data && keys.data.length === 0 ? (
        <Empty>还没有 key。</Empty>
      ) : (
        <div className="space-y-2">
          {keys.data?.map((row) => (
            <Card key={row.id} className="flex flex-wrap items-center gap-3 py-3">
              <code className="text-xs">{row.key_prefix}…</code>
              <span className="text-xs text-dim">
                {projects.data?.find((p) => p.id === row.project_id)?.name ?? row.project_id}
              </span>
              <Badge tone="muted">{row.rate_limit_per_min}/min</Badge>
              {row.revoked_at ? (
                <Badge tone="bad">已撤销</Badge>
              ) : (
                <Badge tone="ok">生效中</Badge>
              )}
              <span className="ml-auto text-xs text-dim">
                {row.created_at.slice(0, 10)}
              </span>
              {!row.revoked_at && (
                <Button variant="danger" onClick={() => revoke.mutate(row.id)}>
                  撤销
                </Button>
              )}
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
