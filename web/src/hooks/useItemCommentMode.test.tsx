// Comment mode against a stand-in composer: drafting sets the typed message
// aside, submit sends one structured message through the send callback, and
// the drafts settle with the send path (posted, cancelled, or orphaned).

import { act, cleanup, renderHook } from "@testing-library/react";
import { useRef } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  composerInlineMentions,
  expandMentionTokens,
  presentMentions,
  sessionMentionMarker,
  SESSION_MENTION_HINT,
  type SessionMention,
} from "@/lib/composerMentions";
import { buildItemCommentMessage, scanItemLabelSource } from "@/lib/itemComments";
import {
  getItemCommentState,
  publishItemLabelIndex,
  resetItemCommentDraftsForTests,
  type ItemCommentState,
} from "@/lib/itemCommentDrafts";
import { buildItemLabelIndex } from "@/lib/itemLabels";
import { publishStoredOpenItems, resetClosableItemLabelsForTests } from "@/lib/openItemAnswers";
import { storedItem } from "@/test/openItemsFixtures";
import { useChatStore } from "@/store/chatStore";
import { useItemCommentMode, type ComposerContent } from "./useItemCommentMode";

const recordAnswers = vi.hoisted(() => vi.fn(() => Promise.resolve()));
vi.mock(import("@/lib/openItemAnswers"), async (importOriginal) => ({
  ...(await importOriginal()),
  recordItemCommentAnswers: recordAnswers,
}));

const SESSION_ID = "conv_comments";
const DEFINING_TEXT = [
  "Before I continue:",
  "",
  "1. **[R1] Backfill locking.** One transaction locks the table.",
  "2. **[Q2] Report cutoff timezone.** UTC or the account's zone?",
].join("\n");

let composer: ComposerContent;
const send = vi.fn<(text: string, files?: File[]) => void>();

function renderCommentMode() {
  return renderHook(() => {
    const setAsideRef = useRef<ComposerContent | null>(null);
    return useItemCommentMode({
      sessionId: SESSION_ID,
      enabled: true,
      setAsideRef,
      read: () => composer,
      write: (content) => {
        composer = content;
      },
      focus: () => {},
      // The composer's own expansion, so tags come out as an ordinary send has them.
      expandMentions: (text, mentions, sessions) => {
        const present = presentMentions(
          composerInlineMentions({ files: mentions, sessions }, "claude-native"),
          [text],
        );
        return {
          text: expandMentionTokens(text, present),
          tagsSessions: present.some((m) => m.marker.startsWith("[Session: ")),
        };
      },
      send,
    });
  });
}

type CommentMode = ReturnType<typeof renderCommentMode>["result"];

function comment(result: CommentMode, label: string, text: string, files: File[] = []) {
  act(() => result.current.startComment({ label, title: `${label} title` }));
  composer = { text, files, mentions: [], sessions: [] };
  act(() => result.current.saveComment());
}

function unsent(state: ItemCommentState) {
  return state.drafts.filter((draft) => !draft.submissionId);
}

beforeEach(() => {
  vi.useFakeTimers();
  composer = { text: "", files: [], mentions: [], sessions: [] };
  send.mockReset();
  useChatStore.setState({
    conversationId: SESSION_ID,
    queuedMessages: [],
    pendingUserMessages: [],
    blocks: [],
    failedSendDraft: null,
    restoredSendDraft: null,
  });
  publishItemLabelIndex(
    SESSION_ID,
    buildItemLabelIndex([
      scanItemLabelSource({ messageId: "a1", role: "assistant", text: DEFINING_TEXT }),
    ]),
  );
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  resetItemCommentDraftsForTests();
  resetClosableItemLabelsForTests();
  localStorage.clear();
});

