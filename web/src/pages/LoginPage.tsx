/** 登录页：管理员 key（sessionStorage 暂存，即时校验）；后端未就绪时一键进入离线演示。 */

import { useState } from "react";
import { useNavigate } from "react-router";
import { useAdminKey } from "../hooks/useAdminKey";
import { ApiRequestError, createRealClient } from "../api/client";
import { copy } from "../lib/copy";
import { Button, Card, Input, Spinner } from "../components/ui";

export function LoginPage() {
  const { signIn } = useAdminKey();
  const navigate = useNavigate();
  const [key, setKey] = useState("");
  const [error, setError] = useState("");
  const [checking, setChecking] = useState(false);

  const submit = async (mode: "real" | "demo") => {
    if (mode === "real") {
      if (!key.trim()) {
        setError(copy.login.invalid);
        return;
      }
      setChecking(true);
      setError("");
      try {
        // 用 admin 端点探测 key 有效性：401/403 直接拒绝登录；
        // 网络不通则放行（错误在各页面的错误态里呈现）
        await createRealClient({ apiKey: key.trim() }).listKeys();
      } catch (err) {
        setChecking(false);
        if (err instanceof ApiRequestError && (err.status === 401 || err.status === 403)) {
          setError(copy.login.authFailed);
        } else {
          setError(err instanceof Error ? err.message : String(err));
        }
        return;
      }
      setChecking(false);
    }
    signIn(key.trim(), mode);
    navigate("/playground");
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface p-4">
      <Card className="w-full max-w-sm p-6">
        <h1 className="text-lg font-semibold">{copy.login.title}</h1>
        <p className="mt-1 text-xs text-zinc-500">{copy.app.subtitle}</p>
        <form
          className="mt-5 space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            void submit("real");
          }}
        >
          <label className="block text-sm text-zinc-300" htmlFor="admin-key">
            {copy.login.keyLabel}
          </label>
          <Input
            id="admin-key"
            type="password"
            autoComplete="off"
            placeholder={copy.login.keyPlaceholder}
            value={key}
            onChange={(e) => {
              setKey(e.target.value);
              setError("");
            }}
          />
          {error ? <div className="text-xs text-red-400">{error}</div> : null}
          <Button type="submit" className="w-full" disabled={checking}>
            {checking ? <Spinner /> : null}
            {copy.login.submit}
          </Button>
        </form>
        <div className="mt-5 border-t border-surface-border pt-4">
          <Button variant="ghost" className="w-full" onClick={() => void submit("demo")}>
            {copy.login.demo}
          </Button>
          <p className="mt-2 text-center text-xs text-zinc-600">{copy.login.demoHint}</p>
        </div>
      </Card>
    </div>
  );
}
