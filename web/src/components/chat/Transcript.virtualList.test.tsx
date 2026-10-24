import { measureElement, useVirtualizer } from "@tanstack/react-virtual";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { Bubble } from "@/lib/renderItems";
import { Conversation, ConversationContent } from "@/components/ai-elements/conversation";
import { isNativeFindShortcut, type TranscriptGeometry, VirtualBubbleList } from "./Transcript";

afterEach(cleanup);

const bubble: Extract<Bubble, { kind: "user" }> = {
  kind: "user",
  itemId: "user-1",
  content: [{ type: "input_text", text: "hello" }],
};

const assistantBubble: Extract<Bubble, { kind: "assistant" }> = {
  kind: "assistant",
  responseId: "response-1",
  stableId: "response-1",
  lifecycle: "completed",
  error: null,
  items: [{ kind: "text", itemId: "assistant-1", text: "hello back", final: true }],
};

function list(
  hasTasks: boolean,
  scrollEl: HTMLElement,
  onGeometryChange: (geometry: TranscriptGeometry) => void = vi.fn(),
  disableVirtualization = false,
  bubbles: Bubble[] = [bubble],
) {
  return (
    <Conversation>
      <ConversationContent>
        <VirtualBubbleList
          bubbles={bubbles}
          scrollEl={scrollEl}
          lastAssistantIndex={-1}
          showsWorking={false}
          sessionIdle
          conversationId={undefined}
          hasTasks={hasTasks}
          disableVirtualization={disableVirtualization}
          onGeometryChange={onGeometryChange}
        />
      </ConversationContent>
    </Conversation>
  );
}

function messageList(bubbles: Bubble[], showsWorking: boolean, sessionIdle: boolean) {
  return (
    <Conversation>
      <ConversationContent>
        <VirtualBubbleList
          bubbles={bubbles}
          scrollEl={null}
          lastAssistantIndex={bubbles.findLastIndex((item) => item.kind === "assistant")}
          showsWorking={showsWorking}
          sessionIdle={sessionIdle}
          conversationId="conv-1"
          hasTasks={false}
          disableVirtualization
          onGeometryChange={vi.fn()}
        />
      </ConversationContent>
    </Conversation>
  );
}

function actionFooter(button: HTMLElement): HTMLElement {
  return button.parentElement!.parentElement!;
}

it("remeasures scrollMargin when task padding changes without changing bubbles", async () => {
  const scrollEl = document.createElement("div");
  Object.defineProperties(scrollEl, {
    scrollTop: { configurable: true, writable: true, value: 0 },
    clientHeight: { configurable: true, value: 500 },
    scrollHeight: { configurable: true, value: 1_000 },
  });
  scrollEl.getBoundingClientRect = () => ({ top: 0 }) as DOMRect;

  const bubbles = ["user-0", "user-1", "user-2"].map((itemId) => ({ ...bubble, itemId }));
  // Mount only the middle row, at the library's offsets: 200px rows `gap` apart after `scrollMargin`.
  const passThrough = vi.mocked(useVirtualizer).getMockImplementation()!;
  vi.mocked(useVirtualizer).mockImplementation((options) => {
    const start = options.scrollMargin! + 200 + options.gap!;
    const row = {
      index: 1,
      key: options.getItemKey!(1),
      start,
      size: 200,
      end: start + 200,
      lane: 0,
    };
    const totalSize = 3 * 200 + 2 * options.gap!;
    return {
      ...passThrough(options),
      getVirtualItems: () => [row],
      getTotalSize: () => totalSize,
    } as never;
  });
  try {
    const view = render(list(false, scrollEl, vi.fn(), false, bubbles));
    const row = view.container.querySelector<HTMLElement>('[data-index="1"]')!;
    expect(row).toHaveAttribute("data-bubble-key", "user:user-1");
    const wrapper = row.parentElement!;
    expect(wrapper).toHaveStyle("padding-top: 216px; padding-bottom: 216px");
    wrapper.getBoundingClientRect = () => ({ top: 64 }) as DOMRect;

    view.rerender(list(true, scrollEl, vi.fn(), false, bubbles));

    await waitFor(() => expect(vi.mocked(useVirtualizer).mock.lastCall?.[0].scrollMargin).toBe(64));
    expect(wrapper).toHaveStyle("padding-top: 216px; padding-bottom: 216px");
  } finally {
    vi.mocked(useVirtualizer).mockImplementation(passThrough);
  }
});

