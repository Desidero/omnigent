// Session-row slots in the sidebar: core's Shared decoration and read-state
// pair, plus an extension's label badge and set-label menu, gated on the
// viewer's edit access. Only the data hooks and the network are mocked.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type * as Toast from "@/components/ui/toast";
import type * as Identity from "@/lib/identity";

vi.mock("@/hooks/useScopeCache", () => import("@/test/mockScopeCache"));
vi.mock("@/hooks/useConversations", async () => {
  const { conversationHooksMock } = await import("@/test/sidebarMockHelpers");
  return conversationHooksMock();
});
vi.mock("@/components/PermissionsModal", () => ({ PermissionsModal: () => null }));
const { authenticatedFetchMock, showToastMock } = vi.hoisted(() => ({
  authenticatedFetchMock: vi.fn(),
  showToastMock: vi.fn(),
}));
vi.mock("@/lib/identity", async (importOriginal) => ({
  ...(await importOriginal<typeof Identity>()),
  authenticatedFetch: authenticatedFetchMock,
}));
vi.mock("@/components/ui/toast", async (importOriginal) => ({
  ...(await importOriginal<typeof Toast>()),
  showToast: showToastMock,
}));

import { TooltipProvider } from "@/components/ui/tooltip";
import { ExtensionCatalogProvider } from "@/extensions/ExtensionProvider";
import type { ExtensionCatalogItem, ExtensionSlotItem } from "@/extensions/types";
import { type Conversation, useConversations } from "@/hooks/useConversations";
import { SidebarDataProvider } from "@/hooks/useSidebarData";
import { resetReadStateForTests, seedReadState } from "@/hooks/useUnseenConversations";
import { conversationPage } from "@/test/sidebarMockHelpers";
import { Sidebar } from "./Sidebar";

const KEY = "ext.acme.status.status";

function rowItem(id: string, slot: ExtensionSlotItem["slot"], kind: ExtensionSlotItem["kind"]) {
  return {
    id: `acme.status.${id}`,
    slot,
    kind,
    label: "Status",
    page: null,
    icon: null,
    order: 500,
    when: null,
    binding: { source: "label" as const, key: KEY },
  };
}

const STATUS_EXTENSION: ExtensionCatalogItem = {
  object: "extension",
  id: "acme.status",
  display_name: "Status",
  distribution: "acme-status",
  version: "1.0.0",
  extension_api: 1,
  status: "enabled",
  permissions: ["sessions.labels.write"],
  pages: [],
  primary_navigation: [],
  slot_items: [
    rowItem("badge", "session.row.decorations", "decoration"),
    { ...rowItem("menu", "session.row.menu", "set-label"), clear_label: "Clear status" },
  ],
  labels: [
    {
      key: KEY,
      title: "Status",
      values: [
        { value: "blocked", label: "Blocked", icon: "octagon-alert", tone: "danger" },
        { value: "done", label: "Done", icon: "circle-check", tone: "success" },
      ],
    },
  ],
  browser: { declared: false, has_styles: false, digest: null, script_url: null, style_url: null },
};

function conv(id: string, partial: Partial<Conversation> = {}): Conversation {
  return {
    id,
    object: "conversation",
    title: id,
    created_at: 1_700_000_000,
    updated_at: 1_700_000_000,
    labels: {},
    permission_level: null,
    status: "idle",
    ...partial,
  };
}

function renderSidebar(conversations: Conversation[], extensions = [STATUS_EXTENSION]) {
  vi.mocked(useConversations).mockImplementation(() => conversationPage(conversations));
  seedReadState(conversations.map(({ id, updated_at }) => ({ id, updated_at })));
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <SidebarDataProvider>
        <ExtensionCatalogProvider extensions={extensions}>
          <TooltipProvider>
            <MemoryRouter>
              <Sidebar open onClose={vi.fn()} />
            </MemoryRouter>
          </TooltipProvider>
        </ExtensionCatalogProvider>
      </SidebarDataProvider>
    </QueryClientProvider>,
  );
}

// Shared rows list under the "All sessions" filter.
function showAllSessions() {
  fireEvent.pointerDown(screen.getByTestId("session-filter"), { button: 0, pointerType: "mouse" });
  const displayMenu = screen.queryByTestId("session-display-menu");
  if (displayMenu) fireEvent.keyDown(displayMenu, { key: "ArrowRight" });
  fireEvent.click(screen.getByTestId("session-filter-all"));
}

function patches(): [string, RequestInit][] {
  return authenticatedFetchMock.mock.calls.filter(
    (call): call is [string, RequestInit] =>
      (call[1] as RequestInit | undefined)?.method === "PATCH",
  );
}

function row(id: string): HTMLElement {
  return screen.getByRole("link", { name: new RegExp(id) }).closest("li") as HTMLElement;
}

function openStatusMenu(id: string) {
  fireEvent.pointerDown(within(row(id)).getByTestId("conversation-actions"), { button: 0 });
  fireEvent.keyDown(screen.getByTestId("session-row-menu-acme.status.menu"), {
    key: "ArrowRight",
  });
}

beforeEach(() => {
  resetReadStateForTests();
  authenticatedFetchMock.mockReset();
  showToastMock.mockReset();
});
afterEach(cleanup);

