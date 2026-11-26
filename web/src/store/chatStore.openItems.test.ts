import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import { openItemsKey } from "@/lib/openItems";
import { handleSessionEvent, initChatStore } from "@/store/chatStore";
import { storedItem } from "@/test/openItemsFixtures";

describe("a live open items change", () => {
  it("marks that session's stored items stale, and only that session's", () => {
    const queryClient = new QueryClient();
    initChatStore(queryClient);
    queryClient.setQueryData(openItemsKey("conv"), [storedItem("Q1")]);
    queryClient.setQueryData(openItemsKey("other"), [storedItem("Q1")]);
    handleSessionEvent(
      { type: "session_open_items_changed", conversationId: "conv", labels: ["Q1"] },
      "conv",
    );
    expect(queryClient.getQueryState(openItemsKey("conv"))?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(openItemsKey("other"))?.isInvalidated).toBe(false);
  });
});