it("measures rows at their unrounded border-box height", () => {
  const view = render(list(false, document.createElement("div")));
  const row = view.container.querySelector<HTMLElement>('[data-index="0"]')!;
  const measure = vi.mocked(useVirtualizer).mock.lastCall![0].measureElement!;
  const entry = { borderBoxSize: [{ blockSize: 58.796875, inlineSize: 600 }] };
  const instance = {
    options: { getItemKey: () => "user:user-1", horizontal: false },
    indexFromElement: () => 0,
    itemSizeCache: new Map([["user:user-1", 340.625]]),
  };

  expect(measure(row, entry as unknown as ResizeObserverEntry, instance as never)).toBe(58.796875);
  expect(measure(row, undefined, instance as never)).toBe(
    measureElement(row, undefined, instance as never),
  );

  // A first mount has no cached size; read the unrounded box, not offsetHeight.
  instance.itemSizeCache.clear();
  row.getBoundingClientRect = () => ({ height: 58.796875 }) as DOMRect;
  expect(measure(row, undefined, instance as never)).toBe(58.796875);
});

it("publishes navigation that distinguishes loaded and missing turns", async () => {
  const scrollEl = document.createElement("div");
  const onGeometryChange = vi.fn<(geometry: TranscriptGeometry) => void>();

  render(list(false, scrollEl, onGeometryChange));

  await waitFor(() => expect(onGeometryChange).toHaveBeenCalled());
  const geometry = onGeometryChange.mock.calls.at(-1)![0];
  expect(geometry.scrollToItem("user-1")).toBe(true);
  expect(geometry.scrollToItem("missing")).toBe(false);
});

it("recognizes unhandled native find keyboard shortcuts", () => {
  expect(
    isNativeFindShortcut({
      key: "f",
      metaKey: true,
      ctrlKey: false,
      altKey: false,
      defaultPrevented: false,
    }),
  ).toBe(true);
  expect(
    isNativeFindShortcut({
      key: "f",
      metaKey: false,
      ctrlKey: true,
      altKey: false,
      defaultPrevented: false,
    }),
  ).toBe(true);
  expect(
    isNativeFindShortcut({
      key: "f",
      metaKey: true,
      ctrlKey: false,
      altKey: false,
      defaultPrevented: true,
    }),
  ).toBe(false);
});

it("renders every bubble in normal flow after native find is detected", () => {
  const scrollEl = document.createElement("div");

  const view = render(list(false, scrollEl, vi.fn(), true));

  expect(view.container.querySelector('[data-index="0"]')).toBeNull();
  expect(view.container.querySelectorAll('[data-testid="message-bubble"]')).toHaveLength(1);
});

it("keeps actions visible only on a final assistant message while idle", () => {
  const bubbles: Bubble[] = [bubble, assistantBubble, { kind: "compaction", itemId: "compact-1" }];
  const view = render(messageList(bubbles, false, true));
  const copyButtons = screen.getAllByRole("button", { name: "Copy" });

  expect(actionFooter(copyButtons[0]!)).toHaveClass("md:opacity-0");
  expect(actionFooter(copyButtons[1]!)).toHaveClass("opacity-100");
  expect(actionFooter(copyButtons[1]!)).not.toHaveClass(
    "md:opacity-0",
    "md:group-hover:opacity-100",
  );

  view.rerender(messageList(bubbles, false, false));
  expect(actionFooter(screen.getAllByRole("button", { name: "Copy" })[1]!)).toHaveClass(
    "md:opacity-0",
  );
});

it("keeps every action row hover-only when the final message is from the user", () => {
  render(messageList([assistantBubble, bubble], false, true));

  for (const button of screen.getAllByRole("button", { name: "Copy" })) {
    expect(actionFooter(button)).toHaveClass("md:opacity-0");
  }
});

it("keeps a renamed top bubble's row across a history prepend", () => {
  // An assistant bubble is keyed by its first item, so a page that continues
  // the top turn renames it. The row must keep its node: a remount replays the
  // action row's hover fade on every page while older history loads.
  const scrollEl = document.createElement("div");
  Object.defineProperties(scrollEl, {
    scrollTop: { configurable: true, writable: true, value: 0 },
    clientHeight: { configurable: true, value: 500 },
    scrollHeight: { configurable: true, value: 1_000 },
  });
  scrollEl.getBoundingClientRect = () => ({ top: 0 }) as DOMRect;
  const transcript = (bubbles: Bubble[]) => (
    <Conversation>
      <ConversationContent>
        <VirtualBubbleList
          bubbles={bubbles}
          scrollEl={scrollEl}
          lastAssistantIndex={bubbles.length - 1}
          showsWorking={false}
          sessionIdle
          conversationId="conv-1"
          hasTasks={false}
          disableVirtualization={false}
          onGeometryChange={vi.fn()}
        />
      </ConversationContent>
    </Conversation>
  );

  const view = render(transcript([assistantBubble]));
  const row = view.container.querySelector<HTMLElement>('[data-index="0"]')!;
  expect(row).toHaveAttribute("data-bubble-key", "assistant:response-1");

  // The page lands an earlier item of the same response: same bubble, new key.
  const renamed: Bubble = {
    ...assistantBubble,
    stableId: "assistant-0",
    items: [
      { kind: "text", itemId: "assistant-0", text: "hello first", final: true },
      ...assistantBubble.items,
    ],
  };
  view.rerender(transcript([renamed]));

  expect(view.container.querySelector('[data-index="0"]')).toBe(row);
  expect(row).toHaveAttribute("data-bubble-key", "assistant:response-1");

  // A genuinely earlier turn is a new row above; the renamed bubble keeps its node.
  view.rerender(transcript([bubble, renamed]));
  expect(view.container.querySelector('[data-index="1"]')).toBe(row);
  expect(view.container.querySelector('[data-index="0"]')).toHaveAttribute(
    "data-bubble-key",
    "user:user-1",
  );
});

