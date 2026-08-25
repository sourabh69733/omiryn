import { createClient } from "@supabase/supabase-js";

import { buildApiUrl, createAdminFetch } from "./api.js";

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL || "").trim().replace(/\/+$/, "");
let authClientPromise = null;

async function getAuthClient() {
  if (authClientPromise) return authClientPromise;

  authClientPromise = fetch(buildApiUrl(apiBaseUrl, "/api/auth/config"))
    .then(async (response) => {
      if (!response.ok) throw new Error("Could not load sign-in configuration.");

      const config = await response.json();
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

async function getAccessToken() {
  const authClient = await getAuthClient();
  if (!authClient) return null;

  const { data, error } = await authClient.auth.getSession();
  if (error) throw new Error("Could not restore your sign-in session.");
  return data.session?.access_token || null;
}

export async function ensureAdminSession() {
  return Boolean(await getAccessToken());
}

export async function signInWithGoogle() {
  const authClient = await getAuthClient();
  if (!authClient) throw new Error("Google sign-in is not configured.");

  const returnUrl = new URL(window.location.href);
  returnUrl.hash = "";
  const { error } = await authClient.auth.signInWithOAuth({
    provider: "google",
    options: { redirectTo: returnUrl.toString() },
  });
  if (error) throw new Error("Could not start Google sign-in. Please try again.");
}

export async function signOut() {
  const authClient = await getAuthClient();
  if (authClient) await authClient.auth.signOut({ scope: "local" });
  window.dispatchEvent(new Event("omiryn:auth-required"));
}

export const adminFetch = createAdminFetch({
  apiBaseUrl,
  getAccessToken,
  onUnauthorized: signOut,
});
