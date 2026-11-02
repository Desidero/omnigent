import type {
  ExtensionContext,
  ExtensionPullRequest,
  ExtensionSessionSummary,
} from "@omnigent/extension-sdk";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mountReview, type ReviewPage } from "./review";

function summary(overrides: Partial<ExtensionSessionSummary> = {}): ExtensionSessionSummary {
  return {
    id: "conv-a",
    title: "Add CSV export",
    status: "idle",
    unread: false,
    titleProvisional: false,
    workspace: "/work",
    gitBranch: "feat/csv",
    projectId: "proj-1",
    createdAt: 1_700_000_000,
    updatedAt: 1_700_000_000,
    ...overrides,
  };
}

function unavailableStorage(): ExtensionContext["storage"]["user"] {
  const fail = () => Promise.reject(Object.assign(new Error("IndexedDB is unavailable"), { code: "Unavailable" }));
  return { get: fail, set: fail, delete: fail };
}

function memoryStorage(): ExtensionContext["storage"]["user"] {
  const values = new Map<string, unknown>();
  return {
    get: async <T>(key: string) => (values.get(key) as T | undefined) ?? null,
    set: async (key, value) => void values.set(key, value),
    delete: async (key) => void values.delete(key),
  };
}

function stubContext(options: {
  conversationId?: string;
  sessions?: ExtensionSessionSummary[];
  pullRequest?: ExtensionPullRequest | null | Error;
  storage?: ExtensionContext["storage"]["user"];
}) {
  const sessions = options.sessions ?? [summary()];
  const navigation = {
    openPage: vi.fn(async () => {}),
    openSession: vi.fn(async () => {}),
    openNewSession: vi.fn(async () => {}),
    openExternal: vi.fn(async () => {}),
  };
  const context: ExtensionContext = {
    extensionId: "omnigent.review-checklist",
    pageId: "omnigent.review-checklist.review",
    view: "review",
    apiVersion: 1,
    capabilities: [],
    invocation: options.conversationId ? { conversationId: options.conversationId } : {},
    navigation,
    theme: {
      getCurrent: async () => ({ theme: "light" }),
      subscribe: async () => ({ dispose() {} }),
    },
    storage: { user: options.storage ?? memoryStorage() },
    sessions: {
      getCached: async () => null,
      listPage: async () => ({ sessions, nextCursor: null, hasMore: false }),
      listAll: async () => sessions,
      get: vi.fn(async (id: string) => sessions.find((session) => session.id === id) ?? null),
      pullRequest: vi.fn(async () => {
        if (options.pullRequest instanceof Error) throw options.pullRequest;
        return options.pullRequest ?? null;
      }),
    },
    projects: {
      list: async () => [{ id: "proj-1", name: "Storefront", icon: null }],
      create: async () => {
        throw new Error("not used");
      },
    },
    // The checklist keeps no session state of its own.
    commands: {
      invoke: async () => {
        throw new Error("not used");
      },
    },
    state: {
      get: async () => null,
      list: async () => ({ entries: [], nextAfter: null }),
    },
  };
  return { context, navigation };
}

let page: ReviewPage | null = null;

async function mount(context: ExtensionContext) {
  document.body.innerHTML = '<div id="root"></div>';
  const root = document.getElementById("root")!;
  page = await mountReview(root, context, () => 1_700_000_000_000 + 120_000);
  await vi.waitFor(() => expect(root.querySelector("#pull-request")?.textContent).not.toContain("Checking"));
  return root;
}

afterEach(() => {
  page?.dispose();
  page = null;
});

