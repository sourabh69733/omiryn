import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Bookmark, Sparkles, Users, X } from "lucide-react";
import { apiFetch, signOut } from "../../lib/api";
import { initAppLogger, trackPageView } from "../../lib/appLogger";
import { ChatPage, type OmiStatus } from "./pages/ChatPage";
import { ContactPage } from "./pages/ContactPage";
import { MatchesPage } from "./pages/MatchesPage";
import { PersonChatPage } from "./pages/PersonChatPage";
import { MemoriesPage } from "./pages/MemoriesPage";
import { ProfilePage } from "./pages/ProfilePage";
import { PrivacyPage } from "./pages/PrivacyPage";
import { VibePage } from "./pages/VibePage";
import { AgentOrb } from "./AgentOrb";
import { AvatarImage } from "./AvatarImage";
import { mainPhoto } from "./profilePhoto";
import { initialOf, type MatchCard } from "./matches";
import { MATCH_EVENT, pairFromPath, peopleRows, personPath, previewLine, unreadLabel, type MatchEventDetail } from "./people";
import { assetUrl, canShowUsage, pageFromPath, pathForPage } from "./appUtils";
import { useIsMobile } from "./useIsMobile";
import { useKeyboardA11y } from "./useKeyboardA11y";
import type { AuthUser, Page, Profile, ProfileResponse } from "./types";

