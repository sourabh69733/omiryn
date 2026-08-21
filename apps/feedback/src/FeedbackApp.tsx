import {
  ArrowLeft,
  ArrowRight,
  Check,
  MessageCircleMore,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  UsersRound,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  getOrCreateClientToken,
  submitFeedback,
  type SubmissionMode,
} from "./feedbackApi";
import { getQuestionScreenClass } from "./firstQuestionTheme.js";
import { conceptInsertAfterQuestion, questions, type Question } from "./questionnaire";

type AnswerMap = Record<string, string[]>;
type Screen = { kind: "welcome" } | { kind: "question"; questionIndex: number } | { kind: "concept" };

const draftStorageKey = "omiryn-feedback-draft-v3";
const completedStorageKey = "omiryn-feedback-completed-v3";
const maxFeedbackLength = 250;
const maxOtherAnswerLength = 120;
const otherAnswerPrefix = "Other: ";
const surveyVersion = "2026-08-19-v4";
const omirynWebsiteUrl = "https://omiryn.com/";
const omirynInstagramUrl = "https://www.instagram.com/omiryn.ai/";

const conceptFrames = [
  {
    icon: MessageCircleMore,
    title: "Have a short private conversation",
    body: "Tell Omiryn what matters to you, at your own pace, instead of relying only on a short profile.",
  },
  {
    icon: Sparkles,
    title: "Review what Omiryn understood",
    body: "Check and correct the values, intentions, lifestyle, and communication preferences used for matching.",
  },
  {
    icon: UsersRound,
    title: "Receive a few explained introductions",
    body: "See a small number of relevant people and a clear explanation of why each connection may work.",
  },
  {
    icon: ShieldCheck,
    title: "Move forward only by mutual choice",
    body: "Both people approve before a conversation opens, and you control what remains private.",
  },
];

function buildScreens(): Screen[] {
  const screens: Screen[] = [{ kind: "welcome" }];
  questions.forEach((_question, questionIndex) => {
    screens.push({ kind: "question", questionIndex });
    if (questionIndex + 1 === conceptInsertAfterQuestion) screens.push({ kind: "concept" });
  });
  return screens;
}

const screens = buildScreens();

function readDraft(): { screenIndex: number; answers: AnswerMap } {
  try {
    const stored = window.localStorage.getItem(draftStorageKey);
    if (!stored) return { screenIndex: 0, answers: {} };
    const parsed = JSON.parse(stored) as { screenIndex?: number; answers?: AnswerMap };
    return {
      screenIndex: Math.min(Math.max(parsed.screenIndex ?? 0, 0), screens.length - 1),
      answers: parsed.answers ?? {},
    };
  } catch {
    return { screenIndex: 0, answers: {} };
  }
}

