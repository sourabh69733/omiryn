import { createClient, type SupabaseClient } from "@supabase/supabase-js";

type AuthConfig = {
  auth_provider?: string;
  providers?: {
    supabase?: {
      url?: string;
      anon_key?: string;
    };
  };
  supabase_url?: string;
  supabase_anon_key?: string;
};

let authClientPromise: Promise<SupabaseClient | null> | null = null;
const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL || "").trim().replace(/\/+$/, "");

function apiUrl(input: string) {
  if (!apiBaseUrl || !input.startsWith("/")) return input;
  return `${apiBaseUrl}${input}`;
}

export function apiWebSocketUrl(input: string) {
  const url = new URL(apiUrl(input), window.location.href);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url;
}

async function getAuthClient() {
  if (authClientPromise) return authClientPromise;

  authClientPromise = fetch(apiUrl("/api/auth/config"))
    .then(async (response) => {
      if (!response.ok) throw new Error("Could not load sign-in configuration.");
      const config = (await response.json()) as AuthConfig;
      if (config.auth_provider !== "supabase") return null;

      const provider = config.providers?.supabase;
      const url = provider?.url || config.supabase_url;
      const anonKey = provider?.anon_key || config.supabase_anon_key;
      if (!url || !anonKey) throw new Error("Sign-in is not configured correctly.");
      return createClient(url, anonKey);
    })
    .catch((error) => {
      authClientPromise = null;
      throw error;
    });

  return authClientPromise;
}

export async function apiFetch(input: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers);
  const timeZone = browserTimeZone();
  if (timeZone) headers.set("X-Timezone", timeZone);
  const authClient = await getAuthClient();

  if (authClient) {
    const { data, error } = await authClient.auth.getSession();
    if (error) throw new Error("Could not restore your sign-in session.");
    if (data.session?.access_token) {
      headers.set("Authorization", `Bearer ${data.session.access_token}`);
    }
  }

  const response = await fetch(apiUrl(input), { ...init, headers });
  if (response.status === 401 && authClient) {
    await authClient.auth.signOut({ scope: "local" });
    window.dispatchEvent(new Event("omiryn:auth-required"));
  }
  return response;
}

export async function ensureAuthenticatedSession() {
  const authClient = await getAuthClient();
  if (!authClient) return true;

  const { data, error } = await authClient.auth.getSession();
  if (error) throw new Error("Could not restore your sign-in session.");
  return Boolean(data.session?.access_token);
}

export async function signInWithGoogle() {
  const authClient = await getAuthClient();
  if (!authClient) throw new Error("Google sign-in is not configured.");

  const returnUrl = new URL(window.location.href);
  returnUrl.hash = "";
  const { error } = await authClient.auth.signInWithOAuth({
    provider: "google",
    options: { redirectTo: returnUrl.toString() }
  });
  if (error) throw new Error("Could not start Google sign-in. Please try again.");
}

export async function signOut() {
  const authClient = await getAuthClient();
  if (authClient) await authClient.auth.signOut();
  window.dispatchEvent(new Event("omiryn:auth-required"));
}

export type ApiErrorDetail = { message: string; code?: string; messageIndex?: number };

// `detail` is a string, or {code, message, message_index} for errors the UI handles inline.
export async function apiErrorDetail(response: Response, fallback: string): Promise<ApiErrorDetail> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    const detail = body.detail;
    if (typeof detail === "string") return { message: detail || fallback };
    if (detail && typeof detail === "object") {
      const record = detail as { message?: unknown; code?: unknown; message_index?: unknown };
      return {
        message: typeof record.message === "string" ? record.message : fallback,
        code: typeof record.code === "string" ? record.code : undefined,
        messageIndex: typeof record.message_index === "number" ? record.message_index : undefined
      };
    }
    return { message: fallback };
  } catch {
    return { message: fallback };
  }
}

export async function apiErrorMessage(response: Response, fallback: string) {
  return (await apiErrorDetail(response, fallback)).message;
}

// IANA name such as "Asia/Kolkata"; the agent uses it to know the user's local time.
function browserTimeZone(): string | null {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || null;
  } catch {
    return null;
  }
}
