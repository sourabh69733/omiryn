export function buildApiUrl(baseUrl, path) {
  const base = String(baseUrl || "").trim().replace(/\/+$/, "");
  const target = String(path || "");

  if (!base || /^https?:\/\//i.test(target)) return target;
  return `${base}/${target.replace(/^\/+/, "")}`;
}

export function createAdminFetch({
  apiBaseUrl,
  fetchImpl = globalThis.fetch,
  getAccessToken = async () => null,
  onUnauthorized = async () => {},
}) {
  return async function adminFetch(path, init = {}) {
    const headers = new Headers(init.headers);
    const accessToken = await getAccessToken();
    if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);

    const response = await fetchImpl(buildApiUrl(apiBaseUrl, path), {
      ...init,
      headers,
    });
    if (response.status === 401) await onUnauthorized();
    return response;
  };
}
