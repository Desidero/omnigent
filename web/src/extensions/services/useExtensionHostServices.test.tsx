import "fake-indexeddb/auto";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RunnerOfflineError } from "@/hooks/useWorkspaceChangedFiles";
import { FALLBACK_SERVER_INFO } from "@/lib/capabilities";
import { CapabilitiesProvider } from "@/lib/CapabilitiesContext";
import type { ExtensionCatalogItem } from "../types";
import { HOST_METHOD_PERMISSIONS } from "./registry";
import { resetExtensionStorageForTests } from "./storage";

const { navigate, identityRef, serverRef, authenticatedFetchMock } = vi.hoisted(() => ({
  navigate: vi.fn(),
  authenticatedFetchMock: vi.fn(),
  identityRef: { current: "user@example.com" as string | null },
  serverRef: { current: "server-a" as string | null },
}));
vi.mock("@/lib/routing", () => ({ useNavigate: () => navigate }));
vi.mock("@/lib/identity", () => ({
  authenticatedFetch: authenticatedFetchMock,
  resolveIdentity: async () => identityRef.current,
}));
vi.mock("@/lib/host", () => ({ getOmnigentServerIdentity: () => serverRef.current }));
vi.mock("next-themes", () => ({ useTheme: () => ({ resolvedTheme: "dark" }) }));

import { useExtensionHostServices } from "./useExtensionHostServices";

const extension: ExtensionCatalogItem = {
  object: "extension",
  id: "acme.review",
  display_name: "Review",
  distribution: "acme-review",
  version: "1.0.0",
  extension_api: 1,
  status: "enabled",
  permissions: ["navigation", "projects.read", "projects.write", "sessions.read", "storage.user"],
  pages: [
    {
      id: "acme.review.dashboard",
      title: "Dashboard",
      route: "dashboard",
      view: "dashboard",
    },
  ],
  primary_navigation: [],
  slot_items: [],
  commands: [
    {
      id: "acme.review.watch",
      title: "Watch",
      arguments: [{ name: "pr", choices: [], pattern: "[0-9]+", max_length: 8 }],
      required_access: "read",
      confirm: null,
      action: { type: "set_state", field: "pr:*", value: "watching" },
    },
  ],
  browser: {
    declared: true,
    has_styles: false,
    digest: "digest",
    script_url: "/script",
    style_url: null,
  },
};
const signal = () => new AbortController().signal;
const queryClient = new QueryClient();
const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
);

beforeEach(async () => {
  navigate.mockReset();
  authenticatedFetchMock.mockReset();
  queryClient.clear();
  identityRef.current = "user@example.com";
  serverRef.current = "server-a";
  await resetExtensionStorageForTests();
});

