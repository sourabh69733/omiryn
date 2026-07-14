import { useEffect, useMemo, useRef, useState } from "react";
import { OmirynLogo } from "../brand/OmirynLogo";
import { ChatBubble } from "./ChatBubble";
import { ChatComposer } from "./ChatComposer";
import { ProfilePreview, type ProfilePreviewValues } from "./ProfilePreview";
import { onboardingSteps } from "./onboardingSteps";

type Message = {
  id: string;
  role: "agent" | "user";
  text: string;
  hint?: string;
  timestamp: string;
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

const wait = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));

function formatChatTime(date = new Date()) {
  return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function createMessage(role: "agent" | "user", text: string, hint?: string): Message {
  return {
    id: `${role}-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    role,
    text,
    hint,
    timestamp: formatChatTime()
  };
}

function normalizeDob(value: string) {
  const trimmed = value.trim();
  const slashMatch = /^(\d{1,2})\/(\d{1,2})\/(\d{4})$/.exec(trimmed);
  if (slashMatch) {
    const [, day, month, year] = slashMatch;
    return `${year}-${month.padStart(2, "0")}-${day.padStart(2, "0")}`;
  }
  return trimmed;
}

function ageFromDob(value: string) {
  const normalized = normalizeDob(value);
  const birthDate = new Date(`${normalized}T00:00:00`);
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
    return { valid: true, response: "Nice. Officially less mysterious." };
  }

  if (stepId === "dob") {
    const normalized = normalizeDob(trimmed);
    const age = ageFromDob(normalized);
    if (!trimmed || age === null) {
      return { valid: false, message: "My calendar is squinting. Please enter your full date of birth." };
    }
    if (age < 18) {
      return { valid: false, message: "Ah, the math says no. Omiryn is for 18+ only." };
    }
    return { valid: true, response: "Got it. Birthday math survived." };
  }

  if (stepId === "state") {
    if (trimmed.length < 2) {
      return { valid: false, message: "Give me the state first. Tiny map brain, very orderly." };
    }
    return { valid: true, response: "Noted." };
  }

  if (stepId === "city") {
    if (trimmed.length < 2) {
      return { valid: false, message: "City needs at least 2 letters so I can place you properly." };
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
  const [isBotTyping, setIsBotTyping] = useState(false);
  const conversationEndRef = useRef<HTMLDivElement | null>(null);
  const [messages, setMessages] = useState<Message[]>([
    createMessage("agent", onboardingSteps[0].question, onboardingSteps[0].hint)
  ]);
  const step = onboardingSteps[stepIndex];
  const visibleMessages = messages;

  useEffect(() => {
    conversationEndRef.current?.scrollIntoView({ block: "end" });
  }, [messages, isBotTyping, step.type]);

  useEffect(() => {
    const updateKeyboardOffset = () => {
      const viewport = window.visualViewport;
      const offset = viewport ? Math.max(0, window.innerHeight - viewport.height - viewport.offsetTop) : 0;
      document.documentElement.style.setProperty("--keyboard-offset", `${Math.round(offset)}px`);
    };

    updateKeyboardOffset();
    window.visualViewport?.addEventListener("resize", updateKeyboardOffset);
    window.visualViewport?.addEventListener("scroll", updateKeyboardOffset);
    window.addEventListener("resize", updateKeyboardOffset);

    return () => {
      window.visualViewport?.removeEventListener("resize", updateKeyboardOffset);
      window.visualViewport?.removeEventListener("scroll", updateKeyboardOffset);
      window.removeEventListener("resize", updateKeyboardOffset);
      document.documentElement.style.removeProperty("--keyboard-offset");
    };
  }, []);

  const profilePreview = useMemo<ProfilePreviewValues>(
    () => ({
      name: answers.name,
      dob: answers.dob,
      interested: answers.interested,
      location: [answers.city, answers.state].filter(Boolean).join(", "),
      photos: answers.photos
    }),
    [answers]
  );

  async function submitAnswer(value = inputValue, label = value, skipped = false) {
    if (isBotTyping) return;

    const displayValue = skipped ? "Skip" : label.trim();
    if (!displayValue) return;

    setMessages((currentMessages) => [...currentMessages, createMessage("user", displayValue)]);
    setInputValue("");

    const result = validateAnswer(step.id, value, skipped);
    setIsBotTyping(true);
    await wait(650);

    if (!result.valid) {
      setMessages((currentMessages) => [...currentMessages, createMessage("agent", result.message, step.hint)]);
      setIsBotTyping(false);
      return;
    }

    const nextAnswers = {
      ...answers,
      [step.id]: skipped ? "" : step.id === "dob" ? normalizeDob(value) : displayValue
    };
    setAnswers(nextAnswers);
    setMessages((currentMessages) => [...currentMessages, createMessage("agent", result.response)]);

    await wait(760);

    const nextIndex = stepIndex + 1;
    if (nextIndex >= onboardingSteps.length) {
      setMessages((currentMessages) => [
        ...currentMessages,
        createMessage("agent", "That’s the tiny setup done. We can start matching smarter now.")
      ]);
      setIsBotTyping(false);
      return;
    }

    const nextStep = onboardingSteps[nextIndex];
    setStepIndex(nextIndex);
    setMessages((currentMessages) => [...currentMessages, createMessage("agent", nextStep.question, nextStep.hint)]);
    setIsBotTyping(false);
  }

  return (
    <main className="onboarding-page">
      <header className="onboarding-topbar">
        <OmirynLogo />
      </header>

      <section className="onboarding-layout">
        <aside className="onboarding-copy">
          <h1>
            {/* Talk first. <span>Match better.</span> */}
          </h1>
          <p>Tiny setup, one question at a time.</p>
        </aside>

        <section className="conversation-panel" aria-label="Onboarding chat">
          <div className="conversation-heading">
            <h2>Onboarding chat</h2>
            <p>A tiny setup, then we match smarter.</p>
          </div>

          <div className={`chat-canvas ${visibleMessages.length <= 2 ? "is-intro" : "is-active"}`}>
            <span className="doodle question" aria-hidden="true">
              ?
            </span>
            <span className="doodle heart" aria-hidden="true">
              ♡
            </span>
            <span className="doodle check" aria-hidden="true" />
            {visibleMessages.map((message) => (
              <ChatBubble key={message.id} role={message.role} hint={message.hint} timestamp={message.timestamp}>
                {message.text}
              </ChatBubble>
            ))}

            {isBotTyping ? <ChatBubble role="agent" typing /> : null}

            {step.type === "choice" ? (
              <div className="choice-composer">
                {step.choices?.map((choice) => (
                  <button
                    key={choice.value}
                    className={`choice-option choice-${choice.value}`}
                    type="button"
                    disabled={isBotTyping}
                    onClick={() => submitAnswer(choice.value, choice.label)}
                  >
                    <span aria-hidden="true" />
                    {choice.label}
                  </button>
                ))}
              </div>
            ) : null}

            {step.type === "photo" ? (
              <div className="choice-composer photo-actions">
                <button type="button" disabled={isBotTyping} onClick={() => submitAnswer("photo", "Add photo")}>
                  Add photo
                </button>
                <button type="button" disabled={isBotTyping} onClick={() => submitAnswer("", "Skip", true)}>
                  Skip
                </button>
              </div>
            ) : null}
            <div className="conversation-end-spacer" ref={conversationEndRef} aria-hidden="true" />
          </div>

          {step.type === "choice" || step.type === "photo" ? (
            <div className="chat-composer chat-composer-disabled" aria-hidden="true">
              <span>Type a message...</span>
              <span>☺</span>
            </div>
          ) : (
            <ChatComposer
              type={step.type === "date" ? "date" : "text"}
              placeholder={step.placeholder}
              value={inputValue}
              optional={step.optional}
              disabled={isBotTyping}
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
