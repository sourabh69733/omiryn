import { OmirynLogo } from "../brand/OmirynLogo";
import { ChatBubble } from "./ChatBubble";
import { ChatComposer } from "./ChatComposer";
import { ProfilePreview } from "./ProfilePreview";
import { ProgressPill } from "./ProgressPill";
import { onboardingSteps } from "./onboardingSteps";

export function OnboardingChat() {
  const step = onboardingSteps[0];

  return (
    <main className="onboarding-page">
      <header className="onboarding-topbar">
        <OmirynLogo />
        <ProgressPill current={1} total={onboardingSteps.length} />
      </header>

      <section className="onboarding-layout">
        <aside className="onboarding-copy">
          <h1>
            Talk first. <span>Match better.</span>
          </h1>
          <p>Tiny setup, one question at a time.</p>
        </aside>

        <section className="conversation-panel" aria-label="Onboarding chat">
          <div className="conversation-heading">
            <h2>Onboarding chat</h2>
            <p>A tiny setup, then we match smarter.</p>
          </div>

          <div className="chat-canvas">
            <span className="doodle question" aria-hidden="true">
              ?
            </span>
            <span className="doodle heart" aria-hidden="true">
              ♡
            </span>
            <span className="doodle check" aria-hidden="true" />
            <ChatBubble role="agent" hint={step.hint}>
              {step.question}
            </ChatBubble>
          </div>

          <ChatComposer placeholder={step.placeholder} />
        </section>

        <ProfilePreview />
      </section>
    </main>
  );
}
