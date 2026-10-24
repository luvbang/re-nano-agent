import { useState } from "react";

import { Button, Card, ErrorBox, Input } from "../components/ui";
import { loadKeys, saveKeys } from "../hooks/keys";

export function Login({ onLogin }: { onLogin: (adminKey: string) => void }) {
  const [adminKey, setAdminKey] = useState("");
  const [projectKey, setProjectKey] = useState(loadKeys().projectKey);
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);

  async function submit() {
    setChecking(true);
    setError(null);
    try {
      const response = await fetch("/v1/admin/projects", {
        headers: { Authorization: `Bearer ${adminKey.trim()}` },
      });
      if (!response.ok) {
        setError("管理员 key 无效（需要 AGENTD_ADMIN_KEY 或 admin scope 的 key）");
        return;
      }
      saveKeys({ adminKey: adminKey.trim(), projectKey: projectKey.trim() });
      onLogin(adminKey.trim());
    } catch {
      setError("无法连接服务，请确认地址与网络");
    } finally {
      setChecking(false);
    }
  }

  return (
    <div className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-4">
      <Card>
        <h1 className="mb-1 text-lg font-semibold">agentd 控制台</h1>
        <p className="mb-4 text-sm text-dim">
          管理员 key 用于 Keys/Usage/Status；项目 key（可在 Keys 页创建）用于 Playground。
        </p>
        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <div>
            <label className="mb-1 block text-xs text-dim">管理员 key</label>
            <Input
              type="password"
              value={adminKey}
              onChange={(event) => setAdminKey(event.target.value)}
              placeholder="（AGENTD_ADMIN_KEY）"
              autoFocus
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-dim">项目 key（可选，稍后也能填）</label>
            <Input
              type="password"
              value={projectKey}
              onChange={(event) => setProjectKey(event.target.value)}
              placeholder="agd_..."
            />
          </div>
          {error && <ErrorBox>{error}</ErrorBox>}
          <Button type="submit" disabled={checking || !adminKey.trim()}>
            {checking ? "校验中…" : "进入控制台"}
          </Button>
        </form>
      </Card>
    </div>
  );
}
