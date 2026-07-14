import { useMemo, useState } from "react";
import { OmirynLogo } from "../brand/OmirynLogo";
import { ChatBubble } from "./ChatBubble";
import { ChatComposer } from "./ChatComposer";
import { ProfilePreview, type ProfilePreviewValues } from "./ProfilePreview";
import { ProgressPill } from "./ProgressPill";
import { onboardingSteps } from "./onboardingSteps";

type Message = {
  id: string;
  role: "agent" | "user";
  text: string;
  hint?: string;
};

type Answers = {
  [key: string]: string;
};

type ValidationResult =
  | {
      valid: true;
      response: string;
    }
  | {
      valid: false;
      message: string;
    };

function ageFromDob(value: string) {
  const birthDate = new Date(`${value}T00:00:00`);
  if (Number.isNaN(birthDate.getTime())) return null;
  const today = new Date();
  let age = today.getFullYear() - birthDate.getFullYear();
  const monthDiff = today.getMonth() - birthDate.getMonth();
  if (monthDiff < 0 || (monthDiff === 0 && today.getDate() < birthDate.getDate())) {
    age -= 1;
  }
  return age;
}

function validateAnswer(stepId: string, value: string, skipped = false): ValidationResult {
  const trimmed = value.trim();
  if (stepId === "name") {
    if (trimmed.length < 2) {
      return {
        valid: false,
        message: "Mysterious. Very spy-movie. But I need at least 2 letters for your profile."
      };
    }
    return { valid: true, response: `Nice to meet you, ${trimmed}.` };
  }

  if (stepId === "dob") {
    const age = ageFromDob(trimmed);
    if (!trimmed || age === null) {
      return { valid: false, message: "My calendar is squinting. Please enter your full date of birth." };
    }
    if (age < 18) {
      return { valid: false, message: "Ah, the math says no. Omiryn is for 18+ only." };
    }
    return { valid: true, response: "Got it. Birthday math survived." };
  }

  if (stepId === "location") {
    if (!trimmed.includes(",") || trimmed.length < 5) {
      return { valid: false, message: "I need city and state. Tiny map brain, very strict." };
    }
    return { valid: true, response: `${trimmed}. Pinned on the map.` };
  }

  if (stepId === "phone") {
    if (skipped || !trimmed) return { valid: true, response: "No phone for now. Totally fine." };
    if (!/^\+?[0-9\s-]{7,16}$/.test(trimmed)) {
      return { valid: false, message: "That phone number looks a little lost. Try country code, or skip." };
    }
    return { valid: true, response: "Saved. Very official." };
  }

  if (stepId === "photos") {
    return { valid: true, response: skipped ? "Skipping photos for now." : "Photo step noted." };
  }

  return { valid: true, response: "Noted." };
}

export function OnboardingChat() {
  const [stepIndex, setStepIndex] = useState(0);
  const [inputValue, setInputValue] = useState("");
  const [answers, setAnswers] = useState<Answers>({});
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "intro",
      role: "agent",
      text: onboardingSteps[0].question,
      hint: onboardingSteps[0].hint
    }
  ]);
  const step = onboardingSteps[stepIndex];
  const current = stepIndex + 1;
  const visibleMessages = messages.slice(-5);

  const profilePreview = useMemo<ProfilePreviewValues>(
    () => ({
      name: answers.name,
      dob: answers.dob,
      interested: answers.interested,
      location: answers.location,
      photos: answers.photos
    }),
    [answers]
  );

  function moveToNext(nextAnswers: Answers, extraMessages: Message[]) {
    const nextIndex = stepIndex + 1;
    if (nextIndex >= onboardingSteps.length) {
      setMessages([
        ...extraMessages,
        {
          id: `done-${Date.now()}`,
          role: "agent",
          text: "That’s the tiny setup done. We can start matching smarter now."
        }
      ]);
      setAnswers(nextAnswers);
      setInputValue("");
      return;
    }

    const nextStep = onboardingSteps[nextIndex];
    setStepIndex(nextIndex);
    setAnswers(nextAnswers);
    setInputValue("");
    setMessages([
      ...extraMessages,
      {
        id: `${nextStep.id}-${Date.now()}`,
        role: "agent",
        text: nextStep.question,
        hint: nextStep.hint
      }
    ]);
  }

  function submitAnswer(value = inputValue, label = value, skipped = false) {
    const displayValue = skipped ? "Skip" : label.trim();
    if (!displayValue) return;

    const baseMessages = [
      ...messages,
      {
        id: `user-${Date.now()}`,
        role: "user" as const,
        text: displayValue
      }
    ];
    const result = validateAnswer(step.id, value, skipped);

    if (!result.valid) {
      setMessages([
        ...baseMessages,
        {
          id: `error-${Date.now()}`,
          role: "agent",
          text: result.message,
          hint: step.hint
        }
      ]);
      setInputValue("");
      return;
    }

    const nextAnswers = {
      ...answers,
      [step.id]: skipped ? "" : displayValue
    };
    const successMessages = [
      ...baseMessages,
      {
        id: `success-${Date.now()}`,
        role: "agent" as const,
        text: result.response
      }
    ];
    moveToNext(nextAnswers, successMessages);
  }

  return (
    <main className="onboarding-page">
      <header className="onboarding-topbar">
        <OmirynLogo />
        <ProgressPill current={current} total={onboardingSteps.length} />
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
            {visibleMessages.map((message) => (
              <ChatBubble key={message.id} role={message.role} hint={message.hint}>
                {message.text}
              </ChatBubble>
            ))}
          </div>

          {step.type === "choice" ? (
            <div className="choice-composer">
              {step.choices?.map((choice) => (
                <button
                  key={choice.value}
                  type="button"
                  onClick={() => submitAnswer(choice.value, choice.label)}
                >
                  {choice.label}
                </button>
              ))}
            </div>
          ) : step.type === "photo" ? (
            <div className="choice-composer photo-actions">
              <button type="button" onClick={() => submitAnswer("photo", "Add photo")}>
                Add photo
              </button>
              <button type="button" onClick={() => submitAnswer("", "Skip", true)}>
                Skip
              </button>
            </div>
          ) : (
            <ChatComposer
              type={step.type === "date" ? "date" : "text"}
              placeholder={step.placeholder}
              value={inputValue}
              optional={step.optional}
              onChange={setInputValue}
              onSubmit={() => submitAnswer()}
              onSkip={() => submitAnswer("", "Skip", true)}
            />
          )}
        </section>

        <ProfilePreview values={profilePreview} />
      </section>
    </main>
  );
}
