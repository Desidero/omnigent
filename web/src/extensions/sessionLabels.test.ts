import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { authenticatedFetchMock } = vi.hoisted(() => ({ authenticatedFetchMock: vi.fn() }));
vi.mock("@/lib/identity", () => ({ authenticatedFetch: authenticatedFetchMock }));

import { writeSessionLabelOptimistically } from "./sessionLabels";

const KEY = "ext.acme.status.status";
const queryClient = new QueryClient();

function seed(labels: Record<string, string>) {
  queryClient.setQueryData(["conversations", "", true], {
    pages: [{ data: [{ id: "conv_1", title: "One", labels, updated_at: 1 }], has_more: false }],
    pageParams: [undefined],
  });
}

function cachedLabels() {
  return queryClient.getQueryData<{ pages: { data: { labels: Record<string, string> }[] }[] }>([
    "conversations",
    "",
    true,
  ])?.pages[0].data[0].labels;
}

function deferredResponse() {
  let resolve!: (response: Response) => void;
  const promise = new Promise<Response>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

beforeEach(() => {
  queryClient.clear();
  authenticatedFetchMock.mockReset();
});

function serve(patch: () => Promise<Response>, labels: Record<string, string> | null) {
  authenticatedFetchMock.mockImplementation(async (_url: string, init?: RequestInit) => {
    if (init?.method === "PATCH") return patch();
    return labels === null
      ? new Response("{}", { status: 503 })
      : new Response(JSON.stringify({ labels }), { status: 200 });
  });
}

const patches = () =>
  authenticatedFetchMock.mock.calls.filter(([, init]) => init?.method === "PATCH");

describe("writeSessionLabelOptimistically", () => {
  it("paints only its key and shows the server's value when the write fails", async () => {
    seed({ team: "ml", [KEY]: "blocked" });
    const pending = deferredResponse();
    serve(() => pending.promise, { [KEY]: "blocked", team: "server" });

    const write = writeSessionLabelOptimistically(queryClient, "conv_1", KEY, "done");
    expect(cachedLabels()).toEqual({ team: "ml", [KEY]: "done" });
    // Another label changes while the write is in flight; the repair keeps it.
    seed({ team: "infra", [KEY]: "done" });
    pending.resolve(new Response("{}", { status: 500 }));

    await expect(write).rejects.toThrow();
    expect(cachedLabels()).toEqual({ team: "infra", [KEY]: "blocked" });
  });

  it("shows a timed-out write the server applied anyway", async () => {
    seed({});
    serve(() => Promise.reject(new DOMException("timed out", "TimeoutError")), { [KEY]: "done" });

    await expect(
      writeSessionLabelOptimistically(queryClient, "conv_1", KEY, "done"),
    ).rejects.toThrow();

    expect(cachedLabels()).toEqual({ [KEY]: "done" });
  });

  it("sends writes in order and keeps the newest one when an older one fails", async () => {
    seed({});
    const older = deferredResponse();
    const responses = [older.promise, Promise.resolve(new Response("{}", { status: 200 }))];
    serve(() => responses.shift()!, { [KEY]: "done" });

    const first = writeSessionLabelOptimistically(queryClient, "conv_1", KEY, "blocked");
    const second = writeSessionLabelOptimistically(queryClient, "conv_1", KEY, "done");
    // The newer write waits for the older one to settle.
    await vi.waitFor(() => expect(patches()).toHaveLength(1));
    older.resolve(new Response("{}", { status: 500 }));

    await expect(first).rejects.toThrow();
    await second;
    expect(patches()).toHaveLength(2);
    expect(cachedLabels()).toEqual({ [KEY]: "done" });
  });

  it("reads the label back after the last write when an earlier one timed out", async () => {
    seed({});
    const responses = [
      Promise.reject(new DOMException("timed out", "TimeoutError")),
      Promise.resolve(new Response("{}", { status: 200 })),
    ];
    // The timed-out request landed after the newer one.
    serve(() => responses.shift()!, { [KEY]: "blocked" });

    const first = writeSessionLabelOptimistically(queryClient, "conv_1", KEY, "blocked");
    const second = writeSessionLabelOptimistically(queryClient, "conv_1", KEY, "done");

    await expect(first).rejects.toThrow();
    await second;
    expect(cachedLabels()).toEqual({ [KEY]: "blocked" });
  });

  it("drops an older read-back once a newer write starts", async () => {
    seed({});
    const olderRead = deferredResponse();
    const patchResponses = [
      Promise.resolve(new Response("{}", { status: 500 })),
      Promise.resolve(new Response("{}", { status: 200 })),
    ];
    const reads = [
      olderRead.promise,
      Promise.resolve(new Response(JSON.stringify({ labels: { [KEY]: "done" } }))),
    ];
    authenticatedFetchMock.mockImplementation(async (_url: string, init?: RequestInit) =>
      init?.method === "PATCH" ? patchResponses.shift()! : reads.shift()!,
    );

    const first = writeSessionLabelOptimistically(queryClient, "conv_1", KEY, "blocked");
    // The failed write is reading the label back when a newer one starts.
    await vi.waitFor(() => expect(authenticatedFetchMock).toHaveBeenCalledTimes(2));
    const second = writeSessionLabelOptimistically(queryClient, "conv_1", KEY, "done");
    await vi.waitFor(() => expect(patches()).toHaveLength(2));
    olderRead.resolve(new Response(JSON.stringify({ labels: { [KEY]: "stale" } })));

    await expect(first).rejects.toThrow();
    await second;
    expect(cachedLabels()).toEqual({ [KEY]: "done" });
  });

  it("does not read back when every write succeeded", async () => {
    seed({});
    serve(async () => new Response("{}", { status: 200 }), { [KEY]: "stale" });

    await writeSessionLabelOptimistically(queryClient, "conv_1", KEY, "done");

    expect(authenticatedFetchMock.mock.calls).toHaveLength(1);
    expect(cachedLabels()).toEqual({ [KEY]: "done" });
  });

  it("refetches the lists when it can't read the label back", async () => {
    seed({});
    serve(async () => new Response("{}", { status: 500 }), null);
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");

    await expect(
      writeSessionLabelOptimistically(queryClient, "conv_1", KEY, "done"),
    ).rejects.toThrow();

    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["conversations"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["project-sessions"] });
  });
});
