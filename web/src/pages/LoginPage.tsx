/** 登录页：管理员 key（sessionStorage 暂存）；后端未就绪时一键进入离线演示。 */

import { useState } from "react";
import { useNavigate } from "react-router";
import { useAdminKey } from "../hooks/useAdminKey";
import { copy } from "../lib/copy";
import { Button, Card, Input } from "../components/ui";

export function LoginPage() {
  const { signIn } = useAdminKey();
  const navigate = useNavigate();
  const [key, setKey] = useState("");
  const [error, setError] = useState("");

  const submit = (mode: "real" | "demo") => {
    if (mode === "real" && !key.trim()) {
      setError(copy.login.invalid);
      return;
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
            submit("real");
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
          <Button type="submit" className="w-full">
            {copy.login.submit}
          </Button>
        </form>
        <div className="mt-5 border-t border-surface-border pt-4">
          <Button variant="ghost" className="w-full" onClick={() => submit("demo")}>
            {copy.login.demo}
          </Button>
          <p className="mt-2 text-center text-xs text-zinc-600">{copy.login.demoHint}</p>
        </div>
      </Card>
    </div>
  );
}