describe("useItemCommentMode", () => {
  it("sets the typed message aside while commenting and saves the comment as a draft", () => {
    composer = { text: "Half-typed message", files: [], mentions: [], sessions: [] };
    const { result } = renderCommentMode();

    act(() => result.current.startComment({ label: "Q2", title: "Report cutoff timezone" }));
    expect(result.current.target).toEqual({
      label: "Q2",
      title: "Report cutoff timezone",
      draftId: null,
      closes: false,
    });
    expect(composer.text).toBe("");
    expect(result.current.excerpt).toBe("UTC or the account's zone?");
    expect(result.current.item?.source.messageId).toBe("a1");

    composer = { text: "Use the account's zone.", files: [], mentions: [], sessions: [] };
    act(() => result.current.saveComment());

    expect(result.current.target).toBeNull();
    expect(result.current.item).toBeNull();
    expect(composer.text).toBe("Half-typed message");
    expect(result.current.unsentDrafts.map((draft) => [draft.label, draft.text])).toEqual([
      ["Q2", "Use the account's zone."],
    ]);
  });

  it("keeps the comment as a draft on leaving, and deletes an edited draft cleared out", () => {
    const { result } = renderCommentMode();
    act(() => result.current.startComment({ label: "Q2", title: "Cutoff" }));
    composer = { text: "Typed before Escape", files: [], mentions: [], sessions: [] };
    act(() => result.current.leaveCommentMode());
    const [draft] = result.current.unsentDrafts;
    expect(draft.text).toBe("Typed before Escape");

    act(() => result.current.editDraft(draft.id));
    expect(composer.text).toBe("Typed before Escape");
    expect(result.current.target?.draftId).toBe(draft.id);
    composer = { text: "", files: [], mentions: [], sessions: [] };
    act(() => result.current.saveComment());
    expect(result.current.unsentDrafts).toEqual([]);
  });

  it("submits every draft as one message in definition order, with the typed message last", async () => {
    const { result } = renderCommentMode();
    comment(result, "Q2", "Use the account's zone.", [
      new File(["a,b"], "image.png", { type: "image/png" }),
    ]);
    comment(result, "R1", "Batch it at 5,000 rows.");
    comment(result, "Q2", "Store the zone per row.", [
      new File(["c"], "image.png", { type: "image/png" }),
    ]);
    composer = { text: "Q2 blocks the export PR.", files: [], mentions: [], sessions: [] };

    await act(() => result.current.submitComments());

    expect(send).toHaveBeenCalledTimes(1);
    const [text, files] = send.mock.calls[0];
    expect(text).toBe(
      buildItemCommentMessage(
        [
          {
            label: "R1",
            title: "Backfill locking",
            comments: [{ text: "Batch it at 5,000 rows.", attachments: [] }],
          },
          {
            label: "Q2",
            title: "Report cutoff timezone",
            comments: [
              { text: "Use the account's zone.", attachments: ["q2-1.png"] },
              { text: "Store the zone per row.", attachments: ["q2-2.png"] },
            ],
          },
        ],
        { text: "Q2 blocks the export PR.", attachments: [] },
      ),
    );
    expect(files?.map((file) => file.name)).toEqual(["q2-1.png", "q2-2.png"]);
    expect(composer.text).toBe("");
    // Sent, but kept until the message posts.
    expect(getItemCommentState(SESSION_ID).drafts).toHaveLength(3);
    expect(unsent(getItemCommentState(SESSION_ID))).toEqual([]);
  });

  it("sends only the drafts when asked, leaving the typed message in the composer", async () => {
    const { result } = renderCommentMode();
    comment(result, "R1", "Batch it.");
    const typed: ComposerContent = {
      text: "Still deciding.",
      files: [new File(["x"], "notes.txt", { type: "text/plain" })],
      mentions: [],
      sessions: [],
    };
    composer = typed;

    let sent = false;
    await act(async () => {
      sent = await result.current.submitComments({ withMessage: false });
    });

    expect(sent).toBe(true);
    expect(send).toHaveBeenCalledWith(
      buildItemCommentMessage(
        [
          {
            label: "R1",
            title: "Backfill locking",
            comments: [{ text: "Batch it.", attachments: [] }],
          },
        ],
        null,
      ),
      undefined,
    );
    expect(composer).toBe(typed);
    expect(getItemCommentState(SESSION_ID).submissions[0]?.general).toBeUndefined();
  });

  it("passes the queue override to the send, and nothing extra without it", async () => {
    const { result } = renderCommentMode();
    comment(result, "R1", "Batch it.");
    await act(() => result.current.submitComments({ queue: true }));
    expect(send.mock.calls[0]).toEqual([expect.any(String), undefined, { queue: true }]);

    comment(result, "R1", "And log it.");
    await act(() => result.current.submitComments());
    expect(send.mock.calls[1]).toHaveLength(2);
  });

  it("appends extra General text after the typed message and gives it back on cancel", async () => {
    const { result } = renderCommentMode();
    comment(result, "R1", "Batch it.");
    composer = { text: "Thanks.", files: [], mentions: [], sessions: [] };

    await act(() => result.current.submitComments({ appendGeneral: "Review context" }));

    const [text] = send.mock.calls[0];
    expect(text).toBe(
      buildItemCommentMessage(
        [
          {
            label: "R1",
            title: "Backfill locking",
            comments: [{ text: "Batch it.", attachments: [] }],
          },
        ],
        { text: "Thanks.\n\nReview context", attachments: [] },
      ),
    );
    act(() => {
      expect(result.current.restoreQueuedMessage(text)).toBe(true);
    });
    expect(composer.text).toBe("Thanks.\n\nReview context");
  });

  it("resolves false without sending when there are no drafts", async () => {
    const { result } = renderCommentMode();
    composer = { text: "Thanks.", files: [], mentions: [], sessions: [] };
    let sent = true;
    await act(async () => {
      sent = await result.current.submitComments();
    });
    expect(sent).toBe(false);
    expect(send).not.toHaveBeenCalled();
    expect(composer.text).toBe("Thanks.");
  });

  it("keeps session tags with comments and sends them with one tool hint", async () => {
    const fixCi: SessionMention = {
      id: "conv_fix",
      title: "Fix CI",
      isSubagent: false,
      token: "@Fix CI",
    };
    const audit: SessionMention = {
      id: "conv_audit",
      title: "Audit",
      isSubagent: true,
      token: "@Audit",
    };
    composer = { text: "See @Audit too.", files: [], mentions: [], sessions: [audit] };
    const { result } = renderCommentMode();
    act(() => result.current.startComment({ label: "R1", title: "Backfill locking" }));
    // A new comment starts empty; the typed message's tags wait with it.
    expect(composer.sessions).toEqual([]);
    composer = { text: "Ask @Fix CI first.", files: [], mentions: [], sessions: [fixCi] };
    act(() => result.current.saveComment());
    expect(composer.sessions).toEqual([audit]);
    // Reopening the draft brings its tag back.
    const [draft] = getItemCommentState(SESSION_ID).drafts;
    expect(draft.sessions).toEqual([fixCi]);
    act(() =>
      result.current.startComment({ label: "R1", title: "Backfill locking", draftId: draft.id }),
    );
    expect(composer.sessions).toEqual([fixCi]);
    act(() => result.current.saveComment());

    await act(() => result.current.submitComments());

    const [text] = send.mock.calls[0];
    expect(text).toContain(`Ask ${sessionMentionMarker(fixCi)} first.`);
    expect(text).toContain(`See ${sessionMentionMarker(audit)} too.`);
    expect(text).not.toContain("@Fix CI");
    expect(text.endsWith(`\n\n${SESSION_MENTION_HINT}`)).toBe(true);
    expect(text.split(SESSION_MENTION_HINT)).toHaveLength(2);
  });

  it("counts the comment being written when submitting from comment mode", async () => {
    composer = { text: "General note", files: [], mentions: [], sessions: [] };
    const { result } = renderCommentMode();
    act(() => result.current.startComment({ label: "R1", title: "Backfill locking" }));
    composer = { text: "Run it at night.", files: [], mentions: [], sessions: [] };

    await act(() => result.current.submitComments());

    expect(send.mock.calls[0][0]).toContain("#### [R1] Backfill locking\n\nRun it at night.");
    expect(send.mock.calls[0][0]).toContain("#### General\n\nGeneral note");
    expect(send.mock.calls[0][0]).not.toContain(SESSION_MENTION_HINT);
    expect(result.current.target).toBeNull();
  });

  it("drops the drafts once the message posts", async () => {
    const { result } = renderCommentMode();
    comment(result, "R1", "Batch it.");
    await act(() => result.current.submitComments());
    const [text] = send.mock.calls[0];

    act(() => {
      useChatStore.setState({
        queuedMessages: [{ queueId: "q_1", text, conversationId: SESSION_ID }],
      });
      vi.advanceTimersByTime(10);
    });
    expect(getItemCommentState(SESSION_ID).drafts).toHaveLength(1);

    act(() => {
      useChatStore.setState({
        queuedMessages: [],
        pendingUserMessages: [
          { tempId: "pend_1", content: [{ type: "input_text", text }], posted: true },
        ],
      });
      vi.advanceTimersByTime(10);
    });
    expect(getItemCommentState(SESSION_ID)).toEqual({ drafts: [], submissions: [] });
  });

  it("records the comments as the items' answers once, when the message posts", async () => {
    recordAnswers.mockClear();
    const { result } = renderCommentMode();
    comment(result, "R1", "Batch it.");
    await act(() => result.current.submitComments());
    const [text] = send.mock.calls[0];
    act(() => {
      useChatStore.setState({
        queuedMessages: [{ queueId: "q_1", text, conversationId: SESSION_ID }],
      });
      vi.advanceTimersByTime(10);
    });
    expect(recordAnswers).not.toHaveBeenCalled();
    act(() => {
      useChatStore.setState({
        queuedMessages: [],
        pendingUserMessages: [
          { tempId: "pend_1", content: [{ type: "input_text", text }], posted: true },
        ],
      });
      vi.advanceTimersByTime(10);
    });
    act(() => {
      useChatStore.setState({ pendingUserMessages: [] });
      vi.advanceTimersByTime(10);
    });
    expect(recordAnswers.mock.calls).toEqual([[SESSION_ID, text, undefined]]);
  });

  it("sends Comment and close marked in the heading and closes the item once it posts", async () => {
    recordAnswers.mockClear();
    publishStoredOpenItems(SESSION_ID, [storedItem("Q2"), storedItem("R1")]);
    const { result } = renderCommentMode();
    act(() => result.current.startComment({ label: "Q2", title: "Q2 title" }));
    expect(result.current.target?.closes).toBe(false);
    act(() => result.current.setTargetCloses(true));
    composer = { text: "Use the account's zone.", files: [], mentions: [], sessions: [] };
    act(() => result.current.saveComment());
    comment(result, "R1", "Batch it.");
    expect(result.current.unsentDrafts.map((draft) => [draft.label, draft.closes])).toEqual([
      ["R1", undefined],
      ["Q2", true],
    ]);

    await act(() => result.current.submitComments());
    const [text] = send.mock.calls[0];
    expect(text).toBe(
      [
        "Comments on 2 items:",
        "#### [R1] Backfill locking",
        "Batch it.",
        "#### [Q2] Report cutoff timezone (closed by me)",
        "Use the account's zone.",
      ].join("\n\n"),
    );
    act(() => {
      useChatStore.setState({
        pendingUserMessages: [
          { tempId: "pend_1", content: [{ type: "input_text", text }], posted: true },
        ],
      });
      vi.advanceTimersByTime(10);
    });
    expect(recordAnswers.mock.calls).toEqual([[SESSION_ID, text, ["Q2"]]]);
  });

  it("keeps Comment and close per item, and back in the drafts if the send is undone", async () => {
    publishStoredOpenItems(SESSION_ID, [storedItem("Q2")]);
    const { result } = renderCommentMode();
    comment(result, "Q2", "First.");
    comment(result, "Q2", "Second.");
    act(() => result.current.toggleItemClose("Q2"));
    expect(unsent(getItemCommentState(SESSION_ID)).map((draft) => draft.closes)).toEqual([
      true,
      true,
    ]);
    // A further comment on the item starts as closing it too.
    act(() => result.current.startComment({ label: "Q2", title: "Q2 title" }));
    expect(result.current.target?.closes).toBe(true);
    act(() => result.current.leaveCommentMode());

    await act(() => result.current.submitComments());
    const [text] = send.mock.calls[0];
    act(() => {
      useChatStore.setState({
        queuedMessages: [{ queueId: "q_1", text, conversationId: SESSION_ID }],
      });
    });
    act(() => {
      useChatStore.setState({ queuedMessages: [] });
      expect(result.current.restoreQueuedMessage(text)).toBe(true);
    });
    expect(result.current.unsentDrafts.map((draft) => draft.closes)).toEqual([true, true]);

    act(() => result.current.toggleItemClose("Q2"));
    expect(result.current.unsentDrafts.map((draft) => draft.closes)).toEqual([
      undefined,
      undefined,
    ]);
  });

  it("offers no Comment and close without a stored item that is still open", async () => {
    recordAnswers.mockClear();
    publishStoredOpenItems(SESSION_ID, [storedItem("R1", { status: "closed" })]);
    const { result } = renderCommentMode();
    act(() => result.current.startComment({ label: "Q2", title: "Q2 title", closes: true }));
    expect(result.current.target?.closes).toBe(false);
    composer = { text: "Use the account's zone.", files: [], mentions: [], sessions: [] };
    act(() => result.current.saveComment());
    act(() => result.current.toggleItemClose("R1"));
    comment(result, "R1", "Batch it.");
    expect(result.current.closableLabels.size).toBe(0);
    expect(result.current.unsentDrafts.some((draft) => draft.closes)).toBe(false);

    await act(() => result.current.submitComments());
    const [text] = send.mock.calls[0];
    expect(text).not.toContain("(closed by me)");
    expect(getItemCommentState(SESSION_ID).submissions[0]).not.toHaveProperty("closes");
  });

  it("gives the comments and the typed message back when the queued message is cancelled", async () => {
    const { result } = renderCommentMode();
    comment(result, "R1", "Batch it.");
    composer = { text: "Also, thanks.", files: [], mentions: [], sessions: [] };
    await act(() => result.current.submitComments());
    const [text] = send.mock.calls[0];
    act(() => {
      useChatStore.setState({
        queuedMessages: [{ queueId: "q_1", text, conversationId: SESSION_ID }],
      });
    });

    act(() => {
      useChatStore.setState({ queuedMessages: [] });
      expect(result.current.restoreQueuedMessage(text)).toBe(true);
    });

    expect(result.current.unsentDrafts.map((draft) => draft.text)).toEqual(["Batch it."]);
    expect(getItemCommentState(SESSION_ID).submissions).toEqual([]);
    expect(composer.text).toBe("Also, thanks.");
  });

  it("gives back a message that vanished without posting, after a grace period", async () => {
    const { result } = renderCommentMode();
    comment(result, "R1", "Batch it.");
    await act(() => result.current.submitComments());

    act(() => vi.advanceTimersByTime(10));
    expect(unsent(getItemCommentState(SESSION_ID))).toEqual([]);
    act(() => vi.advanceTimersByTime(5000));
    expect(unsent(getItemCommentState(SESSION_ID)).map((draft) => draft.text)).toEqual([
      "Batch it.",
    ]);
  });

  it("restores comments a closed page left orphaned, unless the transcript has them", () => {
    const orphanedText = buildItemCommentMessage([
      { label: "R1", title: "Backfill locking", comments: [{ text: "Lost.", attachments: [] }] },
    ]);
    const postedText = buildItemCommentMessage([
      { label: "Q2", title: "Cutoff", comments: [{ text: "Landed.", attachments: [] }] },
    ]);
    localStorage.setItem(
      `omnigent.itemComments.${SESSION_ID}`,
      JSON.stringify({
        drafts: [
          {
            id: "d1",
            label: "R1",
            title: "",
            text: "Lost.",
            files: [],
            createdAt: 1,
            submissionId: "s1",
          },
          {
            id: "d2",
            label: "Q2",
            title: "",
            text: "Landed.",
            files: [],
            createdAt: 2,
            submissionId: "s2",
          },
          {
            id: "d3",
            label: "Q2",
            title: "",
            text: "Elsewhere.",
            files: [],
            createdAt: 3,
            submissionId: "s3",
          },
        ],
        submissions: [
          { id: "s1", text: orphanedText, orphaned: true },
          { id: "s2", text: postedText, orphaned: true },
          { id: "s3", text: "still sending in another tab" },
        ],
      }),
    );
    useChatStore.setState({
      blocks: [
        {
          type: "user_message",
          ctx: { itemId: "item_1" },
          content: [{ type: "input_text", text: postedText }],
        } as never,
      ],
    });

    const { result } = renderCommentMode();
    act(() => vi.advanceTimersByTime(10));

    expect(result.current.unsentDrafts.map((draft) => draft.text)).toEqual(["Lost."]);
    expect(getItemCommentState(SESSION_ID).drafts.map((draft) => draft.id)).toEqual(["d1", "d3"]);
    expect(result.current.sendingElsewhere).toEqual([{ submissionId: "s3", commentCount: 1 }]);
  });

  it("turns a failed comment send back into drafts instead of composer text", async () => {
    const { result } = renderCommentMode();
    comment(result, "R1", "Batch it.");
    await act(() => result.current.submitComments());
    const [text] = send.mock.calls[0];

    let handled = false;
    act(() => {
      handled = result.current.takeFailedSend(text);
    });

    expect(handled).toBe(true);
    expect(result.current.unsentDrafts.map((draft) => draft.text)).toEqual(["Batch it."]);
    expect(result.current.takeFailedSend("an ordinary message")).toBe(false);
  });
});
