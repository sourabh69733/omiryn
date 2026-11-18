// The read tried before sign-in, held in this tab while the person signs in. Sign-in leaves the
// page and comes back, so the chat they picked and the seal of the read they saw wait in session
// storage: it stays on their device, lives only as long as the tab, and is cleared the moment
// the chat is shared after sign-in. The server keeps nothing until then.
import type { ChatRead } from "./chatRead";

export type TriedRead = Extract<ChatRead, { state: "ready" }> & { kept?: string };

export type HeldTry = {
  /** The export's text, as the person picked it. */
  text: string;
  /** Their name in the chat. */
  me: string;
  /** The upload's title: the other person's name. */
  title: string;
  /** The seal of the read they saw, so it is kept and not written again. */
  kept: string | null;
};

const KEY = "omiryn.try_read";
export const TRY_PATH = "/try";

type Store = Pick<Storage, "getItem" | "setItem" | "removeItem">;

function tabStore(): Store | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

/** Hold the chat for after sign-in. False when the browser has no room or no storage: then they
    sign in and share the chat again from 📎. */
export function holdTry(held: HeldTry, store: Store | null = tabStore()): boolean {
  if (!store) return false;
  try {
    store.setItem(KEY, JSON.stringify(held));
    return true;
  } catch {
    try { store.removeItem(KEY); } catch { /* nothing to clear */ }
    return false;
  }
}

/** The held chat, taken out: a second look finds nothing, so it is shared once. */
export function takeTry(store: Store | null = tabStore()): HeldTry | null {
  if (!store) return null;
  try {
    const raw = store.getItem(KEY);
    if (!raw) return null;
    store.removeItem(KEY);
    const held = JSON.parse(raw) as Partial<HeldTry>;
    if (typeof held.text !== "string" || typeof held.me !== "string" || !held.text || !held.me) return null;
    return { text: held.text, me: held.me, title: typeof held.title === "string" && held.title ? held.title : "WhatsApp chat", kept: typeof held.kept === "string" ? held.kept : null };
  } catch {
    return null;
  }
}

export function dropTry(store: Store | null = tabStore()) {
  try { store?.removeItem(KEY); } catch { /* nothing to clear */ }
}

export const isTryPath = (pathname: string) => pathname === TRY_PATH || pathname.startsWith(`${TRY_PATH}/`);