it("holds the row under the reader while rows above it change height", () => {
  // Rows the mocked virtualizer reports, list-relative; mutable so a
  // re-measure or a re-key can be played back through the virtualizer's
  // onChange, the way a ResizeObserver batch or a mount measurement reaches it.
  interface Row {
    key: string;
    start: number;
    size: number;
  }
  let rows: Row[] = [
    { key: "user:user-0", start: 0, size: 200 },
    { key: "user:user-1", start: 216, size: 200 },
    { key: "user:user-2", start: 432, size: 200 },
  ];
  const passThrough = vi.mocked(useVirtualizer).getMockImplementation()!;
  vi.mocked(useVirtualizer).mockImplementation(
    (options) =>
      ({
        ...passThrough(options),
        getVirtualItems: () =>
          rows.map((row, index) => ({
            index,
            key: row.key,
            start: options.scrollMargin! + row.start,
            size: row.size,
            end: options.scrollMargin! + row.start + row.size,
            lane: 0,
          })),
        getTotalSize: () => rows.at(-1)!.start + rows.at(-1)!.size,
      }) as never,
  );
  try {
    const bubbles = ["user-0", "user-1", "user-2"].map((itemId) => ({ ...bubble, itemId }));
    const view = render(list(false, document.createElement("div"), vi.fn(), false, bubbles));
    // The hold writes through StickToBottom, so hand it StickToBottom's own scroller.
    const scroller = view.container.querySelector<HTMLElement>('[role="log"] > div')!;
    Object.defineProperties(scroller, {
      scrollTop: { configurable: true, writable: true, value: 216 },
      clientHeight: { configurable: true, value: 500 },
      scrollHeight: { configurable: true, value: 1_000 },
    });
    scroller.getBoundingClientRect = () => ({ top: 0 }) as DOMRect;
    // The list sits at the scroller's top, scrolled by 216: its offset is 0.
    const wrapper = view.container.querySelector<HTMLElement>('[data-index="0"]')!.parentElement!;
    wrapper.getBoundingClientRect = () => ({ top: -216 }) as DOMRect;
    view.rerender(list(false, scroller, vi.fn(), false, bubbles));
    expect(scroller.scrollTop).toBe(216);
    const virtualizer = vi.mocked(useVirtualizer).mock.results.at(-1)!.value as {
      shouldAdjustScrollPositionOnItemSizeChange?: () => boolean;
    };
    // The hold is the only in-list compensation; the library's own is off.
    expect(virtualizer.shouldAdjustScrollPositionOnItemSizeChange?.()).toBe(false);
    const notify = () =>
      vi.mocked(useVirtualizer).mock.lastCall![0].onChange!(undefined as never, false);

    // The row above the reader grows by 100: the reader's row keeps its place.
    rows = [
      { key: "user:user-0", start: 0, size: 300 },
      { key: "user:user-1", start: 316, size: 200 },
      { key: "user:user-2", start: 532, size: 200 },
    ];
    notify();
    expect(scroller.scrollTop).toBe(316);

    // It shrinks back: so does the offset.
    rows = [
      { key: "user:user-0", start: 0, size: 200 },
      { key: "user:user-1", start: 216, size: 200 },
      { key: "user:user-2", start: 432, size: 200 },
    ];
    notify();
    expect(scroller.scrollTop).toBe(216);

    // The reader's row remounts under a new key with the same content: nothing moved.
    rows = [
      { key: "user:user-0", start: 0, size: 200 },
      { key: "assistant:renamed", start: 216, size: 200 },
      { key: "user:user-2", start: 432, size: 200 },
    ];
    notify();
    expect(scroller.scrollTop).toBe(216);
  } finally {
    vi.mocked(useVirtualizer).mockImplementation(passThrough);
  }
});
