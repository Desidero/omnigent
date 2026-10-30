import { parseItemCommentMessage } from "@/lib/itemComments";
import { readComposerDraft, serializeReplyDraft, type StoredReplyDraft } from "@/lib/replyDraft";
import type { SessionStatus } from "@/lib/types";
import type { QueuedMessage } from "@/store/chatStore";

// Preserve FIFO even with always-steer enabled or a transient idle status.
// Waiting on background work is idle for sending; native side chats bypass the queue.
// A first message still held for startup can't be steered, so later sends queue behind it.
export function shouldQueueSend(
  conversationId: string | null,
  status: "idle" | "streaming",
  sessionStatus: SessionStatus,
  queuedMessages: QueuedMessage[],
  alwaysSteer = false,
  opensSideChat = false,
  holdsFirstMessage = false,
): boolean {
  if (conversationId === null) return false;
  if (holdsFirstMessage) return true;
  if (opensSideChat) return false;
  const hasQueued = queuedMessages.some((m) => m.conversationId === conversationId);
  if (alwaysSteer) return hasQueued;
  const isBusy = status === "streaming" || sessionStatus === "running";
  return isBusy || hasQueued;
}

/** What decides whether queued messages may be combined. */
export interface CombineQueueOptions {
  /** The harness's skill prefix (`skillInvocationPrefix`); `$` on Codex. */
  skillPrefix?: "/" | "$";
}

/**
 * Whether a queued message has to be sent on its own: a `!` shell command, a
 * `/`-led command, skill or path (the harness reads the first text), a failed
 * send that may already be on the server, or an item-comment message, whose
 * comment tracking matches the exact text it was sent with.
 */
export function keepsQueuedMessageSeparate(
  message: QueuedMessage,
  { skillPrefix = "/" }: CombineQueueOptions = {},
): boolean {
  const lead = message.text.trimStart();
  return (
    lead.startsWith("!") ||
    lead.startsWith("/") ||
    lead.startsWith(skillPrefix) ||
    message.command !== undefined ||
    message.requiresRetry === true ||
    parseItemCommentMessage(message.text) !== null
  );
}

function joinWithBlankLine(before: string, after: string): string {
  return before !== "" && after !== "" ? `${before}\n\n${after}` : before || after;
}

/** The reply quotes of `messages` as one draft, when it still reproduces `text`. */
function combinedReplyDraft(
  messages: readonly QueuedMessage[],
  text: string,
): StoredReplyDraft | undefined {
  const quotes: StoredReplyDraft["quotes"] = [];
  let tail = "";
  for (const message of messages) {
    const draft = readComposerDraft(message)?.replyDraft;
    if (draft === undefined) {
      tail = joinWithBlankLine(tail, message.text);
      continue;
    }
    draft.quotes.forEach((quote, index) => {
      quotes.push(
        index === 0 ? { ...quote, before: joinWithBlankLine(tail, quote.before) } : quote,
      );
    });
    tail = draft.text;
  }
  if (quotes.length === 0) return undefined;
  const combined: StoredReplyDraft = { version: 1, quotes, text: tail };
  return serializeReplyDraft(combined) === text ? combined : undefined;
}

function mergeQueuedRun(run: readonly QueuedMessage[]): QueuedMessage {
  const [first] = run;
  if (run.length === 1) return first!;
  const withText = run.filter((message) => message.text.trim() !== "");
  const text = withText.map((message) => message.text).join("\n\n");
  const files = run.flatMap((message) => message.files ?? []);
  const replyDraft = combinedReplyDraft(withText, text);
  // No stableId: the combined text is a new submission and needs a new one.
  return {
    queueId: first!.queueId,
    text,
    conversationId: first!.conversationId,
    ...(first!.agentId !== undefined ? { agentId: first!.agentId } : {}),
    ...(files.length > 0 ? { files } : {}),
    ...(replyDraft ? { replyDraft } : {}),
    ...(run.some((message) => message.waitingForHost) ? { waitingForHost: true } : {}),
  };
}

/**
 * One conversation's queue with each run of adjacent combinable messages
 * merged into one: texts joined by a blank line, attachments concatenated, in
 * queue order. The merged message takes its run's first `queueId` and place.
 * Messages that stay separate keep their place and end a run, so nothing moves
 * across a command; a change of agent ends a run too.
 */
export function combinedQueue(
  messages: readonly QueuedMessage[],
  options: CombineQueueOptions = {},
): QueuedMessage[] {
  const combined: QueuedMessage[] = [];
  let run: QueuedMessage[] = [];
  const endRun = () => {
    if (run.length > 0) combined.push(mergeQueuedRun(run));
    run = [];
  };
  for (const message of messages) {
    if (keepsQueuedMessageSeparate(message, options)) {
      endRun();
      combined.push(message);
      continue;
    }
    const runStart = run[0];
    if (
      runStart !== undefined &&
      (runStart.agentId !== message.agentId || runStart.conversationId !== message.conversationId)
    ) {
      endRun();
    }
    run.push(message);
  }
  endRun();
  return combined;
}

/** Whether combining would merge anything, i.e. two adjacent messages can combine. */
export function canCombineQueue(
  messages: readonly QueuedMessage[],
  options: CombineQueueOptions = {},
): boolean {
  return combinedQueue(messages, options).length < messages.length;
}