describe("review page", () => {
  it("names the session and summarises its pull request", async () => {
    const { context, navigation } = stubContext({
      conversationId: "conv-a",
      pullRequest: { number: 480, title: "Add CSV export", state: "open", url: "https://github.com/acme/shop/pull/480" },
    });
    const root = await mount(context);
    expect(root.querySelector("#session-title")?.textContent).toBe("Add CSV export");
    expect(root.querySelector("[data-testid=status-chip]")?.textContent).toContain("Idle");
    expect(root.textContent).toContain("Storefront");
    expect(root.textContent).toContain("feat/csv");
    expect(root.querySelector("#session-id")?.textContent).toBe("conv-a");
    expect(root.querySelector("#pull-request")?.textContent).toContain("#480 · Add CSV export · open");
    expect(root.querySelector("#progress")?.textContent).toBe("0 of 11 checked");
    expect(root.querySelector("#template-source")?.textContent).toBe("From: Your default");
    expect(root.querySelector("#storage-notice")?.textContent).toContain("Saved in this browser only");

    [...root.querySelectorAll("button")].find((node) => node.textContent === "Open pull request")!.click();
    expect(navigation.openExternal).toHaveBeenCalledWith("https://github.com/acme/shop/pull/480");
  });

  it("says when the branch has no pull request and the agent is still running", async () => {
    const { context } = stubContext({ conversationId: "conv-a", sessions: [summary({ status: "running" })] });
    const root = await mount(context);
    expect(root.querySelector("#pull-request")?.textContent).toBe("No pull request found for this session's branch");
    expect(root.querySelector("#banner")?.textContent).toContain("The agent is still working.");
    expect(root.querySelector("[data-testid=status-chip]")?.textContent).toContain("Running");
  });

  it("says a failed pull request lookup in plain words, without the host's message", async () => {
    const failure = Object.assign(new Error("runner tunnel 502: upstream connect error"), { code: "Unavailable" });
    const { context } = stubContext({ conversationId: "conv-a", pullRequest: failure });
    const root = await mount(context);
    const line = root.querySelector("#pull-request")?.textContent ?? "";
    expect(line).toBe("Couldn't check for a pull request right now. The session's host may be offline; try Refresh.");
    expect(line).not.toContain("502");
  });

  it("skips the pull request lookup when the session has no branch", async () => {
    const { context } = stubContext({ conversationId: "conv-a", sessions: [summary({ gitBranch: null })] });
    const root = await mount(context);
    expect(root.querySelector("#pull-request")?.textContent).toBe("No branch to check for a pull request");
    expect(context.sessions.pullRequest).not.toHaveBeenCalled();
  });

  it("keeps a session's template choice and ticks to that session", async () => {
    const storage = memoryStorage();
    const sessions = [summary(), summary({ id: "conv-b", title: "Fix login" })];
    const first = stubContext({ conversationId: "conv-a", sessions, storage }).context;
    let root = await mount(first);
    const select = root.querySelector<HTMLSelectElement>("#template-select")!;
    select.value = "builtin.pull-request-ready";
    select.dispatchEvent(new Event("change"));
    expect(root.querySelector("#template-source")?.textContent).toBe("From: Chosen for this session");
    root.querySelector<HTMLInputElement>("input[type=checkbox]")!.click();
    expect(root.querySelector("#progress")?.textContent).toBe("1 of 6 checked");
    page!.dispose();
    page = null;
    await vi.waitFor(async () => expect(await storage.get("progress.v1")).toHaveProperty("conv-a"));

    // Another session in the same project keeps the default and has no ticks.
    root = await mount(stubContext({ conversationId: "conv-b", sessions, storage }).context);
    expect(root.querySelector<HTMLSelectElement>("#template-select")?.value).toBe("builtin.agent-change-review");
    expect(root.querySelector("#template-source")?.textContent).toBe("From: Your default");
    expect(root.querySelector("#progress")?.textContent).toBe("0 of 11 checked");
    page!.dispose();
    page = null;

    root = await mount(stubContext({ conversationId: "conv-a", sessions, storage }).context);
    expect(root.querySelector<HTMLSelectElement>("#template-select")?.value).toBe("builtin.pull-request-ready");
    expect(root.querySelector("#progress")?.textContent).toBe("1 of 6 checked");
  });

  it("reads the session by id, so one the list leaves out still loads", async () => {
    const { context } = stubContext({
      conversationId: "conv-child",
      sessions: [summary({ id: "conv-child", title: "Sub-agent: run the tests" })],
    });
    const listAll = vi.spyOn(context.sessions, "listAll");
    const root = await mount(context);
    expect(context.sessions.get).toHaveBeenCalledWith("conv-child");
    expect(listAll).not.toHaveBeenCalled();
    expect(root.querySelector("#session-title")?.textContent).toBe("Sub-agent: run the tests");
  });

  it("says the session isn't available when the viewer can't read it", async () => {
    const { context } = stubContext({ conversationId: "conv-hidden" });
    document.body.innerHTML = '<div id="root"></div>';
    const root = document.getElementById("root")!;
    page = await mountReview(root, context);
    expect(root.querySelector("#unavailable")?.textContent).toBe(
      "This session isn't available here. It may have been deleted, or it isn't shared with you.",
    );
  });

  it("keeps both sessions' ticks when two open pages save", async () => {
    const storage = memoryStorage();
    const sessions = [summary(), summary({ id: "conv-b", title: "Fix login" })];
    document.body.innerHTML = '<div id="page-a"></div><div id="page-b"></div>';
    const rootA = document.getElementById("page-a")!;
    const rootB = document.getElementById("page-b")!;
    // Both pages load before either one saves.
    const pageA = await mountReview(rootA, stubContext({ conversationId: "conv-a", sessions, storage }).context);
    const pageB = await mountReview(rootB, stubContext({ conversationId: "conv-b", sessions, storage }).context);

    rootA.querySelector<HTMLInputElement>("input[type=checkbox]")!.click();
    pageA.dispose();
    await vi.waitFor(async () => expect(await storage.get("progress.v1")).toHaveProperty("conv-a"));
    rootB.querySelector<HTMLInputElement>("input[type=checkbox]")!.click();
    pageB.dispose();
    await vi.waitFor(async () => expect(await storage.get("progress.v1")).toHaveProperty("conv-b"));

    const stored = await storage.get<Record<string, { c: string[] }>>("progress.v1");
    expect(stored?.["conv-a"]?.c).toHaveLength(1);
    expect(stored?.["conv-b"]?.c).toHaveLength(1);
  });

  it("treats an untrusted id as text and stores nothing for it", async () => {
    const storage = memoryStorage();
    const set = vi.spyOn(storage, "set");
    const { context } = stubContext({ conversationId: "<img src=x onerror=alert(1)>", storage });
    document.body.innerHTML = '<div id="root"></div>';
    const root = document.getElementById("root")!;
    page = await mountReview(root, context);
    expect(root.querySelector("#unavailable")?.textContent).toContain("This session isn't available here.");
    expect(root.querySelector("img")).toBeNull();
    expect(set).not.toHaveBeenCalled();
  });

  it("keeps working in memory when browser storage is unavailable", async () => {
    const { context } = stubContext({ conversationId: "conv-a", storage: unavailableStorage() });
    const root = await mount(context);
    expect(root.querySelector("#storage-notice")?.textContent).toContain("Can't save in this browser");
    const box = root.querySelector<HTMLInputElement>("input[type=checkbox]")!;
    box.click();
    expect(root.querySelector("#progress")?.textContent).toBe("1 of 11 checked");
  });

  it("offers recent sessions when opened without a session", async () => {
    const { context, navigation } = stubContext({});
    document.body.innerHTML = '<div id="root"></div>';
    const root = document.getElementById("root")!;
    page = await mountReview(root, context);
    expect(root.textContent).toContain("Open the review checklist from a session's header or composer.");
    const open = await vi.waitFor(() => {
      const found = root.querySelector<HTMLButtonElement>("button[aria-label='Open session Add CSV export']");
      expect(found).not.toBeNull();
      return found!;
    });
    open.click();
    expect(navigation.openSession).toHaveBeenCalledWith("conv-a");
  });
});