describe("session-row decorations", () => {
  it("follows core's Shared entry with the declared value as text and icon", () => {
    renderSidebar([
      conv("shared_row", {
        owner: "other@example.com",
        permission_level: 1,
        labels: { [KEY]: "blocked" },
      }),
    ]);
    showAllSessions();

    const group = within(row("shared_row")).getByTestId("session-row-decorations");
    const [shared, badge] = within(group).getAllByRole("img");
    expect(shared).toHaveAccessibleName("Shared session");
    expect(badge).toHaveAccessibleName("Status: Blocked");
    expect(badge).toHaveAttribute("title", "Status: Blocked");
    expect(badge.querySelector("svg")).toHaveClass("text-status-red!");
    // Room for both icons, so the title stops before them.
    expect(screen.getByRole("link", { name: /shared_row/ })).toHaveClass("pr-14");
  });

  it.each<Record<string, string>>([
    {},
    { [KEY]: "" },
    { [KEY]: "bogus" },
    { [KEY]: "constructor" },
  ])("renders nothing for an absent, empty or undeclared value: %j", (labels) => {
    renderSidebar([conv("own_row", { labels })]);
    expect(within(row("own_row")).queryByTestId("session-row-decorations")).toBeNull();
  });

  it("renders no extension items without the catalog", () => {
    renderSidebar([conv("own_row", { labels: { [KEY]: "done" } })], []);
    expect(within(row("own_row")).queryByRole("img")).toBeNull();
  });
});

describe("session-row menu", () => {
  it("lists declared values after core's read-state entry and writes the choice", async () => {
    authenticatedFetchMock.mockResolvedValue(new Response("{}", { status: 200 }));
    renderSidebar([conv("own_row", { labels: { [KEY]: "blocked" } })]);

    openStatusMenu("own_row");
    const items = screen.getAllByRole("menuitem").map((item) => item.dataset.testid);
    expect(items.indexOf("mark-unread-conversation")).toBeLessThan(
      items.indexOf("session-row-menu-acme.status.menu"),
    );
    const blocked = screen.getByTestId("session-row-label-acme.status.menu-blocked");
    expect(blocked).toHaveAttribute("role", "menuitemradio");
    expect(blocked).toHaveAttribute("aria-checked", "true");
    expect(screen.getByTestId("session-row-label-acme.status.menu-done")).toHaveAttribute(
      "aria-checked",
      "false",
    );
    // Value icons carry their tone; Clear uses the item's own wording.
    expect(blocked.querySelector("svg")).toHaveClass("text-status-red!");
    expect(screen.getByTestId("session-row-label-acme.status.menu-clear")).toHaveTextContent(
      "Clear status",
    );

    fireEvent.click(screen.getByTestId("session-row-label-acme.status.menu-done"));
    await waitFor(() => expect(patches()).toHaveLength(1));
    expect(patches()[0][0]).toBe("/v1/sessions/own_row");
    expect(patches()[0][1].body).toBe(JSON.stringify({ labels: { [KEY]: "done" } }));
  });

  it("clears with an empty value, and Clear is disabled with nothing set", async () => {
    authenticatedFetchMock.mockResolvedValue(new Response("{}", { status: 200 }));
    renderSidebar([conv("set_row", { labels: { [KEY]: "done" } }), conv("unset_row")]);

    openStatusMenu("unset_row");
    expect(screen.getByTestId("session-row-label-acme.status.menu-clear")).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    cleanup();

    renderSidebar([conv("set_row", { labels: { [KEY]: "done" } })]);
    openStatusMenu("set_row");
    fireEvent.click(screen.getByTestId("session-row-label-acme.status.menu-clear"));
    await waitFor(() => expect(patches()).toHaveLength(1));
    expect(patches()[0][1].body).toBe(JSON.stringify({ labels: { [KEY]: "" } }));
  });

  it("toasts when the server refuses the write", async () => {
    authenticatedFetchMock.mockImplementation(
      async () =>
        new Response(JSON.stringify({ error: { message: "Access denied" } }), { status: 403 }),
    );
    renderSidebar([conv("own_row")]);

    openStatusMenu("own_row");
    fireEvent.click(screen.getByTestId("session-row-label-acme.status.menu-blocked"));

    await waitFor(() =>
      expect(showToastMock).toHaveBeenCalledWith("Couldn't update Status: Access denied"),
    );
  });

  it.each([
    [1, false],
    [2, true],
    [3, true],
  ])("offers the menu to a sharee at level %s: %s", (level, offered) => {
    renderSidebar([
      conv("shared_row", {
        owner: "other@example.com",
        permission_level: level,
        labels: { [KEY]: "done" },
      }),
    ]);
    showAllSessions();
    // Viewers still see the badge.
    expect(within(row("shared_row")).getByRole("img", { name: "Status: Done" })).toBeTruthy();

    fireEvent.contextMenu(screen.getByRole("link", { name: /shared_row/ }));
    expect(screen.queryByTestId("session-row-menu-acme.status.menu") !== null).toBe(offered);
  });

  it("drops a set-label item whose extension lacks the write permission", () => {
    renderSidebar([conv("own_row")], [{ ...STATUS_EXTENSION, permissions: [] }]);

    fireEvent.pointerDown(within(row("own_row")).getByTestId("conversation-actions"), {
      button: 0,
    });
    expect(screen.getByTestId("mark-unread-conversation")).toBeInTheDocument();
    expect(screen.queryByTestId("session-row-menu-acme.status.menu")).toBeNull();
  });
});
