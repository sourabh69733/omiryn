import { useEffect, useRef, useState } from "react";
import { Bookmark, Sparkles, Users, X } from "lucide-react";
import { apiFetch, signOut } from "../../lib/api";
import { initAppLogger, trackPageView } from "../../lib/appLogger";
import { ChatPage, type OmiStatus } from "./pages/ChatPage";
import { ContactPage } from "./pages/ContactPage";
import { MatchesPage } from "./pages/MatchesPage";
import { MemoriesPage } from "./pages/MemoriesPage";
import { ProfilePage } from "./pages/ProfilePage";
import { VibePage } from "./pages/VibePage";
import { AgentOrb } from "./AgentOrb";
import { AvatarImage } from "./AvatarImage";
import { mainPhoto } from "./profilePhoto";
import { assetUrl, canShowUsage, pageFromPath, pathForPage } from "./appUtils";
import { useIsMobile } from "./useIsMobile";
import type { AuthUser, Page, Profile, ProfileResponse } from "./types";

export function MainApp({ initialConversationId }: { initialConversationId?: string | null }) {
  const [page, setPage] = useState<Page>(pageFromPath);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [accountOpen, setAccountOpen] = useState(false);
  const accountRef = useRef<HTMLDivElement | null>(null);
  const isMobile = useIsMobile();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const mobileNavRef = useRef<HTMLElement | null>(null);
  const [omiStatus, setOmiStatus] = useState<OmiStatus>({ typing: false, preview: "", viewingEarlier: false });

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
    const sync = () => { setPage(pageFromPath()); setMobileNavOpen(false); };
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
    };
    syncHeight();
    viewport?.addEventListener("resize", syncHeight);
    window.addEventListener("resize", syncHeight);
    return () => {
      viewport?.removeEventListener("resize", syncHeight);
      window.removeEventListener("resize", syncHeight);
      document.documentElement.style.removeProperty("--omi-viewport-height");
    };
  }, [isMobile]);

  // The profile is the source of truth; Google's name and photo are only the fallback.
  const displayName = profile?.display_name || user?.display_name || user?.email || "Account";
  const initial = displayName.trim().slice(0, 1).toUpperCase() || "O";
  const profileAvatar = mainPhoto(profile, user?.avatar_url);

  const navItems = [["vibe", Sparkles, "Vibe"], ["memories", Bookmark, "Memories"], ["matches", Users, "Matches"]] as const;
  const chatOpenOnMobile = isMobile && page === "chat";
  const openOmi = () => navigate("chat");
  const omiRow = (
    <button type="button" className={`omi-contact ${page === "chat" && !omiStatus.viewingEarlier ? "is-active" : ""}`} onClick={openOmi}>
      <span className="omi-contact-avatar"><AgentOrb state={omiStatus.typing ? "thinking" : "idle"} /></span>
      <span className="omi-contact-copy"><strong>Omi</strong>{omiStatus.typing ? <small className="is-typing">typing…</small> : <small>{omiStatus.preview || "Finds your people"}</small>}</span>
    </button>
  );

  return (
    <div className={`legacy-react-shell omi-shell ${chatOpenOnMobile ? "is-chat-open" : ""}`}>
      <aside className="omi-rail">
        <div className="omi-rail-top">
          <button className="omi-brand" type="button" onClick={openOmi} aria-label="Omiryn home">
            <img src={assetUrl("omiryn-logo-neon.png")} alt="" />
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
        </div>
        <nav className="omi-rail-section omi-rail-links" aria-label="You">
          <p className="omi-rail-label">You</p>
          {navItems.map(([item, Icon, label]) => (
            <a className={page === item ? "is-active" : ""} href={pathForPage[item]} key={item} onClick={(event) => { event.preventDefault(); navigate(item); }}><Icon aria-hidden="true" />{label}</a>
          ))}
        </nav>
        <div className="omi-account" ref={accountRef}>
          <button className="omi-account-button" type="button" onClick={() => setAccountOpen((value) => !value)} aria-expanded={accountOpen} aria-label="Account">
            <span className="omi-account-avatar"><AvatarImage src={profileAvatar} fallback={initial} /></span>
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
        {page === "chat" ? <ChatPage initialConversationId={initialConversationId} userAvatar={profileAvatar} onOpenNavigation={isMobile ? () => setMobileNavOpen(true) : undefined} onOmiStatus={(next) => setOmiStatus((current) => ({ ...next, preview: next.preview || current.preview }))} /> : null}
        {page === "vibe" ? <VibePage onChat={openOmi} /> : null}
        {page === "memories" ? <MemoriesPage /> : null}
        {page === "matches" ? <MatchesPage onVibe={() => navigate("vibe")} /> : null}
        {page === "profile" ? <ProfilePage onVibe={() => navigate("vibe")} fallbackAvatar={user?.avatar_url || null} onProfileChange={setProfile} /> : null}
        {page === "contact" ? <ContactPage user={user} /> : null}
      </main>
      {isMobile && mobileNavOpen ? (
        <div className="omi-mobile-navigation">
          <button type="button" className="omi-mobile-navigation-backdrop" onClick={closeMobileNavigation} aria-label="Close navigation" />
          <nav className="omi-mobile-navigation-panel" role="dialog" aria-modal="true" aria-label="Mobile navigation" ref={mobileNavRef} onKeyDown={(event) => {
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
