import { useEffect, useState } from "react";
import { Bookmark, Sparkles, Users } from "lucide-react";
import { apiFetch, signOut } from "../../lib/api";
import { initAppLogger, trackPageView } from "../../lib/appLogger";
import { ChatPage } from "./pages/ChatPage";
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
  // Phones show the contacts list first and the chat full screen; web shows both side by side.
  const isMobile = useIsMobile();
  const [mobileChatOpen, setMobileChatOpen] = useState(false);

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
    const sync = () => setPage(pageFromPath());
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
  }

  // The profile is the source of truth; Google's name and photo are only the fallback.
  const displayName = profile?.display_name || user?.display_name || user?.email || "Account";
  const initial = displayName.trim().slice(0, 1).toUpperCase() || "O";
  const profileAvatar = mainPhoto(profile, user?.avatar_url);

  const showContactsHome = isMobile && page === "chat" && !mobileChatOpen;
  const chatOpenOnMobile = isMobile && page === "chat" && mobileChatOpen;
  const openOmi = () => { navigate("chat"); setMobileChatOpen(true); };
  const omiRow = (
    <button type="button" className={`omi-contact ${page === "chat" && !showContactsHome ? "is-active" : ""}`} onClick={openOmi}>
      <span className="omi-contact-avatar"><AgentOrb /></span>
      <span className="omi-contact-copy"><strong>Omi</strong><small>AI companion</small></span>
    </button>
  );

  return (
    <div className={`legacy-react-shell omi-shell ${chatOpenOnMobile ? "is-chat-open" : ""}`}>
      <aside className="omi-rail">
        <div className="omi-rail-top">
          <button className="omi-brand" type="button" onClick={() => { navigate("chat"); setMobileChatOpen(false); }} aria-label="Omiryn home">
            <img src={assetUrl("omiryn-logo-neon.png")} alt="" />
            <strong>Omiryn</strong>
          </button>
          <nav className="omi-rail-nav" aria-label="Main navigation">
            {([["vibe", Sparkles, "Vibe"], ["memories", Bookmark, "Memories"], ["matches", Users, "Matches"]] as const).map(([item, Icon, label]) => (
              <a className={page === item ? "is-active" : ""} href={pathForPage[item]} key={item} title={label} aria-label={label} onClick={(event) => { event.preventDefault(); navigate(item); }}><Icon aria-hidden="true" /></a>
            ))}
          </nav>
        </div>
        <div className="omi-contacts" aria-label="Chats">{omiRow}</div>
        <div className="omi-account">
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
        {showContactsHome ? <div className="omi-contacts-home"><p className="omi-contacts-label">Chats</p>{omiRow}</div> : null}
        {page === "chat" && !showContactsHome ? <ChatPage initialConversationId={initialConversationId} userAvatar={profileAvatar} onBack={isMobile ? () => setMobileChatOpen(false) : undefined} /> : null}
        {page === "vibe" ? <VibePage onChat={openOmi} /> : null}
        {page === "memories" ? <MemoriesPage /> : null}
        {page === "matches" ? <MatchesPage onVibe={() => navigate("vibe")} /> : null}
        {page === "profile" ? <ProfilePage onVibe={() => navigate("vibe")} fallbackAvatar={user?.avatar_url || null} onProfileChange={setProfile} /> : null}
        {page === "contact" ? <ContactPage user={user} /> : null}
      </main>
    </div>
  );
}
