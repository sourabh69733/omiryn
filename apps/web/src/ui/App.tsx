import { useEffect, useState } from "react";
import { MessageCircle, Sparkles, Users } from "lucide-react";
import { apiFetch, ensureAuthenticatedSession, signInWithGoogle } from "../lib/api";
import { MainApp } from "./app/MainApp";
import { AgentOrb } from "./app/AgentOrb";
import { OmirynLogo } from "./brand/OmirynLogo";
import { QuickSetup } from "./onboarding/QuickSetup";

type AuthState = "checking" | "signed_in" | "signed_out";
type ProfileState = "checking" | "complete" | "incomplete";

function conversationIdFromUrl() {
  return new URLSearchParams(window.location.search).get("conversation_id");
}

function AppLoader() {
  const loaderMark = `${import.meta.env.BASE_URL}assets/omiryn-mark.svg`;
  const loaderMarkDark = `${import.meta.env.BASE_URL}assets/omiryn-mark-dark.svg`;
  return (
    <main className="boot-loader" aria-label="Loading Omiryn" role="status">
      <div className="boot-mark-card" aria-hidden="true">
        <picture>
          <source srcSet={loaderMarkDark} media="(prefers-color-scheme: dark)" />
          <img className="boot-logo-image" src={loaderMark} alt="" />
        </picture>
        <span className="boot-word">Omiryn</span>
      </div>
    </main>
  );
}

export function App() {
  const [authState, setAuthState] = useState<AuthState>("checking");
  const [profileState, setProfileState] = useState<ProfileState>("checking");
  const [authError, setAuthError] = useState<string | null>(null);
  const [isSigningIn, setIsSigningIn] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const requireAuth = () => {
      setAuthState("signed_out");
      setProfileState("checking");
    };
    window.addEventListener("omiryn:auth-required", requireAuth);
    ensureAuthenticatedSession()
      .then((ready) => {
        if (!cancelled) setAuthState(ready ? "signed_in" : "signed_out");
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setAuthError(caught instanceof Error ? caught.message : "Could not check sign in.");
          setAuthState("signed_out");
        }
      });
    return () => {
      cancelled = true;
      window.removeEventListener("omiryn:auth-required", requireAuth);
    };
  }, []);

  useEffect(() => {
    if (authState !== "signed_in") return;
    let cancelled = false;
    apiFetch("/api/me/basics")
      .then(async (response) => response.ok ? response.json() : { complete: false })
      .then((data) => {
        if (!cancelled) setProfileState(data.complete ? "complete" : "incomplete");
      })
      .catch(() => {
        if (!cancelled) setProfileState("incomplete");
      });
    return () => { cancelled = true; };
  }, [authState]);

  async function beginGoogleSignIn() {
    if (isSigningIn) return;
    setAuthError(null);
    setIsSigningIn(true);
    try {
      await signInWithGoogle();
    } catch (caught) {
      setAuthError(caught instanceof Error ? caught.message : "Could not start Google sign-in.");
      setIsSigningIn(false);
    }
  }

  if (authState === "checking" || (authState === "signed_in" && profileState === "checking")) {
    return <AppLoader />;
  }

  if (authState === "signed_out") {
    return (
      <main className="auth-screen-page">
        <div className="auth-layout">
          <section className="auth-intro" aria-labelledby="auth-intro-title">
            <OmirynLogo />
            <div className="auth-intro-copy">
              <span className="auth-intro-orb"><AgentOrb state="idle" /></span>
              <h1 id="auth-intro-title">Talk first.<br /><em>Connect better.</em></h1>
              <ol className="auth-steps">
                <li><MessageCircle aria-hidden="true" />Just talk to Omi</li>
                <li><Sparkles aria-hidden="true" />It learns your vibe</li>
                <li><Users aria-hidden="true" />Meet people who click</li>
              </ol>
            </div>
          </section>
          <section className="auth-card" aria-label="Sign in">
            <h2>Sign in to Omiryn</h2>
            <button className="google-signin-button" type="button" onClick={() => void beginGoogleSignIn()} disabled={isSigningIn}>
              <span className="google-mark" aria-hidden="true">G</span>
              {isSigningIn ? "Opening Google..." : "Continue with Google"}
            </button>
            {authError ? <p className="auth-error" role="alert">{authError}</p> : null}
            <small>By continuing, you agree to Omiryn's <a href="https://omiryn.com/terms">Terms</a> and <a href="https://omiryn.com/privacy">Privacy Policy</a>.</small>
          </section>
        </div>
      </main>
    );
  }

  if (profileState === "incomplete") return <QuickSetup />;
  return <MainApp initialConversationId={conversationIdFromUrl()} />;
}
