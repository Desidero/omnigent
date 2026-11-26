// The sidebar's New session links hand a plain click to the project prompt
// (store/newSessionProjectPrompt.test.ts covers which clicks it takes).

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/hooks/useScopeCache", () => import("@/test/mockScopeCache"));
vi.mock("@/hooks/useConversations", async () => {
  const { conversationHooksMock } = await import("@/test/sidebarMockHelpers");
  return conversationHooksMock();
});
vi.mock("@/components/PermissionsModal", () => ({ PermissionsModal: () => null }));

import { TooltipProvider } from "@/components/ui/tooltip";
import { useConversations } from "@/hooks/useConversations";
import { SidebarDataProvider } from "@/hooks/useSidebarData";
import { FALLBACK_SERVER_INFO } from "@/lib/capabilities";
import { CapabilitiesProvider } from "@/lib/CapabilitiesContext";
import { useNewSessionProjectPromptStore } from "@/store/newSessionProjectPrompt";
import { conversationPage } from "@/test/sidebarMockHelpers";

import { Sidebar } from "./Sidebar";

function CurrentPath() {
  return <output data-testid="current-path">{useLocation().pathname}</output>;
}

function renderSidebar() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <CapabilitiesProvider info={FALLBACK_SERVER_INFO}>
        <SidebarDataProvider>
          <TooltipProvider>
            <MemoryRouter initialEntries={["/c/conv_1"]}>
              <Sidebar open={true} onClose={vi.fn()} />
              <CurrentPath />
            </MemoryRouter>
          </TooltipProvider>
        </SidebarDataProvider>
      </CapabilitiesProvider>
    </QueryClientProvider>,
  );
}

const promptOpen = () => useNewSessionProjectPromptStore.getState().open;
const currentPath = () => screen.getByTestId("current-path").textContent;

beforeEach(() => {
  const noSessions = conversationPage([]);
  vi.mocked(useConversations).mockImplementation(() => noSessions);
});
afterEach(() => {
  cleanup();
  useNewSessionProjectPromptStore.setState({ open: false, hosted: false });
  localStorage.clear();
});

describe("Sidebar New session links", () => {
  it.each(["new-chat-button", "sessions-new-session"])(
    "%s asks for a project on a plain click, and still opens a new tab on a modified one",
    (testId) => {
      useNewSessionProjectPromptStore.setState({ hosted: true });
      renderSidebar();
      const link = screen.getByTestId(testId).closest("a") ?? screen.getByTestId(testId);

      // The browser opens the new tab: nothing here prevents the click.
      expect(fireEvent.click(link, { metaKey: true })).toBe(true);
      expect(promptOpen()).toBe(false);

      fireEvent.click(link);
      expect(promptOpen()).toBe(true);
      expect(currentPath()).toBe("/c/conv_1");
    },
  );

  it("follows the link where no shell mounts the prompt", () => {
    renderSidebar();

    fireEvent.click(screen.getByTestId("new-chat-button"));

    expect(promptOpen()).toBe(false);
    expect(currentPath()).toBe("/");
  });
});
