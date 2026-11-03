import { afterEach, describe, expect, it } from "vitest";
import { defineExtension, type ExtensionContext } from "../../../sdks/web-extension/src/index";
import {
  EXTENSION_RPC_SOURCE,
  EXTENSION_RPC_VERSION,
} from "../../../sdks/web-extension/src/protocol";

const identity = {
  extensionId: "acme.goals",
  pageId: "acme.goals.page",
  view: "goals",
  nonce: "nonce-1",
  apiVersion: EXTENSION_RPC_VERSION,
};

interface HostRequest {
  requestId: string;
  method: string;
  params: Record<string, unknown>;
}

// Activates the SDK in this window and answers its requests like the host.
async function activate(invocation: Record<string, string>) {
  globalThis.__OMNIGENT_EXTENSION__ = identity;
  const channel = new MessageChannel();
  const requests: HostRequest[] = [];
  channel.port1.onmessage = (event: MessageEvent<HostRequest & { type: string }>) => {
    if (event.data.type !== "request") return;
    requests.push(event.data);
    channel.port1.postMessage({
      ...identity,
      source: EXTENSION_RPC_SOURCE,
      type: "response",
      requestId: event.data.requestId,
      result: { echoed: event.data.method },
    });
  };
  const context = new Promise<ExtensionContext>((resolve) => {
    defineExtension({ activate: resolve });
  });
  window.dispatchEvent(
    new MessageEvent("message", {
      source: window.parent,
      ports: [channel.port2],
      data: {
        ...identity,
        source: EXTENSION_RPC_SOURCE,
        type: "init",
        capabilities: ["commands.invoke", "state.get", "state.list"],
        context: invocation,
      },
    }),
  );
  return { context: await context, requests, close: () => channel.port1.close() };
}

let close: (() => void) | undefined;
afterEach(() => {
  close?.();
  window.dispatchEvent(new Event("pagehide"));
});

describe("extension SDK commands and state", () => {
  it("invokes a command on the page's session by default", async () => {
    const host = await activate({ conversationId: "conv_1" });
    close = host.close;

    await host.context.commands.invoke("acme.goals.watch", { pr: "7" });
    await host.context.commands.invoke("acme.goals.stop", undefined, {
      sessionId: "conv_2",
      expectedVersion: 3,
    });
    await host.context.state.get("goal:7");
    await host.context.state.list({ after: "goal:1", limit: 10 });

    expect(host.requests.map(({ method, params }) => [method, params])).toEqual([
      [
        "commands.invoke",
        { sessionId: "conv_1", commandId: "acme.goals.watch", arguments: { pr: "7" } },
      ],
      [
        "commands.invoke",
        { sessionId: "conv_2", commandId: "acme.goals.stop", arguments: {}, expectedVersion: 3 },
      ],
      ["state.get", { sessionId: "conv_1", key: "goal:7" }],
      ["state.list", { sessionId: "conv_1", after: "goal:1", limit: 10 }],
    ]);
  });

  it("needs a session when the page was not opened for one", async () => {
    const host = await activate({});
    close = host.close;

    await expect(host.context.commands.invoke("acme.goals.watch")).rejects.toMatchObject({
      code: "InvalidParams",
    });
    await expect(host.context.state.list()).rejects.toMatchObject({ code: "InvalidParams" });
    expect(host.requests).toEqual([]);
  });
});
