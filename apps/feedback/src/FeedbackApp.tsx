import {
  ArrowLeft,
  ArrowRight,
  Check,
  MessageCircleMore,
  Pause,
  Play,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  UsersRound,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { conceptInsertAfterQuestion, questions, type Question } from "./questionnaire";

type AnswerMap = Record<string, string[]>;
type Screen = { kind: "welcome" } | { kind: "question"; questionIndex: number } | { kind: "concept" };

const draftStorageKey = "omiryn-feedback-draft-v1";
const completedStorageKey = "omiryn-feedback-completed-v1";
const maxFeedbackLength = 250;

const conceptFrames = [
  {
    icon: MessageCircleMore,
    title: "Start with a real conversation",
    body: "Share what matters to you at your own pace, instead of reducing yourself to a short profile.",
  },
  {
    icon: Sparkles,
    title: "Look beyond surface-level signals",
    body: "Omiryn explores values, intentions, lifestyle, and communication preferences.",
  },
  {
    icon: UsersRound,
    title: "Meet fewer, more relevant people",
    body: "The aim is thoughtful introductions, with a clear reason why two people may connect.",
  },
  {
    icon: ShieldCheck,
    title: "Stay in control",
    body: "You decide what is used, what stays private, and whether an introduction moves forward.",
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
  const [screenIndex, setScreenIndex] = useState(initialDraft.screenIndex);
  const [answers, setAnswers] = useState<AnswerMap>(initialDraft.answers);
  const [submitted, setSubmitted] = useState(
    () => window.localStorage.getItem(completedStorageKey) === "true",
  );
  const [submitting, setSubmitting] = useState(false);
  const [showConceptStory, setShowConceptStory] = useState(false);

  useEffect(() => {
    if (submitted) return;
    window.localStorage.setItem(draftStorageKey, JSON.stringify({ screenIndex, answers }));
  }, [answers, screenIndex, submitted]);

  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "instant" });
  }, [screenIndex]);

  const currentScreen = screens[screenIndex];

  const moveForward = () => setScreenIndex((current) => Math.min(current + 1, screens.length - 1));
  const moveBack = () => setScreenIndex((current) => Math.max(current - 1, 0));

  const submit = () => {
    setSubmitting(true);
    // Phase one deliberately keeps submission local until the Google Sheet endpoint is connected.
    window.setTimeout(() => {
      window.localStorage.setItem(completedStorageKey, "true");
      window.localStorage.removeItem(draftStorageKey);
      setSubmitting(false);
      setSubmitted(true);
    }, 650);
  };

  const restart = () => {
    window.localStorage.removeItem(completedStorageKey);
    window.localStorage.removeItem(draftStorageKey);
    setAnswers({});
    setScreenIndex(0);
    setSubmitted(false);
  };

  if (submitted) return <CompletionScreen onRestart={restart} />;

  return (
    <div className="feedback-app">
      <Header />
      <main className="feedback-main">
        <div className="screen-transition" key={`${currentScreen.kind}-${screenIndex}`}>
          {currentScreen.kind === "welcome" ? (
            <WelcomeScreen onBegin={moveForward} />
          ) : currentScreen.kind === "concept" ? (
            <ConceptScreen
              onBack={moveBack}
              onContinue={moveForward}
              onWatch={() => setShowConceptStory(true)}
            />
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
            />
          )}
        </div>
      </main>
      {showConceptStory ? <ConceptStory onClose={() => setShowConceptStory(false)} /> : null}
    </div>
  );
}

function Header() {
  return (
    <header className="feedback-header">
      <img src="/assets/omiryn-logo.png" alt="Omiryn" className="brand-logo" />
      <span className="header-note">Thought experiment</span>
    </header>
  );
}

