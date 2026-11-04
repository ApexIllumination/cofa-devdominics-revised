// Same-origin cookie sessions. No automatic retries, including for writes.
export class HttpError extends Error {
  constructor(readonly status: number) { super(`HTTP ${status}`); }
}

export async function request(path: string, init: RequestInit = {}): Promise<Response> {
  const url = new URL(path, window.location.origin);
  if (url.origin !== window.location.origin) throw new Error("다른 출처의 API 주소입니다.");
  const response = await fetch(url, {
    ...init, credentials: "same-origin", mode: "same-origin", cache: "no-store",
  });
  if (!response.ok) throw new HttpError(response.status);
  return response;
}

// For a JSON endpoint: check the actual payload at the boundary.
export async function getJson<T>(path: string, decode: (value: unknown) => T, signal?: AbortSignal) {
  const response = await request(path, { signal });
  if (response.status === 204) throw new Error("JSON 대신 빈 응답을 받았습니다.");
  return decode(await response.json());
}

// Login/logout return 204. Never call response.json() on those responses.
export function postJson(path: string, body: unknown) {
  return request(path, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
}
