import { describe, expect, it } from "vitest";
import { buildItemCommentMessage } from "@/lib/itemComments";
import { readComposerDraft, serializeReplyDraft, type StoredReplyDraft } from "@/lib/replyDraft";
import type { QueuedMessage } from "@/store/chatStore";
import {
  canCombineQueue,
  combinedQueue,
  keepsQueuedMessageSeparate,
  shouldQueueSend,
} from "./messageQueue";

describe("shouldQueueSend", () => {
  const q = (conversationId: string): QueuedMessage => ({
    queueId: `q_${conversationId}`,
    text: "queued",
    conversationId,
  });

  it("sends directly (no queue) for a brand-new chat with no conversation", () => {
    expect(shouldQueueSend(null, "streaming", "running", [])).toBe(false);
  });

  it("queues while the session is busy (streaming or running)", () => {
    expect(shouldQueueSend("conv_a", "streaming", "idle", [])).toBe(true);
    expect(shouldQueueSend("conv_a", "idle", "running", [])).toBe(true);
  });

  it("sends directly when idle and nothing is queued for this conversation", () => {
    expect(shouldQueueSend("conv_a", "idle", "idle", [])).toBe(false);
  });

  it("sends directly on `waiting` (turn ended, only background work remains)", () => {
    // A background shell / still-running sub-agent keeps the session in
    // `waiting`, but the server's turn gate is already free — a new message
    // must start a fresh turn rather than stalling in the client queue.
    expect(shouldQueueSend("conv_a", "idle", "waiting", [])).toBe(false);
  });

  it("queues when idle but this conversation already has a queued message", () => {
    // The ordering fix: an idle flicker must not let a later send overtake the
    // still-queued earlier one.
    expect(shouldQueueSend("conv_a", "idle", "idle", [q("conv_a")])).toBe(true);
  });

  it("ignores queued messages belonging to a different conversation", () => {
    expect(shouldQueueSend("conv_a", "idle", "idle", [q("conv_b")])).toBe(false);
  });

  it("sends directly while busy when alwaysSteer is on", () => {
    // The whole point of the preference: a mid-turn follow-up is POSTed now
    // (steered) instead of parking in the queue strip.
    expect(shouldQueueSend("conv_a", "streaming", "idle", [], true)).toBe(false);
    expect(shouldQueueSend("conv_a", "idle", "running", [], true)).toBe(false);
  });

  it("still queues under alwaysSteer when this conversation has a queued message", () => {
    // The ordering guard outranks always-steer: draining must stay in order, so
    // a direct send can't overtake a still-queued earlier one.
    expect(shouldQueueSend("conv_a", "streaming", "running", [q("conv_a")], true)).toBe(true);
  });

  it("queues behind a first message still held for startup", () => {
    // The agent hasn't received it, so there is nothing to steer; a transient
    // idle edge during startup must not let a later send overtake it either.
    expect(shouldQueueSend("conv_a", "streaming", "idle", [], true, false, true)).toBe(true);
    expect(shouldQueueSend("conv_a", "idle", "idle", [], false, false, true)).toBe(true);
    // A native /side forks the agent's thread, which doesn't exist yet either.
    expect(shouldQueueSend("conv_a", "streaming", "idle", [], false, true, true)).toBe(true);
  });

  it("sends directly for a /side command even while busy or with a queued message", () => {
    // A codex /side forks its own side chat and is non-interrupting — it must
    // POST now while the parent turn runs, bypassing both the busy gate and the
    // main-thread ordering guard.
    expect(shouldQueueSend("conv_a", "streaming", "running", [], false, true)).toBe(false);
    expect(shouldQueueSend("conv_a", "idle", "idle", [q("conv_a")], false, true)).toBe(false);
  });
});