describe("useExtensionHostServices", () => {
  it("declares a permission rule for every exposed host method", () => {
    const { result } = renderHook(() => useExtensionHostServices(extension), { wrapper });
    expect(Object.keys(result.current.methods).sort()).toEqual(
      Object.keys(HOST_METHOD_PERMISSIONS).sort(),
    );
  });

  it("routes only to pages owned by the extension and preserves params", () => {
    const { result } = renderHook(() => useExtensionHostServices(extension), { wrapper });
    act(() => {
      result.current.methods["navigation.openPage"]?.(
        { pageId: "acme.review.dashboard", params: { tab: "files" } },
        signal(),
      );
    });
    expect(navigate).toHaveBeenCalledWith({
      pathname: "/extensions/acme.review/dashboard",
      search: "?tab=files",
    });

    expect(() =>
      result.current.methods["navigation.openPage"]?.({ pageId: "other.page" }, signal()),
    ).toThrow("Page is not owned by extension");
  });

  it("opens sessions and the new-session page through parent routing", () => {
    const { result } = renderHook(() => useExtensionHostServices(extension), { wrapper });
    act(() => {
      result.current.methods["navigation.openSession"]?.({ sessionId: "conv_123" }, signal());
      result.current.methods["navigation.openNewSession"]?.({}, signal());
    });

    expect(navigate).toHaveBeenNthCalledWith(1, "/c/conv_123");
    expect(navigate).toHaveBeenNthCalledWith(2, "/");
  });

  it("returns theme snapshots and emits theme state", () => {
    const { result } = renderHook(() => useExtensionHostServices(extension), { wrapper });

    expect(result.current.methods["theme.getCurrent"]?.({}, signal())).toEqual({ theme: "dark" });
    expect(result.current.events).toEqual({ "theme.changed": { theme: "dark" } });
  });

  it("lists only the projected session summary through the host method", async () => {
    authenticatedFetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          data: [
            {
              id: "conv_1",
              title: "One",
              status: "idle",
              workspace: "/workspace",
              created_at: 1,
              updated_at: 2,
              owner: "hidden",
            },
          ],
          has_more: false,
          last_id: "conv_1",
        }),
        { status: 200 },
      ),
    );
    const { result } = renderHook(() => useExtensionHostServices(extension), { wrapper });

    await expect(result.current.methods["sessions.listPage"]?.({}, signal())).resolves.toEqual({
      sessions: [
        {
          id: "conv_1",
          title: "One",
          status: "idle",
          titleProvisional: false,
          unread: false,
          workspace: "/workspace",
          gitBranch: null,
          projectId: null,
          createdAt: 1,
          updatedAt: 2,
        },
      ],
      nextCursor: null,
      hasMore: false,
    });
  });

  it("reads one session by id as the viewer, without its transcript", async () => {
    authenticatedFetchMock
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            id: "conv_1",
            agent_id: "agent",
            title: "Archived child",
            status: "idle",
            created_at: 1,
            updated_at: null,
            archived: true,
            parent_session_id: "conv_0",
            labels: { hidden: "yes" },
            items: [],
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(new Response("{}", { status: 404 }));
    const { result } = renderHook(() => useExtensionHostServices(extension), { wrapper });

    await expect(
      result.current.methods["sessions.get"]?.({ sessionId: "conv_1" }, signal()),
    ).resolves.toEqual({
      id: "conv_1",
      title: "Archived child",
      status: "idle",
      titleProvisional: false,
      unread: false,
      workspace: null,
      gitBranch: null,
      projectId: null,
      createdAt: 1,
      updatedAt: 1,
    });
    expect(authenticatedFetchMock.mock.calls[0][0]).toBe(
      "/v1/sessions/conv_1?include_items=false&include_liveness=false&include_usage=false",
    );
    await expect(
      result.current.methods["sessions.get"]?.({ sessionId: "conv_gone" }, signal()),
    ).resolves.toBeNull();
    await expect(
      result.current.methods["sessions.get"]?.({ sessionId: "" }, signal()),
    ).rejects.toThrow("sessionId is invalid");
  });

  it("exposes a cached preview separately from canonical session pages", async () => {
    queryClient.setQueryData(["conversations", "", true], {
      pages: [
        {
          data: [
            {
              id: "conv_cached",
              title: "Cached",
              status: "idle",
              workspace: "/workspace",
              created_at: 1,
              updated_at: 2,
              archived: false,
            },
          ],
          has_more: true,
          last_id: "conv_cached",
        },
      ],
      pageParams: [undefined],
    });
    queryClient.setQueryData(
      ["projects"],
      [
        { id: "proj_1", name: "Alpha", icon: "🅰️" },
        { id: null, name: "Legacy", icon: null },
      ],
    );
    authenticatedFetchMock.mockResolvedValue(
      new Response(JSON.stringify({ data: [], has_more: false, last_id: null }), {
        status: 200,
      }),
    );
    const { result } = renderHook(() => useExtensionHostServices(extension), {
      wrapper,
    });

    expect(result.current.methods["sessions.getCached"]?.({}, signal())).toMatchObject([
      { id: "conv_cached", title: "Cached" },
    ]);
    expect(result.current.methods["projects.list"]?.({}, signal())).toEqual([
      { id: "proj_1", name: "Alpha", icon: "🅰️" },
    ]);
    expect(authenticatedFetchMock).not.toHaveBeenCalled();

    await result.current.methods["sessions.listPage"]?.({}, signal());
    expect(authenticatedFetchMock).toHaveBeenCalledOnce();
  });

  it.each([true, false])(
    "paginates from the server when a cache with has_more=%s has gaps",
    async (hasMore) => {
      const rows = ["a", "b", "c", "d"].map((id, index) => ({
        id,
        title: id,
        status: "idle",
        created_at: 1,
        updated_at: 4 - index,
      }));
      queryClient.setQueryData(["conversations", "", true], {
        pages: [{ data: [rows[0], rows[3]], has_more: hasMore, last_id: "d" }],
        pageParams: [undefined],
      });
      authenticatedFetchMock.mockImplementation(async (url: string) => {
        const after = new URL(url, "http://localhost").searchParams.get("after");
        const start = after ? rows.findIndex((row) => row.id === after) + 1 : 0;
        const data = rows.slice(start, start + 2);
        return new Response(
          JSON.stringify({
            data,
            has_more: start + data.length < rows.length,
            last_id: data.at(-1)?.id ?? null,
          }),
        );
      });
      const { result } = renderHook(() => useExtensionHostServices(extension), { wrapper });

      expect(
        await result.current.methods["sessions.listPage"]?.({ limit: 2 }, signal()),
      ).toMatchObject({
        sessions: [{ id: "a" }, { id: "b" }],
        nextCursor: "b",
        hasMore: true,
      });
      expect(
        await result.current.methods["sessions.listPage"]?.({ after: "b", limit: 2 }, signal()),
      ).toMatchObject({
        sessions: [{ id: "c" }, { id: "d" }],
        nextCursor: null,
        hasMore: false,
      });
      expect(authenticatedFetchMock).toHaveBeenCalledTimes(2);
    },
  );

  it("does not read the cache after cancellation", () => {
    const { result } = renderHook(() => useExtensionHostServices(extension), { wrapper });
    const controller = new AbortController();
    controller.abort();
    expect(() => result.current.methods["sessions.getCached"]?.({}, controller.signal)).toThrow(
      "Host operation cancelled",
    );
    expect(authenticatedFetchMock).not.toHaveBeenCalled();
  });

  it("opens a project-scoped new session by resolving the project name", async () => {
    const projects = new Response(
      JSON.stringify({ object: "list", data: [{ id: "p1", name: "Alpha & co" }] }),
      { status: 200 },
    );
    authenticatedFetchMock.mockResolvedValueOnce(projects).mockResolvedValueOnce(projects.clone());
    const { result } = renderHook(() => useExtensionHostServices(extension), { wrapper });

    await result.current.methods["navigation.openNewSession"]?.({ projectId: "p1" }, signal());
    expect(navigate).toHaveBeenCalledWith({ pathname: "/", search: "?project=Alpha%20%26%20co" });
    await expect(
      result.current.methods["navigation.openNewSession"]?.({ projectId: "missing" }, signal()),
    ).rejects.toMatchObject({ code: "InvalidParams", message: "Project not found" });
  });

  it("returns a session's pull request and only opens URLs it handed out", async () => {
    authenticatedFetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          object: "session.github.info",
          available: true,
          pr: {
            number: 42,
            title: "Add canvas",
            state: "OPEN",
            url: "https://github.com/acme/repo/pull/42",
            is_draft: false,
            author: "me",
            base_ref: "main",
            head_ref: "feat",
            checks: { passing: 0, failing: 0, pending: 0, total: 0, runs: [] },
          },
        }),
        { status: 200 },
      ),
    );
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    const { result } = renderHook(() => useExtensionHostServices(extension), { wrapper });

    await expect(
      result.current.methods["navigation.openExternal"]?.(
        { url: "https://github.com/acme/repo/pull/42" },
        signal(),
      ),
    ).rejects.toMatchObject({ code: "PermissionDenied" });

    await expect(
      result.current.methods["sessions.pullRequest"]?.({ sessionId: "conv_1" }, signal()),
    ).resolves.toEqual({
      number: 42,
      title: "Add canvas",
      state: "OPEN",
      url: "https://github.com/acme/repo/pull/42",
    });
    expect(authenticatedFetchMock.mock.calls[0][0]).toBe("/v1/sessions/conv_1/resources/github");

    await result.current.methods["navigation.openExternal"]?.(
      { url: "https://github.com/acme/repo/pull/42" },
      signal(),
    );
    expect(open).toHaveBeenCalledWith(
      "https://github.com/acme/repo/pull/42",
      "_blank",
      "noopener,noreferrer",
    );
    open.mockRestore();
  });

  it.each([
    { server: "current", stored: true },
    { server: "older", stored: false },
  ])("answers offline from the $server server's stored pull request", async ({ stored }) => {
    authenticatedFetchMock.mockImplementation((url: string) =>
      Promise.resolve(
        url.includes("/resources/github")
          ? new Response(
              JSON.stringify({ error: { code: "runner_unavailable", message: "offline" } }),
              { status: 503 },
            )
          : new Response(
              JSON.stringify({
                object: "list",
                data: [
                  {
                    url: "https://github.com/acme/repo/pull/42",
                    host: "github.com",
                    repository: "acme/repo",
                    number: 42,
                    title: "Add canvas",
                    relationship: "created",
                    state: "MERGED",
                  },
                ],
                // A linked PR with a fetched state answers even before the server imports
                // the session; only an empty list then can't mean "no PR".
                synced: false,
              }),
              { status: 200 },
            ),
      ),
    );
    const { result } = renderHook(() => useExtensionHostServices(extension), {
      wrapper: ({ children }: { children: ReactNode }) => (
        <CapabilitiesProvider info={{ ...FALLBACK_SERVER_INFO, session_pull_requests: stored }}>
          {wrapper({ children })}
        </CapabilitiesProvider>
      ),
    });

    const answer = result.current.methods["sessions.pullRequest"]?.(
      { sessionId: "conv_1" },
      signal(),
    );
    if (stored) {
      await expect(answer).resolves.toEqual({
        number: 42,
        title: "Add canvas",
        state: "MERGED",
        url: "https://github.com/acme/repo/pull/42",
      });
    } else {
      // Servers without stored PRs surface the runner's offline error.
      await expect(answer).rejects.toBeInstanceOf(RunnerOfflineError);
    }
    expect(authenticatedFetchMock.mock.calls.map(([url]) => url)).toEqual(
      stored
        ? ["/v1/sessions/conv_1/resources/github", "/v1/sessions/conv_1/pull-requests?limit=100"]
        : ["/v1/sessions/conv_1/resources/github"],
    );
  });

  it.each([
    {
      case: "a stored PR the host never fetched",
      status: 200,
      data: [{ state: null }],
      synced: true,
    },
    { case: "a session the server hasn't imported", status: 200, data: [], synced: false },
    { case: "a failed stored read", status: 500, data: [], synced: true },
  ])("keeps the offline error for $case", async ({ status, data, synced }) => {
    authenticatedFetchMock.mockImplementation((url: string) =>
      Promise.resolve(
        url.includes("/resources/github")
          ? new Response(
              JSON.stringify({ error: { code: "runner_unavailable", message: "offline" } }),
              { status: 503 },
            )
          : new Response(
              JSON.stringify({
                object: "list",
                data: data.map((pr) => ({
                  url: "https://github.com/acme/repo/pull/42",
                  host: "github.com",
                  repository: "acme/repo",
                  number: 42,
                  relationship: "created",
                  ...pr,
                })),
                synced,
              }),
              { status },
            ),
      ),
    );
    const { result } = renderHook(() => useExtensionHostServices(extension), {
      wrapper: ({ children }: { children: ReactNode }) => (
        <CapabilitiesProvider info={{ ...FALLBACK_SERVER_INFO, session_pull_requests: true }}>
          {wrapper({ children })}
        </CapabilitiesProvider>
      ),
    });

    const error = await result.current.methods["sessions.pullRequest"]?.(
      { sessionId: "conv_1" },
      signal(),
    ).catch((thrown: unknown) => thrown);
    expect(error).toBeInstanceOf(RunnerOfflineError);
    expect((error as Error).cause !== undefined).toBe(status !== 200);
  });

  it("does not make session pages wait behind pull-request enrichment", async () => {
    let resolvePullRequest!: (response: Response) => void;
    const pullRequestResponse = new Promise<Response>((resolve) => {
      resolvePullRequest = resolve;
    });
    authenticatedFetchMock.mockImplementation((url: string) => {
      if (url.includes("/resources/github")) return pullRequestResponse;
      return Promise.resolve(
        new Response(JSON.stringify({ data: [], has_more: false, last_id: null }), { status: 200 }),
      );
    });
    const { result } = renderHook(() => useExtensionHostServices(extension), {
      wrapper,
    });

    const pullRequest = result.current.methods["sessions.pullRequest"]?.(
      { sessionId: "conv_slow" },
      signal(),
    );
    await waitFor(() => expect(authenticatedFetchMock).toHaveBeenCalledOnce());
    const page = result.current.methods["sessions.listPage"]?.({}, signal());
    await waitFor(() =>
      expect(authenticatedFetchMock).toHaveBeenCalledWith(
        expect.stringMatching(/^\/v1\/sessions\?/),
        expect.anything(),
      ),
    );

    resolvePullRequest(
      new Response(
        JSON.stringify({
          object: "session.github.info",
          available: false,
          pr: null,
        }),
        { status: 200 },
      ),
    );
    await expect(page).resolves.toMatchObject({ sessions: [] });
    await expect(pullRequest).resolves.toBeNull();
  });

  it("lists projects and creates one while refreshing the sidebar's project list", async () => {
    authenticatedFetchMock
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            object: "list",
            data: [{ id: "p1", name: "Alpha", config: { icon: "🅰️" } }],
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ id: "p2", name: "Beta", config: {} }), { status: 200 }),
      );
    const invalidate = vi.spyOn(queryClient, "invalidateQueries").mockResolvedValue(undefined);
    const { result } = renderHook(() => useExtensionHostServices(extension), { wrapper });

    await expect(result.current.methods["projects.list"]?.({}, signal())).resolves.toEqual([
      { id: "p1", name: "Alpha", icon: "🅰️" },
    ]);
    await expect(
      result.current.methods["projects.create"]?.({ name: "  Beta " }, signal()),
    ).resolves.toEqual({ id: "p2", name: "Beta", icon: null });
    const [, init] = authenticatedFetchMock.mock.calls[1] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({ name: "Beta" });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["projects"] });
    invalidate.mockRestore();
  });

  it("runs only its own declared commands and repaints the cached row", async () => {
    queryClient.setQueryData(["conversations", "", true], {
      pages: [
        { data: [{ id: "conv_1", title: "One", labels: {}, updated_at: 1 }], has_more: false },
      ],
      pageParams: [undefined],
    });
    authenticatedFetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          object: "extension_command_result",
          command: "acme.review.watch",
          key: "pr:7",
          entry: { key: "pr:7", value: "watching", version: 1, updated_at: 5, updated_by: null },
          deleted: false,
          published_fields: { "acme.review": { count: "1" }, "acme.other": { x: "y" } },
        }),
      ),
    );
    const { result } = renderHook(() => useExtensionHostServices(extension), { wrapper });
    const invoke = result.current.methods["commands.invoke"]!;

    expect(() =>
      invoke({ sessionId: "conv_1", commandId: "acme.other.watch", arguments: {} }, signal()),
    ).toThrow("Command is not declared by extension");
    expect(() =>
      invoke(
        { sessionId: "conv_1", commandId: "acme.review.watch", arguments: { pr: 7 } },
        signal(),
      ),
    ).toThrow("arguments must map names to strings");

    await expect(
      invoke(
        { sessionId: "conv_1", commandId: "acme.review.watch", arguments: { pr: "7" } },
        signal(),
      ),
    ).resolves.toEqual({
      key: "pr:7",
      entry: { key: "pr:7", value: "watching", version: 1, updatedAt: 5, updatedBy: null },
      deleted: false,
      // Only its own extension's fields.
      publishedFields: { count: "1" },
    });
    const [url, init] = authenticatedFetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/v1/sessions/conv_1/extensions/acme.review/commands/acme.review.watch");
    expect(JSON.parse(String(init.body))).toEqual({ arguments: { pr: "7" } });
    expect(
      queryClient.getQueryData<{ pages: { data: { published_fields?: unknown }[] }[] }>([
        "conversations",
        "",
        true,
      ])?.pages[0].data[0].published_fields,
    ).toEqual({ "acme.review": { count: "1" }, "acme.other": { x: "y" } });
  });

  it("needs sessions.read to reopen its page for another session", () => {
    const ownOnly = {
      ...extension,
      permissions: extension.permissions.filter((item) => item !== "sessions.read"),
    };
    const { result } = renderHook(
      () => useExtensionHostServices(ownOnly, { sessionId: "conv_1" }),
      { wrapper },
    );
    const openPage = result.current.methods["navigation.openPage"]!;

    // Reopening for another session would hand the page that session's state.
    expect(() =>
      openPage({ pageId: "acme.review.dashboard", params: { conversationId: "conv_2" } }, signal()),
    ).toThrow("sessions.read");
    expect(navigate).not.toHaveBeenCalled();
    openPage({ pageId: "acme.review.dashboard", params: { conversationId: "conv_1" } }, signal());
    openPage({ pageId: "acme.review.dashboard", params: { tab: "one" } }, signal());
    expect(navigate).toHaveBeenCalledTimes(2);

    const { result: reader } = renderHook(
      () => useExtensionHostServices(extension, { sessionId: "conv_1" }),
      { wrapper },
    );
    reader.current.methods["navigation.openPage"]!(
      { pageId: "acme.review.dashboard", params: { conversationId: "conv_2" } },
      signal(),
    );
    expect(navigate).toHaveBeenLastCalledWith({
      pathname: "/extensions/acme.review/dashboard",
      search: "?conversationId=conv_2",
    });
  });

  it("needs sessions.read to use state on a session other than the page's own", async () => {
    authenticatedFetchMock.mockImplementation(async () => new Response("{}", { status: 404 }));
    const ownOnly = {
      ...extension,
      permissions: extension.permissions.filter((item) => item !== "sessions.read"),
    };
    const { result } = renderHook(
      () => useExtensionHostServices(ownOnly, { sessionId: "conv_1" }),
      { wrapper },
    );
    const methods = result.current.methods;

    await expect(
      methods["state.get"]?.({ sessionId: "conv_1", key: "k" }, signal()),
    ).resolves.toBeNull();
    const others = [
      ["state.get", { sessionId: "conv_2", key: "k" }],
      ["state.list", { sessionId: "conv_2" }],
      [
        "commands.invoke",
        { sessionId: "conv_2", commandId: "acme.review.watch", arguments: { pr: "1" } },
      ],
    ] as const;
    const outcomes = await Promise.allSettled(
      others.map(([method, params]) =>
        Promise.resolve().then((): unknown => methods[method]?.(params, signal())),
      ),
    );
    for (const outcome of outcomes) {
      expect(outcome).toMatchObject({
        status: "rejected",
        reason: { code: "PermissionDenied" },
      });
    }
    expect(authenticatedFetchMock).toHaveBeenCalledTimes(1);

    // With sessions.read, any session the viewer can read.
    const { result: reader } = renderHook(
      () => useExtensionHostServices(extension, { sessionId: "conv_1" }),
      { wrapper },
    );
    await expect(
      reader.current.methods["state.get"]?.({ sessionId: "conv_2", key: "k" }, signal()),
    ).resolves.toBeNull();
  });

  it("maps a refused command to PermissionDenied", async () => {
    authenticatedFetchMock.mockResolvedValue(
      new Response(JSON.stringify({ error: { message: "needs more access" } }), { status: 403 }),
    );
    const { result } = renderHook(() => useExtensionHostServices(extension), { wrapper });

    await expect(
      result.current.methods["commands.invoke"]?.(
        { sessionId: "conv_1", commandId: "acme.review.watch", arguments: { pr: "1" } },
        signal(),
      ),
    ).rejects.toMatchObject({ code: "PermissionDenied", message: "needs more access" });
  });

  it("reads its own state as the viewer, with unreadable keys as null", async () => {
    authenticatedFetchMock
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            key: "pr:7",
            value: "watching",
            value_base64: "d2F0Y2hpbmc=",
            version: 2,
            updated_at: 9,
            updated_by: "editor@example.com",
          }),
        ),
      )
      .mockResolvedValueOnce(new Response("{}", { status: 404 }));
    const { result } = renderHook(() => useExtensionHostServices(extension), { wrapper });
    const get = result.current.methods["state.get"]!;

    await expect(get({ sessionId: "conv_1", key: "pr:7" }, signal())).resolves.toEqual({
      key: "pr:7",
      value: "watching",
      version: 2,
      updatedAt: 9,
      updatedBy: "editor@example.com",
    });
    expect(authenticatedFetchMock.mock.calls[0][0]).toBe(
      "/v1/sessions/conv_1/extensions/acme.review/state/pr%3A7",
    );
    await expect(get({ sessionId: "conv_1", key: "secret" }, signal())).resolves.toBeNull();
    await expect(get({ sessionId: "conv_1", key: "" }, signal())).rejects.toThrow("key is invalid");
  });

  it("lists state in pages that fit one RPC message", async () => {
    const big = "x".repeat(12_000);
    const entry = (key: string) => ({
      key,
      value: big,
      value_base64: "",
      version: 1,
      updated_at: 1,
      updated_by: null,
    });
    authenticatedFetchMock.mockResolvedValue(
      new Response(JSON.stringify({ data: ["a", "b", "c", "d"].map(entry), next_after: null })),
    );
    const { result } = renderHook(() => useExtensionHostServices(extension), { wrapper });

    const page = (await result.current.methods["state.list"]?.(
      { sessionId: "conv_1", after: null, limit: 4 },
      signal(),
    )) as { entries: { key: string }[]; nextAfter: string | null };

    expect(authenticatedFetchMock.mock.calls[0][0]).toBe(
      "/v1/sessions/conv_1/extensions/acme.review/state?limit=4",
    );
    expect(page.entries.map((item) => item.key)).toEqual(["a", "b"]);
    expect(page.nextAfter).toBe("b");
    await expect(
      result.current.methods["state.list"]?.({ sessionId: "conv_1", limit: 51 }, signal()),
    ).rejects.toThrow("limit must be an integer from 1 to 50");
  });

  it("keeps sessions methods absent for existing extension permissions", () => {
    const existing = { ...extension, permissions: ["navigation", "storage.user"] };
    const { result } = renderHook(() => useExtensionHostServices(existing), { wrapper });

    expect(result.current.methods["sessions.getCached"]).toBeUndefined();
    expect(result.current.methods["sessions.listPage"]).toBeUndefined();
    expect(result.current.methods["sessions.get"]).toBeUndefined();
    expect(result.current.methods["projects.list"]).toBeUndefined();
    expect(result.current.methods["projects.create"]).toBeUndefined();
    expect(result.current.methods["navigation.openSession"]).toBeDefined();
    expect(result.current.methods["storage.user.get"]).toBeDefined();
    // A page's own commands and state need no permission.
    expect(result.current.methods["commands.invoke"]).toBeDefined();
    expect(result.current.methods["state.list"]).toBeDefined();
  });

  it("omits methods whose permissions were not granted", () => {
    const denied = { ...extension, permissions: [] };
    const { result } = renderHook(() => useExtensionHostServices(denied), { wrapper });

    expect(Object.keys(result.current.methods).sort()).toEqual([
      "commands.invoke",
      "state.get",
      "state.list",
      "theme.getCurrent",
      "theme.subscribe",
    ]);
  });

  it("refuses storage until both user and server identities resolve", async () => {
    identityRef.current = null;
    serverRef.current = null;
    const { result } = renderHook(() => useExtensionHostServices(extension), { wrapper });

    await expect(
      result.current.methods["storage.user.get"]?.({ key: "layout" }, signal()),
    ).rejects.toMatchObject({ code: "Unavailable" });
  });

  it("persists extension-scoped values through the storage service", async () => {
    const { result } = renderHook(() => useExtensionHostServices(extension), { wrapper });
    await act(() =>
      result.current.methods["storage.user.set"]?.({ key: "layout", value: { x: 1 } }, signal()),
    );

    await expect(
      result.current.methods["storage.user.get"]?.({ key: "layout" }, signal()),
    ).resolves.toEqual({ x: 1 });
  });
});
