// The "Start a new session in…" prompt as the app shell mounts it: a picker on desktop, a
// bottom sheet on phones, and where each choice starts the session.

import {
  act,
  cleanup,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useNewSessionHotkey } from "@/hooks/useNewSessionHotkey";
import { writeNewChatProjectPromptEnabled } from "@/lib/newChatProjectPromptPreferences";
import { useProjectComposerStore } from "@/projectHome/ProjectHomeHeader";
import {
  askForProjectOnNewSessionClick,
  startNewSession,
  useNewSessionProjectPromptStore,
} from "@/store/newSessionProjectPrompt";

import { useAppCommands } from "./appCommands";
import { NewSessionProjectPrompt, projectInView } from "./NewSessionProjectPrompt";

const navigate = vi.fn();
const location = { pathname: "/c/conv_1", search: "" };
vi.mock("@/lib/routing", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  useNavigate: () => navigate,
  useLocation: () => ({ ...location, hash: "", state: null, key: "default" }),
}));

const useProjects = vi.fn();
vi.mock("@/hooks/useConversations", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  useProjects: () => useProjects(),
}));

let mobile = false;
vi.mock("@/hooks/useIsMobileViewport", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  useIsMobileViewport: () => mobile,
}));

const PROJECTS = [
  { id: "p1", name: "omnigent", icon: "🔥" },
  { id: null, name: "docs site", icon: null },
];
const loaded = (data: unknown[]) => ({ data, isError: false });

const closePalette = vi.fn();
function renderPrompt(paletteOpen = false) {
  const view = render(
    <NewSessionProjectPrompt paletteOpen={paletteOpen} closePalette={closePalette} />,
  );
  return {
    openPalette: () =>
      view.rerender(<NewSessionProjectPrompt paletteOpen closePalette={closePalette} />),
  };
}
const ask = () => act(() => startNewSession(navigate));
const promptOpen = () => useNewSessionProjectPromptStore.getState().open;
const input = () => screen.getByTestId("new-session-project-input");
const rowLabels = () =>
  screen.getAllByRole("option").map((row) => row.querySelector(".truncate")?.textContent);

// The three ways to start a new session, each through its real handler.
const ENTRY_POINTS = [
  [
    "the new-session shortcut",
    () => {
      renderHook(() => useNewSessionHotkey(true, false));
      act(() => {
        fireEvent.keyDown(window, { key: "O", code: "KeyO", ctrlKey: true, shiftKey: true });
      });
    },
  ],
  [
    "a sidebar New session link",
    () => {
      // Follows its href as a router link does, unless the prompt takes the click.
      render(
        <a
          href="/"
          onClick={(event) => {
            askForProjectOnNewSessionClick(event);
            if (event.defaultPrevented) return;
            event.preventDefault();
            navigate("/");
          }}
        >
          New session
        </a>,
      );
      act(() => {
        fireEvent.click(screen.getByRole("link", { name: "New session" }));
      });
    },
  ],
  [
    "the palette's New chat",
    () => {
      const { result } = renderHook(() =>
        useAppCommands({
          onToggleLeftSidebar: vi.fn(),
          onToggleRightSidebar: vi.fn(),
          rightSidebarShortcutEnabled: true,
        }),
      );
      act(() => result.current.find((command) => command.id === "new-chat")!.run());
    },
  ],
] as const;

beforeEach(() => {
  mobile = false;
  location.pathname = "/c/conv_1";
  location.search = "";
  navigate.mockReset();
  closePalette.mockReset();
  useProjects.mockReturnValue(loaded(PROJECTS));
  useProjectComposerStore.setState({ open: false });
});
afterEach(() => {
  cleanup();
  localStorage.clear();
});

describe("projectInView", () => {
  it("names the project whose home or composer is open", () => {
    expect(projectInView("/projects/docs%20site", "")).toBe("docs site");
    expect(projectInView("/", "?project=omnigent")).toBe("omnigent");
    expect(projectInView("/c/conv_1", "")).toBeNull();
  });
});