describe("combinedQueue", () => {
  const queued = (queueId: string, text: string, extra: Partial<QueuedMessage> = {}) =>
    ({ queueId, text, conversationId: "conv_a", stableId: `id_${queueId}`, ...extra }) as const;
  const file = (name: string) => new File(["x"], name, { type: "text/plain" });

  it("merges in queue order with a blank line, in the first message's place", () => {
    const [merged, ...rest] = combinedQueue([
      queued("q_1", "Use the account's zone."),
      queued("q_2", "Also store it per row."),
      queued("q_3", "Then rerun the export."),
    ]);
    expect(rest).toEqual([]);
    expect(merged).toMatchObject({
      queueId: "q_1",
      conversationId: "conv_a",
      text: "Use the account's zone.\n\nAlso store it per row.\n\nThen rerun the export.",
    });
    // A new submission: the store gives it a fresh idempotency id.
    expect(merged!.stableId).toBeUndefined();
  });

  it("concatenates attachments and skips empty texts in the join", () => {
    const [a, b, c] = [file("a.txt"), file("b.png"), file("c.csv")];
    const [merged] = combinedQueue([
      queued("q_1", "Compare these", { files: [a!] }),
      queued("q_2", "  ", { files: [b!, c!] }),
      queued("q_3", "and summarize"),
    ]);
    expect(merged!.text).toBe("Compare these\n\nand summarize");
    expect(merged!.files).toEqual([a, b, c]);
  });

  it("keeps ! and / messages separate and in place, merging only runs between them", () => {
    const result = combinedQueue([
      queued("q_1", "first"),
      queued("q_2", "second"),
      queued("q_3", "!git status"),
      queued("q_4", "third"),
      queued("q_5", "  /compact", { command: "compact" }),
      queued("q_6", "fourth"),
      queued("q_7", "fifth"),
      queued("q_8", "/review the diff"),
    ]);
    expect(result.map((m) => [m.queueId, m.text])).toEqual([
      ["q_1", "first\n\nsecond"],
      ["q_3", "!git status"],
      ["q_4", "third"],
      ["q_5", "  /compact"],
      ["q_6", "fourth\n\nfifth"],
      ["q_8", "/review the diff"],
    ]);
  });

  it("keeps Codex $skill messages, failed sends and item-comment messages separate", () => {
    const comments = buildItemCommentMessage([
      { label: "Q2", title: "Cutoff", comments: [{ text: "Use UTC.", attachments: [] }] },
    ]);
    const skillPrefix = "$";
    expect(keepsQueuedMessageSeparate(queued("q_1", "$review now"), { skillPrefix })).toBe(true);
    expect(keepsQueuedMessageSeparate(queued("q_1", "$5 is fine"))).toBe(false);
    expect(keepsQueuedMessageSeparate(queued("q_1", "x", { requiresRetry: true }))).toBe(true);
    expect(keepsQueuedMessageSeparate(queued("q_1", comments))).toBe(true);
    expect(keepsQueuedMessageSeparate(queued("q_1", "plain text"))).toBe(false);
  });

  it("does not merge across a change of agent", () => {
    const result = combinedQueue([
      queued("q_1", "a", { agentId: "agent_1" }),
      queued("q_2", "b", { agentId: "agent_1" }),
      queued("q_3", "c", { agentId: "agent_2" }),
    ]);
    expect(result.map((m) => [m.queueId, m.agentId, m.text])).toEqual([
      ["q_1", "agent_1", "a\n\nb"],
      ["q_3", "agent_2", "c"],
    ]);
  });

  it("holds the merged message for the host when any part waits for it", () => {
    const [merged] = combinedQueue([
      queued("q_1", "a"),
      queued("q_2", "b", { waitingForHost: true }),
    ]);
    expect(merged!.waitingForHost).toBe(true);
  });

  it("keeps reply quotes editable when the combined text still matches them", () => {
    const reply: StoredReplyDraft = {
      version: 1,
      quotes: [{ before: "", text: "the cutoff is local" }],
      text: "Why local?",
    };
    const [merged] = combinedQueue([
      queued("q_1", "One more thing."),
      queued("q_2", serializeReplyDraft(reply), { replyDraft: reply }),
    ]);
    expect(merged!.text).toBe("One more thing.\n\n> the cutoff is local\n\nWhy local?");
    expect(readComposerDraft(merged)?.replyDraft).toEqual({
      version: 1,
      quotes: [{ before: "One more thing.", text: "the cutoff is local" }],
      text: "Why local?",
    });
  });

  it("changes nothing with fewer than two adjacent combinable messages", () => {
    const lone = [queued("q_1", "only")];
    expect(combinedQueue(lone)).toEqual(lone);
    expect(canCombineQueue(lone)).toBe(false);
    const split = [queued("q_1", "a"), queued("q_2", "/clear"), queued("q_3", "b")];
    expect(combinedQueue(split)).toEqual(split);
    expect(canCombineQueue(split)).toBe(false);
    expect(canCombineQueue([])).toBe(false);
    expect(canCombineQueue([queued("q_1", "a"), queued("q_2", "b")])).toBe(true);
  });
});
