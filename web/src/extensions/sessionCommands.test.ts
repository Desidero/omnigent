import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type * as Identity from "@/lib/identity";

const { authenticatedFetchMock } = vi.hoisted(() => ({ authenticatedFetchMock: vi.fn() }));
vi.mock("@/lib/identity", async (importOriginal) => ({
  ...(await importOriginal<typeof Identity>()),
  authenticatedFetch: authenticatedFetchMock,
}));

import { canRunCommand, runExtensionCommand } from "./sessionCommands";
import type { ExtensionCommand } from "./types";

const SET: ExtensionCommand = {
  id: "acme.status.set",
  title: "Set status",
  arguments: [{ name: "status", choices: ["blocked", "done"], pattern: null, max_length: 64 }],
  required_access: "edit",
  confirm: null,
  action: { type: "set_state", field: "status", value: "{status}" },
};

function result(status: string): Response {
  return new Response(
    JSON.stringify({
      object: "extension_command_result",
      command: SET.id,
      key: "status",
      entry: null,
      deleted: false,
      published_fields: { "acme.status": { status } },
    }),
  );
}

function cachedFields(queryClient: QueryClient) {
  return queryClient.getQueryData<{
    pages: { data: { published_fields?: Record<string, Record<string, string>> }[] }[];
  }>(["conversations", "", true])?.pages[0].data[0].published_fields;
}

beforeEach(() => {
  authenticatedFetchMock.mockReset();
});

describe("canRunCommand", () => {
  it.each([
    ["edit", null, true],
    ["edit", 1, false],
    ["edit", 2, true],
    ["read", 1, true],
  ] as const)("%s command for level %s: %s", (access, level, allowed) => {
    expect(canRunCommand({ ...SET, required_access: access }, level)).toBe(allowed);
  });

  it("leaves a sub-agent session's commands to the server, which walks the parent", () => {
    // The row shows the child's own grant; edit access may come from the parent.
    expect(canRunCommand(SET, 1, { parentSessionId: "conv_parent" })).toBe(true);
    expect(canRunCommand(SET, 1, { parentSessionId: null })).toBe(false);
  });
});

describe("runExtensionCommand", () => {
  it("posts as the viewer and repaints the cached row's published fields", async () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(["conversations", "", true], {
      pages: [
        { data: [{ id: "conv_1", title: "One", labels: {}, updated_at: 1 }], has_more: false },
      ],
      pageParams: [undefined],
    });
    authenticatedFetchMock.mockResolvedValue(result("done"));

    await runExtensionCommand(queryClient, {
      sessionId: "conv_1",
      extensionId: "acme.status",
      command: SET,
      arguments: { status: "done" },
      expectedVersion: 0,
    });

    const [url, init] = authenticatedFetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/v1/sessions/conv_1/extensions/acme.status/commands/acme.status.set");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({
      arguments: { status: "done" },
      expected_version: 0,
    });
    expect(cachedFields(queryClient)).toEqual({ "acme.status": { status: "done" } });
  });

  it("runs one session's commands in order, so the last response paints last", async () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(["conversations", "", true], {
      pages: [
        { data: [{ id: "conv_1", title: "One", labels: {}, updated_at: 1 }], has_more: false },
      ],
      pageParams: [undefined],
    });
    const releases: (() => void)[] = [];
    authenticatedFetchMock.mockImplementation((_url: string, init: RequestInit) => {
      const { status } = JSON.parse(String(init.body)).arguments as { status: string };
      return new Promise<Response>((resolve) => {
        releases.push(() => resolve(result(status)));
      });
    });
    const invoke = (status: string) =>
      runExtensionCommand(queryClient, {
        sessionId: "conv_1",
        extensionId: "acme.status",
        command: SET,
        arguments: { status },
      });

    const first = invoke("blocked");
    const second = invoke("done");
    await vi.waitFor(() => expect(releases).toHaveLength(1));
    // The second request waits for the first to settle.
    releases[0]();
    await first;
    await vi.waitFor(() => expect(releases).toHaveLength(2));
    releases[1]();
    await second;

    expect(cachedFields(queryClient)).toEqual({ "acme.status": { status: "done" } });
  });

  it("rejects with the server's error and leaves the cache alone", async () => {
    const queryClient = new QueryClient();
    authenticatedFetchMock.mockResolvedValue(
      new Response(JSON.stringify({ error: { message: "This command needs more access" } }), {
        status: 403,
      }),
    );

    await expect(
      runExtensionCommand(queryClient, {
        sessionId: "conv_1",
        extensionId: "acme.status",
        command: SET,
        arguments: { status: "done" },
      }),
    ).rejects.toMatchObject({ status: 403 });
  });
});