export function MainApp({ initialConversationId }: { initialConversationId?: string | null }) {
  const [page, setPage] = useState<Page>(pageFromPath);
  useKeyboardA11y();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [accountOpen, setAccountOpen] = useState(false);
  const accountRef = useRef<HTMLDivElement | null>(null);
  const isMobile = useIsMobile();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const mobileNavRef = useRef<HTMLElement | null>(null);
  const [omiStatus, setOmiStatus] = useState<OmiStatus>({ typing: false, preview: "", away: false });
  const [backToOmi, setBackToOmi] = useState(0);
  // People Omi introduced: their chats sit beside the chat with Omi.
  const [cards, setCards] = useState<MatchCard[]>([]);
  const [cardsLoaded, setCardsLoaded] = useState(false);
  const [personId, setPersonId] = useState<string | null>(() => pairFromPath(window.location.pathname));

  const loadPeople = useCallback(() => {
    apiFetch("/api/me/matches")
      .then((response) => (response.ok ? response.json() : null))
      .then((data: { matches?: MatchCard[] } | null) => { if (data?.matches) setCards(data.matches); })
      .catch(() => undefined)
      .finally(() => setCardsLoaded(true));
  }, []);

  // Who is writing to the user right now, by pair; each entry clears itself.
  const [typingPairs, setTypingPairs] = useState<Record<string, boolean>>({});
  const typingTimers = useRef<Record<string, number>>({});

  useEffect(() => {
    loadPeople();
    // A message, a read on another device, a block: the socket says so and the list refetches.
    // Typing and reactions change nothing the list shows beyond the "typing…" line.
    const onEvent = (event: Event) => {
      const detail = (event as CustomEvent<MatchEventDetail>).detail;
      const pairId = detail?.payload?.pair_id;
      if (detail?.type === "match.reaction") return;
      if (detail?.type === "match.typing" && pairId) {
        const active = detail.payload.active !== false;
        window.clearTimeout(typingTimers.current[pairId]);
        setTypingPairs((current) => ({ ...current, [pairId]: active }));
        if (active) typingTimers.current[pairId] = window.setTimeout(() => setTypingPairs((current) => ({ ...current, [pairId]: false })), 6000);
        return;
      }
      if (pairId) setTypingPairs((current) => (current[pairId] ? { ...current, [pairId]: false } : current));
      loadPeople();
    };
    const onFocus = () => { if (document.visibilityState === "visible") loadPeople(); };
    window.addEventListener(MATCH_EVENT, onEvent);
    window.addEventListener("focus", onFocus);
    return () => {
      window.removeEventListener(MATCH_EVENT, onEvent);
      window.removeEventListener("focus", onFocus);
    };
  }, [loadPeople]);

  const closeMobileNavigation = () => {
    setMobileNavOpen(false);
    window.requestAnimationFrame(() => document.querySelector<HTMLButtonElement>(".omi-back")?.focus());
  };

  useEffect(() => {
    initAppLogger();
    if (!canShowUsage && window.location.pathname.startsWith("/usage")) {
      window.history.replaceState({}, "", "/");
    }
    if (window.location.pathname.startsWith("/style")) window.history.replaceState({}, "", "/memories");
    apiFetch("/api/auth/me").then((response) => response.ok ? response.json() : null).then(setUser).catch(() => undefined);
    apiFetch("/api/me/profile")
      .then((response) => response.ok ? response.json() : null)
      .then((data: ProfileResponse | null) => setProfile(data?.profile || null))
      .catch(() => undefined);
    const sync = () => { setPage(pageFromPath()); setPersonId(pairFromPath(window.location.pathname)); setMobileNavOpen(false); };
    window.addEventListener("popstate", sync);
    return () => window.removeEventListener("popstate", sync);
  }, []);

  useEffect(() => {
    trackPageView(page);
  }, [page]);

  function navigate(next: Page) {
    window.history.pushState({}, "", pathForPage[next]);
    setPage(next);
    setAccountOpen(false);
    setMobileNavOpen(false);
  }

  function openPerson(pairId: string) {
    window.history.pushState({}, "", personPath(pairId));
    setPersonId(pairId);
    setPage("person");
    setAccountOpen(false);
    setMobileNavOpen(false);
  }

  useEffect(() => {
    if (!mobileNavOpen) return;
    mobileNavRef.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeMobileNavigation();
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [mobileNavOpen]);

  useEffect(() => {
    if (!accountOpen) return;
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent && event.key === "Escape") {
        setAccountOpen(false);
        accountRef.current?.querySelector<HTMLButtonElement>(".omi-account-button")?.focus();
      } else if (event instanceof MouseEvent && event.target instanceof Node && !accountRef.current?.contains(event.target)) {
        setAccountOpen(false);
      }
    };
    document.addEventListener("keydown", close);
    document.addEventListener("mousedown", close);
    return () => {
      document.removeEventListener("keydown", close);
      document.removeEventListener("mousedown", close);
    };
  }, [accountOpen]);

  useEffect(() => {
    if (!isMobile) {
      setMobileNavOpen(false);
      return;
    }
    const viewport = window.visualViewport;
    const syncHeight = () => {
      document.documentElement.style.setProperty("--omi-viewport-height", `${Math.round(viewport?.height ?? window.innerHeight)}px`);
      // iOS scrolls the page up when the keyboard opens, pushing the header off screen. The app
      // scrolls inside its panes, never the page, so keep the page at the top.
      if (window.scrollY) window.scrollTo(0, 0);
    };
    syncHeight();
    viewport?.addEventListener("resize", syncHeight);
    viewport?.addEventListener("scroll", syncHeight);
    window.addEventListener("resize", syncHeight);
    return () => {
      viewport?.removeEventListener("resize", syncHeight);
      viewport?.removeEventListener("scroll", syncHeight);
      window.removeEventListener("resize", syncHeight);
      document.documentElement.style.removeProperty("--omi-viewport-height");
    };
  }, [isMobile]);

  // The profile is the source of truth; Google's name and photo are only the fallback.
  const displayName = profile?.display_name || user?.display_name || user?.email || "Account";
  // Their names, to find them among the people in a shared WhatsApp chat.
  const userNames = useMemo(() => [profile?.display_name, user?.display_name].filter((name): name is string => Boolean(name)), [profile?.display_name, user?.display_name]);
  const initial = displayName.trim().slice(0, 1).toUpperCase() || "O";
  const profilePhoto = mainPhoto(profile);
  // Their photo, else Google's, else their initial: the same badge in the rail and on their messages.
  const accountBadge = useMemo(
    () => <AvatarImage src={profilePhoto} fallback={<AvatarImage src={user?.avatar_url} fallback={initial} />} />,
    [profilePhoto, user?.avatar_url, initial],
  );

  const navItems = [["vibe", Sparkles, "Vibe"], ["memories", Bookmark, "Memories"], ["matches", Users, "Matches"]] as const;
  const chatOpenOnMobile = isMobile && (page === "chat" || page === "person");
  const people = useMemo(() => peopleRows(cards), [cards]);
  const person = personId ? cards.find((card) => card.pair_id === personId) ?? null : null;
  // Already in chat but on an earlier or temporary chat: go back to the main Omi chat.
  const openOmi = () => {
    if (page === "chat" && omiStatus.away) setBackToOmi((count) => count + 1);
    navigate("chat");
  };
  const omiRow = (
    <button type="button" className={`omi-contact ${page === "chat" && !omiStatus.away ? "is-active" : ""}`} onClick={openOmi}>
      <span className="omi-contact-avatar"><AgentOrb state={omiStatus.typing ? "thinking" : "idle"} /></span>
      <span className="omi-contact-copy"><strong>Omi</strong>{omiStatus.typing ? <small className="is-typing">typing…</small> : omiStatus.preview ? <small>{omiStatus.preview}</small> : null}</span>
    </button>
  );

  const personRows = people.map((card) => {
    const unread = unreadLabel(card.chat?.unread);
    return (
      <button type="button" key={card.pair_id} className={`omi-contact omi-person ${page === "person" && personId === card.pair_id ? "is-active" : ""} ${unread ? "has-unread" : ""}`} onClick={() => openPerson(card.pair_id)}>
        <span className="omi-contact-avatar omi-person-avatar" aria-hidden="true">{initialOf(card.name)}</span>
        <span className="omi-contact-copy"><strong>{card.name}</strong>{typingPairs[card.pair_id] ? <small className="is-typing">typing…</small> : <small>{previewLine(card)}</small>}</span>
        {unread ? <span className="omi-unread" aria-label={`${card.chat?.unread} unread`}>{unread}</span> : null}
      </button>
    );
  });

  return (
    <div className={`legacy-react-shell omi-shell ${chatOpenOnMobile ? "is-chat-open" : ""}`}>
      <aside className="omi-rail">
        <div className="omi-rail-top">
          <button className="omi-brand" type="button" onClick={openOmi} aria-label="Omiryn home">
            <img src={assetUrl("omiryn-mark.svg")} alt="" />
            <strong>Omiryn</strong>
          </button>
          <nav className="omi-rail-nav" aria-label="Main navigation">
            {navItems.map(([item, Icon, label]) => (
              <a className={page === item ? "is-active" : ""} href={pathForPage[item]} key={item} title={label} aria-label={label} onClick={(event) => { event.preventDefault(); navigate(item); }}><Icon aria-hidden="true" /></a>
            ))}
          </nav>
        </div>
        <div className="omi-rail-section" aria-label="Chats">
          <p className="omi-rail-label">Chats</p>
          {omiRow}
          {personRows}
        </div>
        <nav className="omi-rail-section omi-rail-links" aria-label="You">
          <p className="omi-rail-label">You</p>
          {navItems.map(([item, Icon, label]) => (
            <a className={page === item ? "is-active" : ""} href={pathForPage[item]} key={item} onClick={(event) => { event.preventDefault(); navigate(item); }}><Icon aria-hidden="true" />{label}</a>
          ))}
        </nav>
        <div className="omi-account" ref={accountRef}>
          <button className="omi-account-button" type="button" onClick={() => setAccountOpen((value) => !value)} aria-expanded={accountOpen} aria-label="Account">
            <span className="omi-account-avatar">{accountBadge}</span>
            <span className="omi-account-name">{displayName}</span>
          </button>
          {accountOpen ? (
            <div className="account-menu omi-account-menu">
              <button type="button" onClick={() => navigate("profile")}>Profile</button>
              <button type="button" onClick={() => navigate("contact")}>Contact</button>
              <button type="button" onClick={() => void signOut()}>Sign out</button>
            </div>
          ) : null}
        </div>
      </aside>
      <main className="omi-main">
        <ChatPage active={page === "chat"} backToOmi={backToOmi} onOpenPage={navigate} initialConversationId={initialConversationId} userAvatar={accountBadge} userNames={userNames} onOpenNavigation={isMobile ? () => setMobileNavOpen(true) : undefined} onOmiStatus={(next) => setOmiStatus((current) => ({ ...next, preview: next.preview || current.preview }))} />
        {page === "vibe" ? <VibePage onChat={openOmi} /> : null}
        {page === "memories" ? <MemoriesPage /> : null}
        {page === "person" && personId ? <PersonChatPage pairId={personId} card={person} cardsLoaded={cardsLoaded} userAvatar={accountBadge} isMobile={isMobile} onOpenNavigation={isMobile ? () => setMobileNavOpen(true) : undefined} onChanged={loadPeople} onMatches={() => navigate("matches")} /> : null}
        {page === "matches" ? <MatchesPage onVibe={() => navigate("vibe")} onChat={openOmi} onOpenPerson={openPerson} onPeopleChanged={loadPeople} /> : null}
        {page === "profile" ? <ProfilePage onVibe={() => navigate("vibe")} onPrivacy={() => navigate("privacy")} fallbackAvatar={user?.avatar_url || null} onProfileChange={setProfile} /> : null}
        {page === "privacy" ? <PrivacyPage onProfile={() => navigate("profile")} onMemories={() => navigate("memories")} onContact={() => navigate("contact")} /> : null}
        {page === "contact" ? <ContactPage user={user} /> : null}
      </main>
      {isMobile && mobileNavOpen ? (
        <div className="omi-mobile-navigation">
          <button type="button" className="omi-mobile-navigation-backdrop" onClick={closeMobileNavigation} aria-label="Close navigation" />
          <nav className="omi-mobile-navigation-panel" role="dialog" aria-modal="true" data-focus-managed aria-label="Mobile navigation" ref={mobileNavRef} onKeyDown={(event) => {
            if (event.key !== "Tab") return;
            const controls = mobileNavRef.current?.querySelectorAll<HTMLElement>("a, button:not(:disabled)");
            if (!controls?.length) return;
            const first = controls[0];
            const last = controls[controls.length - 1];
            if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
            else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
          }}>
            <div className="omi-mobile-navigation-heading">
              <strong>Omiryn</strong>
              <button type="button" onClick={closeMobileNavigation} aria-label="Close navigation"><X aria-hidden="true" /></button>
            </div>
            <button type="button" className="omi-mobile-navigation-chat" onClick={openOmi}>
              <AgentOrb state={omiStatus.typing ? "thinking" : "idle"} />
              <span>Chat with Omi</span>
            </button>
            {personRows}
            {navItems.map(([item, Icon, label]) => (
              <a key={item} href={pathForPage[item]} onClick={(event) => { event.preventDefault(); navigate(item); }}>
                <Icon aria-hidden="true" />{label}
              </a>
            ))}
            <a href={pathForPage.profile} onClick={(event) => { event.preventDefault(); navigate("profile"); }}>Profile</a>
            <a href={pathForPage.contact} onClick={(event) => { event.preventDefault(); navigate("contact"); }}>Contact</a>
            <button type="button" onClick={() => void signOut()}>Sign out</button>
          </nav>
        </div>
      ) : null}
    </div>
  );
}