export function FeedbackApp() {
  const initialDraft = useMemo(readDraft, []);
  const responseId = useRef(crypto.randomUUID());
  const [screenIndex, setScreenIndex] = useState(initialDraft.screenIndex);
  const [answers, setAnswers] = useState<AnswerMap>(initialDraft.answers);
  const [completionMode, setCompletionMode] = useState<SubmissionMode | null>(() => {
    const stored = window.localStorage.getItem(completedStorageKey);
    return stored === "submitted" || stored === "preview" ? stored : null;
  });
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [website, setWebsite] = useState("");

  useEffect(() => {
    if (completionMode) return;
    window.localStorage.setItem(draftStorageKey, JSON.stringify({ screenIndex, answers }));
  }, [answers, completionMode, screenIndex]);

  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "instant" });
  }, [screenIndex]);

  const currentScreen = screens[screenIndex];

  const moveForward = () => setScreenIndex((current) => Math.min(current + 1, screens.length - 1));
  const moveBack = () => setScreenIndex((current) => Math.max(current - 1, 0));

  const submit = async () => {
    setSubmitting(true);
    setSubmitError("");
    try {
      const mode = await submitFeedback({
        responseId: responseId.current,
        surveyVersion,
        clientToken: getOrCreateClientToken(),
        answers,
        website,
      });
      window.localStorage.setItem(completedStorageKey, mode);
      window.localStorage.removeItem(draftStorageKey);
      setCompletionMode(mode);
    } catch {
      setSubmitError("We couldn't confirm your response was saved. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  const restart = () => {
    window.localStorage.removeItem(completedStorageKey);
    window.localStorage.removeItem(draftStorageKey);
    responseId.current = crypto.randomUUID();
    setAnswers({});
    setWebsite("");
    setSubmitError("");
    setScreenIndex(0);
    setCompletionMode(null);
  };

  if (completionMode) return <CompletionScreen mode={completionMode} onRestart={restart} />;

  return (
    <div className="feedback-app">
      <Header />
      <main
        className={`feedback-main${
          currentScreen.kind === "question" && currentScreen.questionIndex === 0
            ? " feedback-main--playground"
            : ""
        }`}
      >
        <div className="screen-transition" key={`${currentScreen.kind}-${screenIndex}`}>
          {currentScreen.kind === "welcome" ? (
            <WelcomeScreen onBegin={moveForward} />
          ) : currentScreen.kind === "concept" ? (
            <ConceptScreen onBack={moveBack} onContinue={moveForward} />
          ) : (
            <QuestionScreen
              question={questions[currentScreen.questionIndex]}
              questionIndex={currentScreen.questionIndex}
              answers={answers}
              onAnswersChange={setAnswers}
              onBack={moveBack}
              onContinue={
                currentScreen.questionIndex === questions.length - 1 ? submit : moveForward
              }
              submitting={submitting}
              submitError={submitError}
            />
          )}
        </div>
      </main>
      <div className="feedback-trap" aria-hidden="true">
        <label htmlFor="feedback-website">Website</label>
        <input
          id="feedback-website"
          name="website"
          type="text"
          tabIndex={-1}
          autoComplete="off"
          value={website}
          onChange={(event) => setWebsite(event.target.value)}
        />
      </div>
    </div>
  );
}

function Header() {
  return (
    <header className="feedback-header">
      <img src="/assets/omiryn-logo.png" alt="Omiryn" className="brand-logo" />
      <span className="header-note">Discovery</span>
    </header>
  );
}

function WelcomeScreen({ onBegin }: { onBegin: () => void }) {
  return (
    <section className="welcome-screen">
      <div className="welcome-copy">
        <p className="eyebrow">A tiny discovery session</p>
        <h1>How could finding the right person feel easier?</h1>
        <p className="lead">
          Eight quick questions about compatibility, meaningful connections, and what technology
          could improve.
        </p>
      </div>
      <div className="welcome-footer">
        <button className="primary-button welcome-button" type="button" onClick={onBegin}>
          Begin
          <ArrowRight aria-hidden="true" />
        </button>
        <div className="welcome-meta" aria-label="Survey details">
          <span>About 2 minutes</span>
          <span aria-hidden="true">·</span>
          <span>Your answers stay anonymous</span>
          <span aria-hidden="true">·</span>
          <span>For adults 18+</span>
        </div>
      </div>
    </section>
  );
}

function QuestionScreen({
  question,
  questionIndex,
  answers,
  onAnswersChange,
  onBack,
  onContinue,
  submitting,
  submitError,
}: {
  question: Question;
  questionIndex: number;
  answers: AnswerMap;
  onAnswersChange: (answers: AnswerMap) => void;
  onBack: () => void;
  onContinue: () => void | Promise<void>;
  submitting: boolean;
  submitError: string;
}) {
  const selected = answers[question.id] ?? [];
  const isText = question.type === "text";
  const otherAnswer = selected.find((value) => value.startsWith(otherAnswerPrefix));
  const otherText = otherAnswer?.slice(otherAnswerPrefix.length) ?? "";
  const canContinue = isText || selected.length > 0;

  const toggleOption = (option: string) => {
    if (question.type === "single") {
      onAnswersChange({ ...answers, [question.id]: [option] });
      return;
    }

    const isSelected = selected.includes(option);
    if (isSelected) {
      onAnswersChange({ ...answers, [question.id]: selected.filter((value) => value !== option) });
      return;
    }
    if (question.exclusiveOptions?.includes(option)) {
      onAnswersChange({ ...answers, [question.id]: [option] });
      return;
    }
    if (selected.length < (question.maxChoices ?? Number.POSITIVE_INFINITY)) {
      const withoutExclusiveOptions = selected.filter(
        (value) => !question.exclusiveOptions?.includes(value),
      );
      onAnswersChange({ ...answers, [question.id]: [...withoutExclusiveOptions, option] });
    }
  };

  const setText = (value: string) => {
    onAnswersChange({ ...answers, [question.id]: [value.slice(0, maxFeedbackLength)] });
  };

  const setOtherText = (value: string) => {
    const boundedValue = value.slice(0, maxOtherAnswerLength);
    const withoutOther = selected.filter((answer) => !answer.startsWith(otherAnswerPrefix));
    if (!boundedValue.trim()) {
      onAnswersChange({ ...answers, [question.id]: withoutOther });
      return;
    }

    // A typed answer behaves like any other non-exclusive selection.
    const withoutExclusiveOptions = withoutOther.filter(
      (answer) => !question.exclusiveOptions?.includes(answer),
    );
    onAnswersChange({
      ...answers,
      [question.id]: [...withoutExclusiveOptions, `${otherAnswerPrefix}${boundedValue}`],
    });
  };

  return (
    <section className={getQuestionScreenClass(questionIndex)}>
      <QuestionProgress current={questionIndex + 1} />
      <div className="question-heading">
        <p className="eyebrow">{question.eyebrow}</p>
        <h1>{question.title}</h1>
        <p>{question.description}</p>
      </div>

      {isText ? (
        <div className="text-response">
          <textarea
            autoFocus
            aria-label={question.title}
            maxLength={maxFeedbackLength}
            placeholder="For this to work, Omiryn should..."
            value={selected[0] ?? ""}
            onChange={(event) => setText(event.target.value)}
          />
          <span>{selected[0]?.length ?? 0} / {maxFeedbackLength}</span>
        </div>
      ) : (
        <div className="option-list" role="group" aria-label={question.title}>
          {question.options?.map((option) => {
            const isSelected = selected.includes(option);
            const atLimit =
              question.type === "multiple" &&
              !isSelected &&
              selected.length >= (question.maxChoices ?? Number.POSITIVE_INFINITY);
            return (
              <button
                key={option}
                type="button"
                className={`option-row${isSelected ? " is-selected" : ""}`}
                aria-pressed={isSelected}
                disabled={atLimit}
                onClick={() => toggleOption(option)}
              >
                <span>{option}</span>
                <span className="selection-mark" aria-hidden="true">
                  {isSelected ? <Check /> : null}
                </span>
              </button>
            );
          })}
          {question.allowOther ? (
            <label className={`option-row option-row-other${otherText ? " is-selected" : ""}`}>
              <input
                type="text"
                maxLength={maxOtherAnswerLength}
                aria-label="Other answer"
                placeholder={question.otherPlaceholder ?? "Other - type your answer"}
                value={otherText}
                onChange={(event) => setOtherText(event.target.value)}
              />
              <span className="selection-mark" aria-hidden="true">
                {otherText ? <Check /> : null}
              </span>
            </label>
          ) : null}
        </div>
      )}

      {submitError ? <p className="submission-error" role="alert">{submitError}</p> : null}

      <Navigation
        onBack={onBack}
        onContinue={onContinue}
        continueDisabled={!canContinue || submitting}
        continueLabel={questionIndex === questions.length - 1 ? "Send feedback" : "Continue"}
        busy={submitting}
      />
    </section>
  );
}

function QuestionProgress({ current }: { current: number }) {
  const progress = `${(current / questions.length) * 100}%`;
  return (
    <div className="question-progress" aria-label={`Question ${current} of ${questions.length}`}>
      <div className="progress-copy">
        <span>{current} of {questions.length}</span>
        <span>{current === questions.length ? "Last one" : "Your perspective"}</span>
      </div>
      <div className="progress-track" aria-hidden="true">
        <span style={{ width: progress }} />
      </div>
    </div>
  );
}

function ConceptScreen({
  onBack,
  onContinue,
}: {
  onBack: () => void;
  onContinue: () => void | Promise<void>;
}) {
  const [frame, setFrame] = useState(0);
  const CurrentIcon = conceptFrames[frame].icon;

  return (
    <section className="concept-screen">
      <div className="concept-copy">
        <p className="eyebrow">Meet Omiryn</p>
        <h1>A more thoughtful introduction</h1>
        <p className="lead">
          Have a short private conversation, review what Omiryn understood, then receive a small
          number of explained introductions. A conversation opens only after mutual approval.
        </p>
      </div>

      <div className="story-inline" aria-label="How Omiryn works">
        <div className="story-steps" role="group" aria-label="Choose a slide">
          {conceptFrames.map((_item, index) => (
            <button
              key={index}
              className={index === frame ? "is-active" : ""}
              type="button"
              aria-label={`Show slide ${index + 1}`}
              aria-current={index === frame ? "step" : undefined}
              onClick={() => setFrame(index)}
            />
          ))}
        </div>

        <div className="story-content" key={frame}>
          <span className="story-icon"><CurrentIcon aria-hidden="true" /></span>
          <p className="eyebrow">{frame + 1} of {conceptFrames.length}</p>
          <h2>{conceptFrames[frame].title}</h2>
          <p>{conceptFrames[frame].body}</p>
        </div>

        <div className="story-controls">
          <button
            className="icon-button"
            type="button"
            disabled={frame === 0}
            onClick={() => setFrame((current) => Math.max(0, current - 1))}
            aria-label="Previous slide"
            title="Previous slide"
          >
            <ArrowLeft aria-hidden="true" />
          </button>
          <button
            className="icon-button"
            type="button"
            disabled={frame === conceptFrames.length - 1}
            onClick={() => setFrame((current) => Math.min(conceptFrames.length - 1, current + 1))}
            aria-label="Next slide"
            title="Next slide"
          >
            <ArrowRight aria-hidden="true" />
          </button>
        </div>
      </div>

      <div className="concept-links" aria-label="Omiryn links">
        <a href={omirynInstagramUrl} target="_blank" rel="noreferrer">
          <img
            className="social-link-icon"
            src="/assets/instagram-color.png"
            alt=""
            aria-hidden="true"
          />
          Instagram
        </a>
        <a href={omirynWebsiteUrl} target="_blank" rel="noreferrer">
          <img
            className="website-link-logo"
            src="/assets/omiryn-logo-neon-light.png"
            alt=""
            aria-hidden="true"
          />
          Website
        </a>
      </div>

      <Navigation
        onBack={onBack}
        onContinue={onContinue}
        continueDisabled={false}
        continueLabel="Continue"
      />
    </section>
  );
}

function Navigation({
  onBack,
  onContinue,
  continueDisabled,
  continueLabel,
  busy = false,
}: {
  onBack: () => void;
  onContinue: () => void;
  continueDisabled: boolean;
  continueLabel: string;
  busy?: boolean;
}) {
  return (
    <div className="navigation-row">
      <button className="icon-button" type="button" onClick={onBack} aria-label="Go back">
        <ArrowLeft aria-hidden="true" />
      </button>
      <button
        className="primary-button"
        type="button"
        disabled={continueDisabled}
        onClick={onContinue}
      >
        {busy ? "Saving..." : continueLabel}
        {!busy ? <ArrowRight aria-hidden="true" /> : null}
      </button>
    </div>
  );
}

function CompletionScreen({
  mode,
  onRestart,
}: {
  mode: SubmissionMode;
  onRestart: () => void;
}) {
  return (
    <div className="feedback-app completion-layout">
      <Header />
      <main className="completion-screen">
        <span className="completion-mark"><Check aria-hidden="true" /></span>
        <p className="eyebrow">That was genuinely useful</p>
        <h1>Thank you for helping shape Omiryn.</h1>
        <p className="lead">
          Honest doubts and unexpected ideas are exactly what make an early concept stronger.
        </p>
        <button className="secondary-button" type="button" onClick={onRestart}>
          <RotateCcw aria-hidden="true" />
          Start again
        </button>
        {mode === "preview" ? (
          <p className="mock-note">UI preview: this response is currently saved only in this browser.</p>
        ) : null}
      </main>
    </div>
  );
}