function WelcomeScreen({ onBegin }: { onBegin: () => void }) {
  return (
    <section className="welcome-screen">
      <div className="welcome-copy">
        <p className="eyebrow">A two-minute thought experiment</p>
        <h1>How could finding the right person feel easier?</h1>
        <p className="lead">
          Six quick prompts about compatibility, meaningful connections, and what technology
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
          <span>No dating-app experience needed</span>
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
}: {
  question: Question;
  questionIndex: number;
  answers: AnswerMap;
  onAnswersChange: (answers: AnswerMap) => void;
  onBack: () => void;
  onContinue: () => void;
  submitting: boolean;
}) {
  const selected = answers[question.id] ?? [];
  const isText = question.type === "text";
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
    if (selected.length < (question.maxChoices ?? Number.POSITIVE_INFINITY)) {
      onAnswersChange({ ...answers, [question.id]: [...selected, option] });
    }
  };

  const setText = (value: string) => {
    onAnswersChange({ ...answers, [question.id]: [value.slice(0, maxFeedbackLength)] });
  };

  return (
    <section className="question-screen">
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
        </div>
      )}

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
  onWatch,
}: {
  onBack: () => void;
  onContinue: () => void;
  onWatch: () => void;
}) {
  return (
    <section className="concept-screen">
      <div className="concept-copy">
        <p className="eyebrow">Meet Omiryn</p>
        <h1>A more thoughtful introduction</h1>
        <p className="lead">
          Omiryn explores how an AI-assisted guide could understand what matters to you and
          help identify potentially compatible people.
        </p>
      </div>

      <button className="concept-preview" type="button" onClick={onWatch}>
        <span className="conversation-visual" aria-hidden="true">
          <span className="bubble bubble-left"><i /><i /><i /></span>
          <span className="connection-line" />
          <span className="bubble bubble-right"><i /><i /><i /></span>
        </span>
        <span className="play-button"><Play fill="currentColor" /></span>
        <span className="preview-copy">
          <strong>Watch the 45-second idea</strong>
          <small>Optional · 4 quick scenes</small>
        </span>
      </button>

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

function ConceptStory({ onClose }: { onClose: () => void }) {
  const [frame, setFrame] = useState(0);
  const [playing, setPlaying] = useState(true);
  const CurrentIcon = conceptFrames[frame].icon;

  useEffect(() => {
    if (!playing) return undefined;
    const timer = window.setInterval(() => {
      setFrame((current) => {
        if (current === conceptFrames.length - 1) {
          setPlaying(false);
          return current;
        }
        return current + 1;
      });
    }, 8000);
    return () => window.clearInterval(timer);
  }, [playing]);

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [onClose]);

  return (
    <div className="story-backdrop" role="dialog" aria-modal="true" aria-label="Omiryn idea">
      <div className="story-dialog">
        <div className="story-toolbar">
          <div className="story-steps" aria-hidden="true">
            {conceptFrames.map((_item, index) => (
              <button
                key={index}
                className={index <= frame ? "is-active" : ""}
                type="button"
                aria-label={`Show scene ${index + 1}`}
                aria-current={index === frame ? "step" : undefined}
                onClick={() => setFrame(index)}
              />
            ))}
          </div>
          <button className="story-close" type="button" onClick={onClose} aria-label="Close idea">
            <X aria-hidden="true" />
          </button>
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
            onClick={() => setPlaying((current) => !current)}
            aria-label={playing ? "Pause" : "Play"}
          >
            {playing ? <Pause aria-hidden="true" /> : <Play aria-hidden="true" />}
          </button>
          <button
            className="primary-button"
            type="button"
            onClick={() => {
              if (frame < conceptFrames.length - 1) {
                setFrame((current) => current + 1);
              } else {
                onClose();
              }
            }}
          >
            {frame === conceptFrames.length - 1 ? "Back to questions" : "Next"}
            <ArrowRight aria-hidden="true" />
          </button>
        </div>
      </div>
    </div>
  );
}

function CompletionScreen({ onRestart }: { onRestart: () => void }) {
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
        <p className="mock-note">UI preview: this response is currently saved only in this browser.</p>
      </main>
    </div>
  );
}
