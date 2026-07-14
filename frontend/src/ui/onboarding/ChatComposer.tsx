import { SendHorizontal } from "lucide-react";

type ChatComposerProps = {
  placeholder?: string;
  type?: "text" | "date";
  value: string;
  optional?: boolean;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onSkip?: () => void;
};

export function ChatComposer({
  placeholder = "Type your answer",
  type = "text",
  value,
  optional = false,
  onChange,
  onSubmit,
  onSkip
}: ChatComposerProps) {
  return (
    <form
      className={`chat-composer ${optional ? "has-skip" : ""}`}
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <button className="emoji-button" type="button" aria-label="Add emoji">
        ☺
      </button>
      <input
        type={type}
        placeholder={placeholder}
        aria-label="Your answer"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
      {optional ? (
        <button className="skip-button" type="button" onClick={onSkip}>
          Skip
        </button>
      ) : null}
      <button className="send-button" type="submit" aria-label="Send answer">
        <SendHorizontal size={22} strokeWidth={2.4} />
      </button>
    </form>
  );
}
