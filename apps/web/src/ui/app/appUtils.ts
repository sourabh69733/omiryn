import type { Page } from "./types";

export const canShowUsage = import.meta.env.DEV;

export const pageFromPath = (): Page => {
  if (window.location.pathname.startsWith("/contact")) return "contact";
  if (window.location.pathname.startsWith("/style")) return "style";
  if (window.location.pathname.startsWith("/matches")) return "matches";
  if (window.location.pathname.startsWith("/profile")) return "profile";
  return "chat";
};

export const pathForPage: Record<Page, string> = {
  chat: "/",
  style: "/style",
  matches: "/matches",
  profile: "/profile",
  contact: "/contact"
};

export const assetUrl = (assetPath: string) => `${import.meta.env.BASE_URL}assets/${assetPath}`;
