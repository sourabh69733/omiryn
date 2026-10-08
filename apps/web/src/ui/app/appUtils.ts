import type { Page } from "./types";

export const canShowUsage = import.meta.env.DEV;

export const pageFromPath = (): Page => {
  if (window.location.pathname.startsWith("/contact")) return "contact";
  if (window.location.pathname.startsWith("/vibe")) return "vibe";
  // /style is the old name of Memories.
  if (/^\/(memories|style)/.test(window.location.pathname)) return "memories";
  if (window.location.pathname.startsWith("/matches")) return "matches";
  if (window.location.pathname.startsWith("/profile/privacy")) return "privacy";
  if (window.location.pathname.startsWith("/profile")) return "profile";
  return "chat";
};

export const pathForPage: Record<Page, string> = {
  chat: "/",
  vibe: "/vibe",
  memories: "/memories",
  matches: "/matches",
  profile: "/profile",
  privacy: "/profile/privacy",
  contact: "/contact"
};

export const assetUrl = (assetPath: string) => `${import.meta.env.BASE_URL}assets/${assetPath}`;
