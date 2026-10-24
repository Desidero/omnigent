import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import type { Bubble } from "@/lib/renderItems";
import { Conversation, ConversationContent } from "@/components/ai-elements/conversation";
import {
  JumpToLatestButton,
  countNewMessages,
  jumpToLatestLabel,
  lastSettledMessageKey,
  transcriptMessageKeys,
} from "./JumpToLatestButton";

afterEach(cleanup);

function user(itemId: string, text = "hello"): Extract<Bubble, { kind: "user" }> {
  return { kind: "user", itemId, content: [{ type: "input_text", text }] };
}

function assistant(
  responseId: string,
  lifecycle: Extract<Bubble, { kind: "assistant" }>["lifecycle"] = "completed",
  stableId = responseId,
): Extract<Bubble, { kind: "assistant" }> {
  return {
    kind: "assistant",
    responseId,
    stableId,
    lifecycle,
    error: null,
    items: [{ kind: "text", itemId: `${stableId}-text`, text: "reply", final: true }],
  };
}

const systemUser: Extract<Bubble, { kind: "user" }> = {
  kind: "user",
  itemId: "sys-1",
  content: [{ type: "input_text", text: "[System: timer fired]" }],
};

describe("transcript message keys", () => {
  it("counts one key per user turn and per assistant response", () => {
    expect(
      transcriptMessageKeys([
        user("u1"),
        assistant("r1", "completed", "r1-a"),
        assistant("r1", "completed", "r1-b"),
        { kind: "compaction", itemId: "c1" },
        user("u2"),
        assistant("r2", "streaming"),
      ]),
    ).toEqual(["user:u1", "assistant:r1", "user:u2", "assistant:r2"]);
  });

  it("ignores system messages", () => {
    expect(transcriptMessageKeys([user("u1"), systemUser])).toEqual(["user:u1"]);
  });

  it("treats a streaming reply as not yet seen", () => {
    expect(lastSettledMessageKey([user("u1"), assistant("r1", "streaming")])).toBe("user:u1");
    expect(lastSettledMessageKey([user("u1"), assistant("r1")])).toBe("assistant:r1");
    expect(lastSettledMessageKey([systemUser])).toBeNull();
    expect(lastSettledMessageKey([])).toBeNull();
  });
});

describe("new message count", () => {
  it("counts distinct messages after the last seen one", () => {
    const keys = ["user:u1", "assistant:r1", "user:u2", "assistant:r2"];
    expect(countNewMessages(keys, "assistant:r1")).toBe(2);
    expect(countNewMessages(keys, "assistant:r2")).toBe(0);
    expect(countNewMessages(keys, null)).toBe(4);
  });

  it("ignores older history landing above the seen message", () => {
    expect(countNewMessages(["user:u0", "assistant:r0", "user:u1"], "user:u1")).toBe(0);
  });

  it("asks for a new baseline when the seen message is gone", () => {
    expect(countNewMessages(["user:u9"], "user:u1")).toBeNull();
  });
});

describe("jump to latest label", () => {
  it("offers a plain jump with nothing new", () => {
    expect(jumpToLatestLabel({ newCount: 0, streaming: false })).toEqual({
      text: "Jump to latest",
      ariaLabel: "Jump to the latest message",
      attention: false,
    });
  });

  it("signals a streaming reply", () => {
    expect(jumpToLatestLabel({ newCount: 1, streaming: true })).toMatchObject({
      text: "New reply",
      attention: true,
    });
    expect(jumpToLatestLabel({ newCount: 0, streaming: true }).text).toBe("New reply");
  });

  it("counts appended messages, streaming or not", () => {
    expect(jumpToLatestLabel({ newCount: 1, streaming: false }).text).toBe("1 new message");
    expect(jumpToLatestLabel({ newCount: 3, streaming: false })).toMatchObject({
      text: "3 new messages",
      ariaLabel: "3 new messages, jump to the latest message",
      attention: true,
    });
    expect(jumpToLatestLabel({ newCount: 2, streaming: true }).text).toBe("2 new messages");
  });
});