describe("NewSessionProjectPrompt on desktop", () => {
  it("lists No project, then every project, and closes the palette it replaces", () => {
    renderPrompt();
    expect(screen.queryByRole("dialog")).toBeNull();

    ask();

    expect(rowLabels()).toEqual(["No project", "omnigent", "docs site"]);
    expect(input()).toHaveAttribute("placeholder", "Start a new session in…");
    expect(closePalette).toHaveBeenCalled();
    expect(navigate).not.toHaveBeenCalled();
  });

  it("starts the session in the project picked by name", async () => {
    renderPrompt();
    ask();
    fireEvent.change(input(), { target: { value: "docs" } });
    expect(rowLabels()).toEqual(["docs site"]);
    fireEvent.keyDown(input(), { key: "Enter" });

    await waitFor(() => expect(navigate).toHaveBeenCalledExactlyOnceWith("/?project=docs%20site"));
    expect(promptOpen()).toBe(false);
  });

  it("opens the plain composer for No project, the top row", async () => {
    renderPrompt();
    ask();
    fireEvent.keyDown(input(), { key: "Enter" });

    await waitFor(() => expect(navigate).toHaveBeenCalledExactlyOnceWith("/"));
  });

  it("starts on the project in view, so Enter keeps the session there", async () => {
    location.pathname = "/";
    location.search = "?project=docs%20site";
    renderPrompt();
    ask();

    const current = screen.getByRole("option", { name: /docs site/ });
    await waitFor(() => expect(current).toHaveAttribute("aria-selected", "true"));
    expect(current).toHaveTextContent("Current project");
    fireEvent.keyDown(input(), { key: "Enter" });

    await waitFor(() => expect(navigate).toHaveBeenCalledExactlyOnceWith("/?project=docs%20site"));
  });

  it.each(ENTRY_POINTS)(
    "starts from %s on a project's home in its composer, without asking",
    (_entry, startFromEntryPoint) => {
      location.pathname = "/projects/omnigent";
      renderPrompt();
      startFromEntryPoint();

      expect(screen.queryByRole("dialog")).toBeNull();
      expect(promptOpen()).toBe(false);
      expect(useProjectComposerStore.getState().open).toBe(true);
      expect(navigate).not.toHaveBeenCalled();
    },
  );

  it.each(ENTRY_POINTS)(
    "asks from %s away from a project's home",
    (_entry, startFromEntryPoint) => {
      renderPrompt();
      startFromEntryPoint();

      expect(rowLabels()).toEqual(["No project", "omnigent", "docs site"]);
      expect(navigate).not.toHaveBeenCalled();
    },
  );

  it.each(ENTRY_POINTS)(
    "opens the plain composer from %s on a project's home with the prompt off",
    (_entry, startFromEntryPoint) => {
      writeNewChatProjectPromptEnabled(false);
      location.pathname = "/projects/omnigent";
      renderPrompt();
      startFromEntryPoint();

      expect(screen.queryByRole("dialog")).toBeNull();
      expect(useProjectComposerStore.getState().open).toBe(false);
      expect(navigate).toHaveBeenCalledExactlyOnceWith("/");
    },
  );

  it("starts on a project's home without waiting for the project list", () => {
    useProjects.mockReturnValue({ data: undefined, isError: false });
    location.pathname = "/projects/omnigent";
    renderPrompt();
    ask();

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(useProjectComposerStore.getState().open).toBe(true);
  });

  it("lists projects as they arrive when it opens before the list has loaded", () => {
    useProjects.mockReturnValue({ data: undefined, isError: false });
    const view = render(
      <NewSessionProjectPrompt paletteOpen={false} closePalette={closePalette} />,
    );
    ask();

    expect(rowLabels()).toEqual(["No project"]);
    expect(screen.getByText("Loading projects…")).toBeTruthy();

    useProjects.mockReturnValue(loaded(PROJECTS));
    view.rerender(<NewSessionProjectPrompt paletteOpen={false} closePalette={closePalette} />);
    expect(rowLabels()).toEqual(["No project", "omnigent", "docs site"]);
  });

  it.each([
    ["has no project", loaded([])],
    ["failed to load", { data: undefined, isError: true }],
  ])("steps aside for the plain composer when the list %s", (_case, projects) => {
    useProjects.mockReturnValue(projects);
    renderPrompt();
    ask();

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(promptOpen()).toBe(false);
    expect(navigate).toHaveBeenCalledExactlyOnceWith("/");
  });

  it("closes without starting anything on Escape", () => {
    renderPrompt();
    ask();
    fireEvent.keyDown(input(), { key: "Escape" });

    expect(promptOpen()).toBe(false);
    expect(navigate).not.toHaveBeenCalled();
  });

  it("gives way to the command palette opening over it", () => {
    const { openPalette } = renderPrompt();
    ask();
    openPalette();

    expect(promptOpen()).toBe(false);
  });

  it("stops asking once the shell unmounts it", () => {
    renderPrompt();
    cleanup();
    startNewSession(navigate);

    expect(promptOpen()).toBe(false);
    expect(navigate).toHaveBeenCalledExactlyOnceWith("/");
  });
});

describe("NewSessionProjectPrompt on phones", () => {
  beforeEach(() => {
    mobile = true;
  });

  it("asks in a sheet with no search field and marks the project in view", () => {
    location.pathname = "/";
    location.search = "?project=omnigent";
    renderPrompt();
    ask();

    const sheet = screen.getByRole("dialog", { name: "Start a new session in" });
    expect(sheet.querySelector("input")).toBeNull();
    const rows = screen.getAllByRole("button").map((row) => row.textContent);
    expect(rows).toEqual(["No project", "🔥omnigentCurrent", "docs site"]);
    expect(screen.getByRole("button", { name: /omnigent/ })).toHaveAttribute(
      "aria-current",
      "true",
    );
  });

  it("opens the composer for the tapped project", () => {
    renderPrompt();
    ask();
    fireEvent.click(screen.getByRole("button", { name: /omnigent/ }));

    expect(navigate).toHaveBeenCalledExactlyOnceWith("/?project=omnigent");
    expect(promptOpen()).toBe(false);
  });

  it("opens a project home's project in the composer without asking", () => {
    location.pathname = "/projects/omnigent";
    renderPrompt();
    ask();

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(navigate).toHaveBeenCalledExactlyOnceWith("/?project=omnigent");
    expect(useProjectComposerStore.getState().open).toBe(false);
    expect(promptOpen()).toBe(false);
  });

  it("opens the plain composer for No project", () => {
    renderPrompt();
    ask();
    fireEvent.click(screen.getByRole("button", { name: "No project" }));

    expect(navigate).toHaveBeenCalledExactlyOnceWith("/");
  });
});
