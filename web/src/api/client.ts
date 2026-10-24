/** fetch 封装：Authorization、错误信封 → 类型化异常（与 SDK 同语义的轻量版）。 */

export class ApiError extends Error {
  code: string;
  retryable: boolean;
  status: number;

  constructor(message: string, code: string, retryable: boolean, status: number) {
    super(message);
    this.code = code;
    this.retryable = retryable;
    this.status = status;
  }
}

export async function api<T>(
  path: string,
  key: string,
  init: { method?: string; body?: unknown } = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      method: init.method ?? "GET",
      headers: {
        Authorization: `Bearer ${key}`,
        ...(init.body !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
    });
  } catch (cause) {
    throw new ApiError(`网络错误：${String(cause)}`, "network", true, 0);
  }
  if (response.ok) {
    return (await response.json()) as T;
  }
  let code = "internal";
  let message = `HTTP ${response.status}`;
  let retryable = false;
  try {
    const envelope = (await response.json()) as {
      error?: { code?: string; message?: string; retryable?: boolean };
    };
    code = envelope.error?.code ?? code;
    message = envelope.error?.message ?? message;
    retryable = envelope.error?.retryable ?? retryable;
  } catch {
    /* 非 JSON 错误体，保留默认值 */
  }
  throw new ApiError(message, code, retryable, response.status);
}

/** 无鉴权的健康探测。 */
export async function health(path: string): Promise<Record<string, unknown>> {
  const response = await fetch(path);
  return (await response.json()) as Record<string, unknown>;
}