describe("JumpToLatestButton", () => {
  const SCROLL_HEIGHT = 2000;
  const CLIENT_HEIGHT = 500;
  const BOTTOM = SCROLL_HEIGHT - 1 - CLIENT_HEIGHT;

  function transcript(containerEl: HTMLElement, bubbles: Bubble[], streaming = false) {
    return (
      <Conversation>
        <ConversationContent>
          <div style={{ height: SCROLL_HEIGHT }} />
        </ConversationContent>
        <JumpToLatestButton containerEl={containerEl} bubbles={bubbles} streaming={streaming} />
      </Conversation>
    );
  }

  function mount(bubbles: Bubble[], streaming = false) {
    const containerEl = document.createElement("div");
    document.body.append(containerEl);
    const view = render(transcript(containerEl, bubbles, streaming));
    const scrollEl = view.container.querySelector<HTMLElement>('[role="log"] > div')!;
    let scrollTop = BOTTOM;
    Object.defineProperties(scrollEl, {
      scrollHeight: { configurable: true, value: SCROLL_HEIGHT },
      clientHeight: { configurable: true, value: CLIENT_HEIGHT },
      scrollTop: {
        configurable: true,
        get: () => scrollTop,
        set: (value: number) => {
          scrollTop = Math.max(0, Math.min(value, BOTTOM));
        },
      },
    });
    // StickToBottom only notices a reader scrolling up relative to a previous
    // scroll event, so settle at the bottom first.
    fireEvent.scroll(scrollEl);
    const scrollTo = (top: number) => {
      scrollEl.scrollTop = top;
      fireEvent.scroll(scrollEl);
    };
    const rerender = (next: Bubble[], nextStreaming = false) =>
      view.rerender(transcript(containerEl, next, nextStreaming));
    return { scrollEl, scrollTo, rerender, containerEl, unmount: view.unmount };
  }

  const pill = () => screen.getByTestId("jump-to-latest");
  const expectHidden = () => expect(pill()).toHaveAttribute("aria-hidden", "true");
  const expectShown = async () =>
    waitFor(() => {
      expect(pill()).toHaveAttribute("aria-hidden", "false");
      expect(pill()).toHaveAttribute("tabindex", "0");
    });

  it("stays hidden at the bottom and appears once the reader scrolls away", async () => {
    const { scrollTo, containerEl, unmount } = mount([user("u1"), assistant("r1")]);
    expectHidden();
    expect(pill()).toHaveAttribute("tabindex", "-1");
    expect(containerEl.contains(pill())).toBe(true);

    scrollTo(400);
    // Not before the settle delay: a mount pin or deep-link scroll never flashes it.
    expectHidden();
    await expectShown();
    expect(pill()).toHaveTextContent("Jump to latest");
    expect(pill()).toHaveAttribute("aria-label", "Jump to the latest message");
    expect(pill()).toHaveAttribute("data-state", "idle");
    unmount();
  });

  it("signals a reply streaming below and then counts what landed", async () => {
    // The reader sent u2, then scrolled up while its reply streams.
    const { scrollTo, rerender, unmount } = mount(
      [user("u1"), assistant("r1"), user("u2"), assistant("r2", "streaming")],
      true,
    );
    scrollTo(400);
    await expectShown();
    expect(pill()).toHaveTextContent("New reply");
    expect(pill()).toHaveAttribute("aria-label", "New reply streaming, jump to it");
    expect(pill()).toHaveAttribute("data-state", "new");

    rerender([user("u1"), assistant("r1"), user("u2"), assistant("r2")]);
    expect(pill()).toHaveTextContent("1 new message");

    // Another client adds a turn below.
    rerender([
      user("u1"),
      assistant("r1"),
      user("u2"),
      assistant("r2"),
      user("u3"),
      assistant("r3"),
    ]);
    expect(pill()).toHaveTextContent("3 new messages");
    expect(pill()).toHaveAttribute("aria-label", "3 new messages, jump to the latest message");
    unmount();
  });

  it("keeps counting a reply that was still streaming when the reader left", async () => {
    const { scrollTo, rerender, unmount } = mount([user("u1"), assistant("r1", "streaming")]);
    scrollTo(400);
    await expectShown();

    rerender([user("u1"), assistant("r1")]);
    expect(pill()).toHaveTextContent("1 new message");
    unmount();
  });

  it("does not count older history or a replaced conversation as new", async () => {
    const { scrollTo, rerender, unmount } = mount([user("u5"), assistant("r5")]);
    scrollTo(400);
    await expectShown();

    rerender([user("u4"), assistant("r4"), user("u5"), assistant("r5")]);
    expect(pill()).toHaveTextContent("Jump to latest");

    rerender([user("x1"), assistant("y1"), user("x2"), assistant("y2")]);
    expect(pill()).toHaveTextContent("Jump to latest");
    unmount();
  });

  it("returns to the bottom and re-engages follow on click or Enter", async () => {
    const { scrollEl, scrollTo, rerender, unmount } = mount([user("u1"), assistant("r1")]);
    scrollTo(400);
    await expectShown();
    rerender([user("u1"), assistant("r1"), user("u2"), assistant("r2")]);
    expect(pill()).toHaveTextContent("2 new messages");

    await userEvent.click(pill());
    expectHidden();
    await waitFor(() => expect(scrollEl.scrollTop).toBe(BOTTOM));

    // Content growing while followed keeps the pill away.
    rerender([user("u1"), assistant("r1"), user("u2"), assistant("r2"), user("u3")]);
    expectHidden();

    scrollTo(300);
    await expectShown();
    expect(pill()).toHaveTextContent("Jump to latest");
    pill().focus();
    await userEvent.keyboard("{Enter}");
    expectHidden();
    await waitFor(() => expect(scrollEl.scrollTop).toBe(BOTTOM));
    unmount();
  });
});
