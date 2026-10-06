import type { Profile } from "./types";

// The one photo that stands for the user everywhere (header, chat, profile): the first uploaded
// photo in any slot, then the older single photo field, then the sign-in (Google) photo.
export function mainPhoto(profile: Profile | null | undefined, fallback?: string | null): string | null {
  return profile?.profile_photo_urls?.find(Boolean) || profile?.profile_photo_url || fallback || null;
}
