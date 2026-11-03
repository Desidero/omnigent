// Session-row slots in the sidebar: core's Shared decoration and read-state
// pair, plus an extension's published-field badge and command menu, with
// commands disabled for viewers who lack their access. Only the data hooks
// and the network are mocked.

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
import type { ExtensionCatalogItem, ExtensionCommand, ExtensionSlotItem } from "@/extensions/types";
import { type Conversation, useConversations } from "@/hooks/useConversations";
import { SidebarDataProvider } from "@/hooks/useSidebarData";
import { resetReadStateForTests, seedReadState } from "@/hooks/useUnseenConversations";
import { conversationPage } from "@/test/sidebarMockHelpers";
import { Sidebar } from "./Sidebar";

const EXT = "acme.status";

function rowItem(id: string, slot: ExtensionSlotItem["slot"], kind: ExtensionSlotItem["kind"]) {
  return {
    id: `${EXT}.${id}`,
    slot,
    kind,
    label: "Status",
    page: null,
    icon: null,
    order: 500,
    when: null,
  };
}

const SET: ExtensionCommand = {
  id: `${EXT}.set`,
  title: "Set status",
  arguments: [{ name: "status", choices: ["blocked", "done"], pattern: null, max_length: 64 }],
  required_access: "edit",
  confirm: null,
  action: { type: "set_state", field: "status", value: "{status}" },
};
const CLEAR: ExtensionCommand = {
  id: `${EXT}.clear`,
  title: "Clear status",
  arguments: [],
  required_access: "edit",
  confirm: null,
  action: { type: "clear_state", field: "status", value: null },
};

const STATUS_EXTENSION: ExtensionCatalogItem = {
  object: "extension",
  id: EXT,
  display_name: "Status",
  distribution: "acme-status",
  version: "1.0.0",
  extension_api: 1,
  status: "enabled",
  permissions: [],
  pages: [],
  primary_navigation: [],
  slot_items: [
    {
      ...rowItem("badge", "session.row.decorations", "decoration"),
      binding: { source: "published_field", key: "status" },
    },
    {
      ...rowItem("menu", "session.row.menu", "command"),
      command: SET.id,
      clear_command: CLEAR.id,
    },
  ],
  state_fields: [
    {
      key: "status",
      visibility: "published",
      max_length: 16,
      values: [
        { value: "blocked", label: "Blocked", icon: "octagon-alert", tone: "danger" },
        { value: "done", label: "Done", icon: "circle-check", tone: "success" },
      ],
    },
  ],
  commands: [SET, CLEAR],
  browser: { declared: false, has_styles: false, digest: null, script_url: null, style_url: null },
};

function withCommands(...commands: ExtensionCommand[]): ExtensionCatalogItem {
  return { ...STATUS_EXTENSION, commands };
}

function status(value: string): Partial<Conversation> {
  return { published_fields: { [EXT]: { status: value } } };
}

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

function posts(): [string, RequestInit][] {
  return authenticatedFetchMock.mock.calls.filter(
    (call): call is [string, RequestInit] =>
      (call[1] as RequestInit | undefined)?.method === "POST",
  );
}

function commandResponse(value: string | null): Response {
  return new Response(
    JSON.stringify({
      object: "extension_command_result",
      command: SET.id,
      key: "status",
      entry: null,
      deleted: value === null,
      published_fields: value === null ? {} : { [EXT]: { status: value } },
    }),
    { status: 200 },
  );
}

function row(id: string): HTMLElement {
  return screen.getByRole("link", { name: new RegExp(id) }).closest("li") as HTMLElement;
}

function openStatusMenu(id: string) {
  fireEvent.pointerDown(within(row(id)).getByTestId("conversation-actions"), { button: 0 });
  fireEvent.keyDown(screen.getByTestId(`session-row-menu-${EXT}.menu`), { key: "ArrowRight" });
}

beforeEach(() => {
  resetReadStateForTests();
  authenticatedFetchMock.mockReset();
  showToastMock.mockReset();
});
afterEach(cleanup);

