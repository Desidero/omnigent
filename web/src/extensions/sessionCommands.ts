import { useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { showToast } from "@/components/ui/toast";
import { authenticatedFetch } from "@/lib/identity";
import { isEditorLevel } from "@/lib/permissionsApi";
import { overlayPublishedFieldsIntoCaches } from "@/lib/sessionListCache";
import { apiErrorFromResponse } from "@/lib/sessionsApi";
import type { ExtensionCommand, PublishedFields } from "./types";

// Under the extension SDK's 10s request timeout, so a page's call and the
// host's request give up together.
export const COMMAND_TIMEOUT_MS = 8_000;

export interface CommandInvocation {
  sessionId: string;
  extensionId: string;
  command: ExtensionCommand;
  arguments: Record<string, string>;
  expectedVersion?: number;
}

export interface CommandResult {
  object: "extension_command_result";
  command: string;
  key: string;
  entry: {
    key: string;
    value: string | null;
    version: number;
    updated_at: number;
    updated_by: string | null;
  } | null;
  deleted: boolean;
  published_fields: PublishedFields;
}

/**
 * Whether a viewer at `permissionLevel` may run the command (the server checks
 * again). A sub-agent session's edit access can come from its parent, which
 * the row's level doesn't show, so those are left to the server.
 */
export function canRunCommand(
  command: ExtensionCommand,
  permissionLevel: number | null,
  session: { parentSessionId?: string | null } = {},
): boolean {
  return (
    command.required_access === "read" ||
    isEditorLevel(permissionLevel) ||
    Boolean(session.parentSessionId)
  );
}

// Aborts on the caller's signal or after the timeout. Built by hand because
// `AbortSignal.any` is newer than the browsers the app supports.
function commandSignal(signal?: AbortSignal): { signal: AbortSignal; done: () => void } {
  const controller = new AbortController();
  const timer = setTimeout(
    () => controller.abort(new DOMException("Command timed out", "TimeoutError")),
    COMMAND_TIMEOUT_MS,
  );
  const forward = () => controller.abort(signal?.reason);
  if (signal?.aborted) forward();
  signal?.addEventListener("abort", forward, { once: true });
  return {
    signal: controller.signal,
    done: () => {
      clearTimeout(timer);
      signal?.removeEventListener("abort", forward);
    },
  };
}

/** Run one declared command through the server as the viewer. */
export async function postExtensionCommand(
  invocation: CommandInvocation,
  signal?: AbortSignal,
): Promise<CommandResult> {
  const abort = commandSignal(signal);
  const path = [
    "/v1/sessions",
    encodeURIComponent(invocation.sessionId),
    "extensions",
    encodeURIComponent(invocation.extensionId),
    "commands",
    encodeURIComponent(invocation.command.id),
  ].join("/");
  try {
    const response = await authenticatedFetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        arguments: invocation.arguments,
        ...(invocation.expectedVersion === undefined
          ? {}
          : { expected_version: invocation.expectedVersion }),
      }),
      signal: abort.signal,
    });
    if (!response.ok) throw await apiErrorFromResponse(response);
    return (await response.json()) as CommandResult;
  } finally {
    abort.done();
  }
}

// Commands on one session run in order, so the published fields painted last
// are the ones the server returned last.
const sessionQueues = new Map<string, Promise<unknown>>();

/**
 * Run a command after any earlier one on the same session, then paint the
 * session's published fields from the response on every cached copy of it.
 */
export function runExtensionCommand(
  queryClient: QueryClient,
  invocation: CommandInvocation,
  signal?: AbortSignal,
): Promise<CommandResult> {
  const previous = sessionQueues.get(invocation.sessionId) ?? Promise.resolve();
  const run = previous
    .catch(() => undefined)
    .then(async () => {
      if (signal?.aborted) throw new DOMException("Command cancelled", "AbortError");
      const result = await postExtensionCommand(invocation, signal);
      overlayPublishedFieldsIntoCaches(queryClient, invocation.sessionId, result.published_fields);
      return result;
    });
  sessionQueues.set(invocation.sessionId, run);
  void run
    .catch(() => undefined)
    .then(() => {
      if (sessionQueues.get(invocation.sessionId) === run) {
        sessionQueues.delete(invocation.sessionId);
      }
    });
  return run;
}

/** Core's own command runs (row menu entries), with its failure toast. */
export function useRunExtensionCommand() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (invocation: CommandInvocation) => runExtensionCommand(queryClient, invocation),
    onError: (error, { command }) => {
      const detail = error instanceof Error && error.message ? `: ${error.message}` : "";
      showToast(`Couldn't run ${command.title}${detail}`);
    },
  });
}
