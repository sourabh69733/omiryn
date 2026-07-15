import { useEffect, useState } from "react";
import { Sparkles } from "lucide-react";
import { apiFetch, ensureAuthenticatedSession, signInWithGoogle } from "../lib/api";
import { MainApp } from "./app/MainApp";
import { OmirynLogo } from "./brand/OmirynLogo";
import { ProfileSetupWizard } from "./onboarding/ProfileSetupWizard";

type AuthState = "checking" | "signed_in" | "signed_out";
type ProfileState = "checking" | "complete" | "incomplete";

function conversationIdFromUrl() {
  return new URLSearchParams(window.location.search).get("conversation_id");
}

function AppLoader() {
  const loaderLogo = `${import.meta.env.BASE_URL}assets/omiryn-logo-neon-light.png`;
  return (
    <main className="boot-loader" aria-label="Loading Omiryn" role="status">
      <div className="boot-mark-card" aria-hidden="true">
        <span className="boot-logo-glow" />
        <img className="boot-logo-image" src={loaderLogo} alt="" />
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
    apiFetch("/api/me/dating-basics")
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
    return <main className="auth-screen-page"><section className="auth-card"><OmirynLogo /><div className="auth-icon"><Sparkles /></div><p className="eyebrow">Talk first. Match better.</p><h1>Welcome to Omiryn</h1><p className="auth-copy">Sign in to keep your conversations, profile, and matches securely connected to you.</p><button className="google-signin-button" type="button" onClick={() => void beginGoogleSignIn()} disabled={isSigningIn}><span className="google-mark">G</span>{isSigningIn ? "Opening Google…" : "Continue with Google"}</button>{authError ? <p className="auth-error">{authError}</p> : null}<small>By continuing, you agree to Omiryn’s Terms and Privacy Policy.</small></section></main>;
  }

  if (profileState === "incomplete") return <ProfileSetupWizard />;
  return <MainApp initialConversationId={conversationIdFromUrl()} />;
}
