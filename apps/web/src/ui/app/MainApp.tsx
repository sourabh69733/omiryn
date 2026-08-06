import { useEffect, useState } from "react";
import { apiFetch, signOut } from "../../lib/api";
import { initAppLogger, trackPageView } from "../../lib/appLogger";
import { ChatPage } from "./pages/ChatPage";
import { ContactPage } from "./pages/ContactPage";
import { MatchesPage } from "./pages/MatchesPage";
import { ProfilePage } from "./pages/ProfilePage";
import { StylePage } from "./pages/StylePage";
import { assetUrl, canShowUsage, pageFromPath, pathForPage } from "./appUtils";
import type { AuthUser, Page, Profile, ProfileResponse } from "./types";

export function MainApp({ initialConversationId }: { initialConversationId?: string | null }) {
  const [page, setPage] = useState<Page>(pageFromPath);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [accountOpen, setAccountOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    initAppLogger();
    if (!canShowUsage && window.location.pathname.startsWith("/usage")) {
      window.history.replaceState({}, "", "/");
    }
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
    setMenuOpen(false);
    setAccountOpen(false);
  }

  const displayName = user?.display_name || user?.email || "Account";
  const initial = displayName.trim().slice(0, 1).toUpperCase() || "O";
  const profileAvatar = profile?.profile_photo_urls?.find(Boolean) || profile?.profile_photo_url || user?.avatar_url || null;

  return (
    <div className="app-shell legacy-react-shell">
      <header className="app-header">
        <button className="brand" type="button" onClick={() => navigate("chat")} aria-label="Omiryn home">
          <span className="brand-mark"><img src={assetUrl("omiryn-logo-neon.png")} alt="" /></span>
          <span className="brand-copy"><strong>Omiryn</strong><small>Talk first. Match better.</small></span>
        </button>
        <nav className={"app-nav " + (menuOpen ? "is-open" : "")} aria-label="Main navigation">
          {(["chat", "style", "matches", "contact"] as Page[]).map((item) => (
            <a
              className={page === item ? "active" : ""}
              data-nav={item === "chat" ? "interview" : item}
              href={pathForPage[item]}
              key={item}
              onClick={(event) => { event.preventDefault(); navigate(item); }}
            >{item[0].toUpperCase() + item.slice(1)}</a>
          ))}
        </nav>
        <div className="header-actions">
          <button className="secondary-button menu-button" type="button" onClick={() => setMenuOpen((value) => !value)} aria-label="Open menu">
            <span className="menu-icon"><span /><span /><span /></span>
          </button>
          <div className="auth-control">
            <button className="auth-user" type="button" onClick={() => setAccountOpen((value) => !value)} aria-expanded={accountOpen}>
              <span className="auth-avatar">{profileAvatar ? <img src={profileAvatar} alt="" /> : initial}</span>
              <span className="auth-email">{displayName}</span>
            </button>
            {accountOpen ? (
              <div className="account-menu">
                <button type="button" onClick={() => navigate("profile")}>Profile</button>
                <button type="button" onClick={() => void signOut()}>Sign out</button>
              </div>
            ) : null}
          </div>
        </div>
      </header>
      <main>
        {page === "chat" ? <ChatPage initialConversationId={initialConversationId} userAvatar={profileAvatar} /> : null}
        {page === "style" ? <StylePage /> : null}
        {page === "matches" ? <MatchesPage /> : null}
        {page === "profile" ? <ProfilePage /> : null}
        {page === "contact" ? <ContactPage user={user} /> : null}
      </main>
    </div>
  );
}