describe("session-row decorations", () => {
  it("follows core's Shared entry with the published value as text and icon", () => {
    renderSidebar([
      conv("shared_row", {
        owner: "other@example.com",
        permission_level: 1,
        ...status("blocked"),
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

  it.each<Partial<Conversation>>([
    {},
    status(""),
    status("bogus"),
    status("constructor"),
    { published_fields: { "acme.other": { status: "done" } } },
    // A label alone is not a published field.
    { labels: { [`ext.${EXT}.status`]: "done" } },
  ])("renders nothing for an absent, empty or unlisted value: %j", (partial) => {
    renderSidebar([conv("own_row", partial)]);
    expect(within(row("own_row")).queryByTestId("session-row-decorations")).toBeNull();
  });

  it("renders no extension items without the catalog", () => {
    renderSidebar([conv("own_row", status("done"))], []);
    expect(within(row("own_row")).queryByRole("img")).toBeNull();
  });
});

describe("session-row menu", () => {
  it("lists the command's choices after core's read-state entry and runs one", async () => {
    authenticatedFetchMock.mockResolvedValue(commandResponse("done"));
    renderSidebar([conv("own_row", status("blocked"))]);

    openStatusMenu("own_row");
    const items = screen.getAllByRole("menuitem").map((item) => item.dataset.testid);
    expect(items.indexOf("mark-unread-conversation")).toBeLessThan(
      items.indexOf(`session-row-menu-${EXT}.menu`),
    );
    const blocked = screen.getByTestId(`session-row-command-${EXT}.menu-blocked`);
    expect(blocked).toHaveAttribute("role", "menuitemradio");
    expect(blocked).toHaveAttribute("aria-checked", "true");
    expect(screen.getByTestId(`session-row-command-${EXT}.menu-done`)).toHaveAttribute(
      "aria-checked",
      "false",
    );
    // Choices carry their field value's tone; the clear entry is its command's title.
    expect(blocked.querySelector("svg")).toHaveClass("text-status-red!");
    expect(screen.getByTestId(`session-row-command-${EXT}.menu-clear`)).toHaveTextContent(
      "Clear status",
    );

    fireEvent.click(screen.getByTestId(`session-row-command-${EXT}.menu-done`));
    await waitFor(() => expect(posts()).toHaveLength(1));
    expect(posts()[0][0]).toBe(`/v1/sessions/own_row/extensions/${EXT}/commands/${SET.id}`);
    expect(posts()[0][1].body).toBe(JSON.stringify({ arguments: { status: "done" } }));
  });

  it("runs the clear command, which is disabled with nothing set", async () => {
    authenticatedFetchMock.mockResolvedValue(commandResponse(null));
    renderSidebar([conv("unset_row")]);

    openStatusMenu("unset_row");
    expect(screen.getByTestId(`session-row-command-${EXT}.menu-clear`)).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    cleanup();

    renderSidebar([conv("set_row", status("done"))]);
    openStatusMenu("set_row");
    fireEvent.click(screen.getByTestId(`session-row-command-${EXT}.menu-clear`));
    await waitFor(() => expect(posts()).toHaveLength(1));
    expect(posts()[0][0]).toBe(`/v1/sessions/set_row/extensions/${EXT}/commands/${CLEAR.id}`);
    expect(posts()[0][1].body).toBe(JSON.stringify({ arguments: {} }));
  });

  it("asks first when the command declares a confirm prompt", async () => {
    authenticatedFetchMock.mockResolvedValue(commandResponse("done"));
    renderSidebar(
      [conv("own_row")],
      [withCommands({ ...SET, confirm: "Mark this session done?" }, CLEAR)],
    );

    openStatusMenu("own_row");
    fireEvent.click(screen.getByTestId(`session-row-command-${EXT}.menu-done`));
    expect(await screen.findByText("Mark this session done?")).toBeInTheDocument();
    expect(posts()).toHaveLength(0);

    fireEvent.click(screen.getByTestId("extension-command-confirm"));
    await waitFor(() => expect(posts()).toHaveLength(1));
  });

  it("toasts when the server refuses the command", async () => {
    authenticatedFetchMock.mockImplementation(
      async () =>
        new Response(JSON.stringify({ error: { message: "Access denied" } }), { status: 403 }),
    );
    renderSidebar([conv("own_row")]);

    openStatusMenu("own_row");
    fireEvent.click(screen.getByTestId(`session-row-command-${EXT}.menu-blocked`));

    await waitFor(() =>
      expect(showToastMock).toHaveBeenCalledWith("Couldn't run Set status: Access denied"),
    );
  });

  it.each([
    [1, true],
    [2, false],
    [3, false],
  ])("disables edit commands for a sharee at level %s: %s", (level, disabled) => {
    renderSidebar([
      conv("shared_row", {
        owner: "other@example.com",
        permission_level: level,
        ...status("done"),
      }),
    ]);
    showAllSessions();
    // Viewers still see the badge.
    expect(within(row("shared_row")).getByRole("img", { name: "Status: Done" })).toBeTruthy();

    fireEvent.contextMenu(screen.getByRole("link", { name: /shared_row/ }));
    const trigger = screen.getByTestId(`session-row-menu-${EXT}.menu`);
    expect(trigger.getAttribute("aria-disabled") === "true").toBe(disabled);
  });

  it("runs a command without arguments as a plain entry, open to readers when it says so", async () => {
    authenticatedFetchMock.mockResolvedValue(commandResponse(null));
    const stop = { ...CLEAR, id: `${EXT}.stop`, title: "Stop", required_access: "read" as const };
    renderSidebar(
      [conv("shared_row", { owner: "other@example.com", permission_level: 1 })],
      [
        {
          ...withCommands(stop),
          slot_items: [{ ...rowItem("menu", "session.row.menu", "command"), command: stop.id }],
        },
      ],
    );
    showAllSessions();

    fireEvent.contextMenu(screen.getByRole("link", { name: /shared_row/ }));
    const entry = screen.getByTestId(`session-row-menu-${EXT}.menu`);
    expect(entry).not.toHaveAttribute("aria-disabled");
    fireEvent.click(entry);
    await waitFor(() => expect(posts()).toHaveLength(1));
    expect(posts()[0][0]).toBe(`/v1/sessions/shared_row/extensions/${EXT}/commands/${stop.id}`);
  });

  it("drops an item whose command the catalog doesn't list", () => {
    renderSidebar([conv("own_row")], [withCommands(CLEAR)]);

    fireEvent.pointerDown(within(row("own_row")).getByTestId("conversation-actions"), {
      button: 0,
    });
    expect(screen.getByTestId("mark-unread-conversation")).toBeInTheDocument();
    expect(screen.queryByTestId(`session-row-menu-${EXT}.menu`)).toBeNull();
  });
});
