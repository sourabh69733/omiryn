import { CalendarDays, SendHorizontal } from "lucide-react";
import { useRef } from "react";

type ChatComposerProps = {
  placeholder?: string;
  type?: "text" | "date";
  value: string;
  optional?: boolean;
  disabled?: boolean;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onSkip?: () => void;
};

export function ChatComposer({
  placeholder = "Type your answer",
  type = "text",
  value,
  optional = false,
  disabled = false,
  onChange,
  onSubmit,
  onSkip
}: ChatComposerProps) {
  const isDate = type === "date";
  const dateInputRef = useRef<HTMLInputElement | null>(null);

  function openDatePicker() {
    const input = dateInputRef.current;
    if (!input || disabled) return;
    const pickerInput = input as HTMLInputElement & { showPicker?: () => void };
    if (pickerInput.showPicker) {
      pickerInput.showPicker();
      return;
    }
    input.click();
    input.focus();
  }

  return (
    <form
      className={`chat-composer ${optional ? "has-skip" : ""} ${isDate ? "is-date" : ""}`}
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <button className="emoji-button" type="button" aria-label="Add emoji" disabled={disabled}>
        ☺
      </button>
      <input
        type="text"
        inputMode={isDate ? "numeric" : "text"}
        placeholder={isDate ? "YYYY-MM-DD" : placeholder}
        aria-label="Your answer"
        autoComplete={isDate ? "bday" : "off"}
        disabled={disabled}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
      {isDate ? (
        <>
          <button className="date-picker-button" type="button" aria-label="Open date picker" onClick={openDatePicker}>
            <CalendarDays size={21} strokeWidth={2.1} />
          </button>
          <input
            ref={dateInputRef}
            className="native-date-input"
            type="date"
            tabIndex={-1}
            aria-hidden="true"
            disabled={disabled}
            value={/^\d{4}-\d{2}-\d{2}$/.test(value) ? value : ""}
            onChange={(event) => onChange(event.target.value)}
          />
        </>
      ) : null}
      {optional ? (
        <button className="skip-button" type="button" disabled={disabled} onClick={onSkip}>
          Skip
        </button>
      ) : null}
      <button className="send-button" type="submit" aria-label="Send answer" disabled={disabled}>
        <SendHorizontal size={22} strokeWidth={2.4} />
      </button>
    </form>
  );
}
