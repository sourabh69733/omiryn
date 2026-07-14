import { SendHorizontal } from "lucide-react";

type ChatComposerProps = {
  placeholder?: string;
};

export function ChatComposer({ placeholder = "Type your answer" }: ChatComposerProps) {
  return (
    <form className="chat-composer">
      <button className="emoji-button" type="button" aria-label="Add emoji">
        ☺
      </button>
      <input placeholder={placeholder} aria-label="Your answer" />
      <button className="send-button" type="submit" aria-label="Send answer">
        <SendHorizontal size={22} strokeWidth={2.4} />
      </button>
    </form>
  );
}
