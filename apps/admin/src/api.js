function assertBackendRelativePath(path) {
  const target = String(path || "");
  if (!target.startsWith("/") || target.startsWith("//") || /^[a-z][a-z0-9+.-]*:/i.test(target)) {
    throw new TypeError("Admin API paths must be backend-relative.");
  }
}

export function buildApiUrl(baseUrl, path) {
  const base = String(baseUrl || "").trim().replace(/\/+$/, "");
  const target = String(path || "");

  assertBackendRelativePath(target);
  if (!base) return target;
  return `${base}/${target.replace(/^\/+/, "")}`;
}

export function createAdminFetch({
  apiBaseUrl,
  fetchImpl = globalThis.fetch,
  getAccessToken = async () => null,
  onUnauthorized = async () => {},
}) {
  return async function adminFetch(path, init = {}) {
    const url = buildApiUrl(apiBaseUrl, path);
    const headers = new Headers(init.headers);
    const accessToken = await getAccessToken();
    if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);

    const response = await fetchImpl(url, {
      ...init,
      headers,
    });
    if (response.status === 401) await onUnauthorized();
    return response;
  };
}
