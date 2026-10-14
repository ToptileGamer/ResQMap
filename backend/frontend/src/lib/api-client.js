const BASE_URL = "/api";

async function request(path, init = {}) {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${body || res.statusText}`);
  }
  return res.json();
}

export const apiClient = {
  get: (path) => request(path),
};
