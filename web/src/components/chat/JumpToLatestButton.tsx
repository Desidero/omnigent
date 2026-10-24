import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ArrowDownIcon } from "lucide-react";
import { useStickToBottomContext } from "use-stick-to-bottom";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { Bubble } from "@/lib/renderItems";
import { bubbleKey, isSystemBubble } from "@/components/chat/chatBubbleParts";

/**
 * One key per message a reader scrolled up can miss: each real user turn and
 * each assistant response, however many bubbles the pipeline split it into.
 */
export function transcriptMessageKeys(bubbles: readonly Bubble[]): string[] {
  const keys: string[] = [];
  for (const bubble of bubbles) {
    if (bubble.kind === "user") {
      if (!isSystemBubble(bubble)) keys.push(bubbleKey(bubble));
    } else if (bubble.kind === "assistant") {
      const key = `assistant:${bubble.responseId}`;
      if (keys.at(-1) !== key) keys.push(key);
    }
  }
  return keys;
}

/**
 * The newest message that is complete: a reply still streaming when the reader
 * scrolls away is not something they have read, so it stays countable.
 */
export function lastSettledMessageKey(bubbles: readonly Bubble[]): string | null {
  for (let i = bubbles.length - 1; i >= 0; i--) {
    const bubble = bubbles[i]!;
    if (bubble.kind === "user") {
      if (!isSystemBubble(bubble)) return bubbleKey(bubble);
    } else if (bubble.kind === "assistant" && bubble.lifecycle !== "streaming") {
      return `assistant:${bubble.responseId}`;
    }
  }
  return null;
}

/**
 * Distinct messages after the last one the reader saw at the bottom. Older
 * history landing above counts for nothing. `null` when `lastSeenKey` is no
 * longer in the list (a conversation switch or a reload replaced it), so the
 * caller re-baselines instead of reporting everything as new.
 */
export function countNewMessages(
  keys: readonly string[],
  lastSeenKey: string | null,
): number | null {
  if (lastSeenKey === null) return keys.length;
  const seenIndex = keys.lastIndexOf(lastSeenKey);
  if (seenIndex < 0) return null;
  return new Set(keys.slice(seenIndex + 1)).size;
}

export interface JumpToLatestLabel {
  text: string;
  ariaLabel: string;
  /** New content landed below the reader: use the attention treatment. */
  attention: boolean;
}

/** Pill wording for what arrived while the reader was away. */
export function jumpToLatestLabel({
  newCount,
  streaming,
}: {
  newCount: number;
  streaming: boolean;
}): JumpToLatestLabel {
  if (newCount > 1) {
    const text = `${newCount} new messages`;
    return { text, ariaLabel: `${text}, jump to the latest message`, attention: true };
  }
  if (streaming) {
    return { text: "New reply", ariaLabel: "New reply streaming, jump to it", attention: true };
  }
  if (newCount === 1) {
    return { text: "1 new message", ariaLabel: "1 new message, jump to it", attention: true };
  }
  return { text: "Jump to latest", ariaLabel: "Jump to the latest message", attention: false };
}

/** How long the reader must be away from the bottom before the pill shows, so
 *  the mount pin, a deep-link scroll or a momentum bounce never flash it. */
export const JUMP_TO_LATEST_SETTLE_MS = 300;

/**
 * Bottom-edge pill for a reader who scrolled away from the live end: "Jump to
 * latest", or what landed below them meanwhile ("New reply", "N new
 * messages"). Clicking scrolls to the bottom and re-engages follow-tail.
 *
 * Rendered inside `<Conversation>` for the StickToBottom context, but mounted
 * through a portal into the conversation wrapper: the scroll container carries
 * the fade mask, which would also fade the pill.
 *
 * @param containerEl - The conversation wrapper the pill is mounted into.
 * @param bubbles - The rendered bubbles, for the new-message count.
 * @param streaming - A reply is being produced right now.
 */
export function JumpToLatestButton({
  containerEl,
  bubbles,
  streaming,
}: {
  containerEl: HTMLElement | null;
  bubbles: readonly Bubble[];
  streaming: boolean;
}) {
  const { isAtBottom, scrollToBottom, state } = useStickToBottomContext();

  // The last complete message seen at the bottom; frozen while away.
  const lastSeenKeyRef = useRef<string | null>(null);
  const keys = useMemo(() => transcriptMessageKeys(bubbles), [bubbles]);
  let newCount = countNewMessages(keys, lastSeenKeyRef.current);
  if (isAtBottom || newCount === null) {
    lastSeenKeyRef.current = lastSettledMessageKey(bubbles);
    newCount = countNewMessages(keys, lastSeenKeyRef.current);
  }

  const [settledAway, setSettledAway] = useState(false);
  useEffect(() => {
    if (isAtBottom) {
      setSettledAway(false);
      return;
    }
    const timer = setTimeout(() => setSettledAway(true), JUMP_TO_LATEST_SETTLE_MS);
    return () => clearTimeout(timer);
  }, [isAtBottom]);
  const visible = settledAway && !isAtBottom;

  const jumpToLatest = useCallback(() => {
    // Re-arm follow-tail explicitly: the library's scrollToBottom leaves
    // `escapedFromLock` as the reader's wheel-up set it.
    state.escapedFromLock = false;
    void scrollToBottom("instant");
    // Rows below mount as the scroll lands; pin again once they are measured.
    requestAnimationFrame(() => void scrollToBottom("instant"));
  }, [scrollToBottom, state]);

  if (!containerEl) return null;
  const label = jumpToLatestLabel({ newCount: newCount ?? 0, streaming });
  return createPortal(
    <div
      // Centered on the bottom edge, just above the composer, clear of the
      // 32px scroll fade. z-40 matches the Jump-to-top pill.
      className={cn(
        "pointer-events-none absolute inset-x-0 bottom-3 z-40 flex justify-center transition-opacity duration-150",
        visible ? "opacity-100" : "opacity-0",
      )}
    >
      <Button
        type="button"
        variant={label.attention ? "default" : "outline"}
        size="sm"
        onClick={jumpToLatest}
        aria-label={label.ariaLabel}
        componentId="chat.nav.jump_to_latest"
        data-testid="jump-to-latest"
        data-state={label.attention ? "new" : "idle"}
        // When hidden keep the button out of the tab order and a11y tree.
        tabIndex={visible ? 0 : -1}
        aria-hidden={!visible}
        className={cn(
          "h-7 gap-1.5 rounded-full px-3 text-sm shadow-sm",
          // The outline hover is a translucent wash; keep the fill opaque over
          // the faded chat text behind the pill.
          !label.attention && "bg-background hover:bg-background hover:brightness-95",
          !label.attention &&
            "dark:bg-background dark:hover:bg-background dark:hover:brightness-125",
          visible ? "pointer-events-auto" : "pointer-events-none",
        )}
      >
        <ArrowDownIcon className="size-3.5" aria-hidden />
        {label.text}
      </Button>
    </div>,
    containerEl,
  );
}
