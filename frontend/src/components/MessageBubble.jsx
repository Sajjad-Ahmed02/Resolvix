import { BrandMark } from "./icons";
import { formatMessageTime } from "../utils/date";

function MessageBubble({ message }) {
  const isUser = message.role === "user";
  const isTool = message.role === "tool";

  if (isTool) {
    return (
      <div className="flex items-center gap-3" role="listitem">
        <span className="h-px flex-1 bg-stone-200" aria-hidden="true" />
        <p className="text-xs text-stone-500">{message.content}</p>
        <span className="h-px flex-1 bg-stone-200" aria-hidden="true" />
      </div>
    );
  }

  return (
    <div
      className={`flex gap-2.5 ${
        isUser ? "justify-end" : "justify-start"
      }`}
      role="listitem"
    >
      {!isUser ? (
        <BrandMark className="mt-5 h-7 w-7 shrink-0 text-[10px]" />
      ) : null}

      <div
        className={`flex max-w-[85%] flex-col sm:max-w-[75%] ${
          isUser ? "items-end" : "items-start"
        }`}
      >
        <div
          className={`mb-1 flex items-center gap-2 text-[11px] ${
            isUser ? "flex-row-reverse" : ""
          }`}
        >
          <span className="font-medium text-stone-500">
            {isUser ? "You" : "Resolvix Support"}
          </span>
          <span className="text-stone-500">
            {formatMessageTime(message.created_at)}
          </span>
        </div>

        <div
          className={`whitespace-pre-wrap break-words rounded-md px-3.5 py-2.5 text-sm leading-6 ${
            isUser
              ? "rounded-br-sm bg-stone-900 text-white"
              : "rounded-bl-sm bg-white text-stone-800 ring-1 ring-inset ring-stone-200"
          }`}
        >
          {message.content}
        </div>

        {message.metadata?.fallback ? (
          <span className="mt-1.5 text-[11px] text-stone-500">
            Automated reply unavailable. Please try again.
          </span>
        ) : null}
      </div>
    </div>
  );
}

export default MessageBubble;
