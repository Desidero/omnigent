// A page's own extension state: running its declared commands and reading the
// keys the viewer may read. Both go through the server as the viewer; the page
// never acts as the extension.

import type { QueryClient } from "@tanstack/react-query";
import { authenticatedFetch } from "@/lib/identity";
import { apiErrorFromResponse } from "@/lib/sessionsApi";
import { isExtensionPayloadWithinBudget } from "../rpc/validation";
import {
  runExtensionCommand,
  type CommandInvocation,
  type CommandResult,
} from "../sessionCommands";
import type { ExtensionCatalogItem } from "../types";
import { ExtensionHostServiceError } from "./errors";

const SESSION_ID_MAX_LENGTH = 256;
const STATE_KEY_MAX_LENGTH = 128;
const MAX_ARGUMENTS = 16;
const ARGUMENT_MAX_LENGTH = 256;
export const STATE_PAGE_DEFAULT_LIMIT = 20;
export const STATE_PAGE_MAX_LIMIT = 50;

export interface ExtensionStateEntry {
  key: string;
  /** UTF-8 text, or null for other bytes. */
  value: string | null;
  version: number;
  updatedAt: number;
  /** Who wrote it; only viewers with edit access see it. */
  updatedBy: string | null;
}

export interface ExtensionStatePage {
  entries: ExtensionStateEntry[];
  /** Pass as `after` for the next page; null on the last page. */
  nextAfter: string | null;
}

export interface ExtensionCommandOutcome {
  key: string;
  entry: ExtensionStateEntry | null;
  deleted: boolean;
  /** This extension's published fields on the session afterwards. */
  publishedFields: Record<string, string>;
}

interface EntryWire {
  key: string;
  value: string | null;
  version: number;
  updated_at: number;
  updated_by: string | null;
}

function objectParams(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new ExtensionHostServiceError("InvalidParams", "Expected an object");
  }
  return value as Record<string, unknown>;
}

/** Which extension a page belongs to, and the session it was opened for. */
export interface StateScope {
  extension: ExtensionCatalogItem;
  /** The page's `conversationId`, or null when it was opened without one. */
  pageSessionId: string | null;
}

// The page's own session is always allowed; naming another one is a session
// read, so it needs the same `sessions.read` permission as `sessions.get`.
function sessionIdParam(params: Record<string, unknown>, scope: StateScope): string {
  const { sessionId } = params;
  if (typeof sessionId !== "string" || !sessionId || sessionId.length > SESSION_ID_MAX_LENGTH) {
    throw new ExtensionHostServiceError("InvalidParams", "sessionId is invalid");
  }
  if (sessionId !== scope.pageSessionId && !scope.extension.permissions.includes("sessions.read")) {
    throw new ExtensionHostServiceError(
      "PermissionDenied",
      "Using another session than the page's own needs the sessions.read permission",
    );
  }
  return sessionId;
}

function entryFromWire(wire: EntryWire): ExtensionStateEntry {
  return {
    key: wire.key,
    value: wire.value,
    version: wire.version,
    updatedAt: wire.updated_at,
    updatedBy: wire.updated_by,
  };
}

function hostError(error: unknown, action: string): ExtensionHostServiceError {
  const status = (error as { status?: unknown }).status;
  const message = error instanceof Error && error.message ? error.message : `${action} failed`;
  if (status === 401 || status === 403)
    return new ExtensionHostServiceError("PermissionDenied", message);
  if (status === 404) return new ExtensionHostServiceError("NotFound", message);
  if (status === 409) return new ExtensionHostServiceError("Conflict", message);
  if (status === 400 || status === 422)
    return new ExtensionHostServiceError("InvalidParams", message);
  return new ExtensionHostServiceError("HostError", `${action} failed`);
}

function stateBase(extensionId: string, sessionId: string): string {
  return `/v1/sessions/${encodeURIComponent(sessionId)}/extensions/${encodeURIComponent(extensionId)}/state`;
}

/** Validate a page's command call against its own extension's catalog. */
export function parseCommandInvoke(scope: StateScope, params: unknown): CommandInvocation {
  const { extension } = scope;
  const input = objectParams(params);
  const sessionId = sessionIdParam(input, scope);
  const command = (extension.commands ?? []).find((item) => item.id === input.commandId);
  if (!command) {
    throw new ExtensionHostServiceError("PermissionDenied", "Command is not declared by extension");
  }
  const raw = input.arguments === undefined ? {} : objectParams(input.arguments);
  const entries = Object.entries(raw);
  if (
    entries.length > MAX_ARGUMENTS ||
    entries.some(([, value]) => typeof value !== "string" || value.length > ARGUMENT_MAX_LENGTH)
  ) {
    throw new ExtensionHostServiceError("InvalidParams", "arguments must map names to strings");
  }
  const { expectedVersion } = input;
  if (
    expectedVersion !== undefined &&
    (typeof expectedVersion !== "number" ||
      !Number.isSafeInteger(expectedVersion) ||
      expectedVersion < 0)
  ) {
    throw new ExtensionHostServiceError("InvalidParams", "expectedVersion is invalid");
  }
  return {
    sessionId,
    extensionId: extension.id,
    command,
    arguments: Object.fromEntries(entries) as Record<string, string>,
    ...(expectedVersion === undefined ? {} : { expectedVersion }),
  };
}

/** Run the command as the viewer, in order with the row menu's commands on the session. */
export async function invokeCommand(
  queryClient: QueryClient,
  invocation: CommandInvocation,
  signal: AbortSignal,
): Promise<ExtensionCommandOutcome> {
  let result: CommandResult;
  try {
    result = await runExtensionCommand(queryClient, invocation, signal);
  } catch (error) {
    if (signal.aborted) throw error;
    throw hostError(error, "Command");
  }
  const own = result.published_fields[invocation.extensionId];
  return {
    key: result.key,
    entry: result.entry ? entryFromWire(result.entry) : null,
    deleted: result.deleted,
    publishedFields: own ? { ...own } : {},
  };
}

/** Read one key of the page's own extension state, or null when unset or not readable. */
export async function readStateEntry(
  scope: StateScope,
  params: unknown,
  signal: AbortSignal,
): Promise<ExtensionStateEntry | null> {
  const extensionId = scope.extension.id;
  const input = objectParams(params);
  const sessionId = sessionIdParam(input, scope);
  const { key } = input;
  if (typeof key !== "string" || !key || key.length > STATE_KEY_MAX_LENGTH) {
    throw new ExtensionHostServiceError("InvalidParams", "key is invalid");
  }
  const response = await authenticatedFetch(
    `${stateBase(extensionId, sessionId)}/${encodeURIComponent(key)}`,
    { signal },
  );
  // Unset, unreadable, and an unreadable session all look the same to a page.
  if (response.status === 404) return null;
  if (!response.ok) throw hostError(await apiErrorFromResponse(response), "State read");
  return entryFromWire((await response.json()) as EntryWire);
}

/**
 * List the keys the viewer may read, in key order. A page shorter than
 * `limit` can still have a next page: the host keeps each reply within the
 * RPC message budget.
 */
export async function listStateEntries(
  scope: StateScope,
  params: unknown,
  signal: AbortSignal,
): Promise<ExtensionStatePage> {
  const extensionId = scope.extension.id;
  const input = objectParams(params);
  const sessionId = sessionIdParam(input, scope);
  const { after } = input;
  const limit = input.limit ?? STATE_PAGE_DEFAULT_LIMIT;
  if (
    after !== undefined &&
    after !== null &&
    (typeof after !== "string" || after.length > STATE_KEY_MAX_LENGTH)
  ) {
    throw new ExtensionHostServiceError("InvalidParams", "after is invalid");
  }
  if (
    typeof limit !== "number" ||
    !Number.isInteger(limit) ||
    limit < 1 ||
    limit > STATE_PAGE_MAX_LIMIT
  ) {
    throw new ExtensionHostServiceError(
      "InvalidParams",
      `limit must be an integer from 1 to ${STATE_PAGE_MAX_LIMIT}`,
    );
  }
  const query = new URLSearchParams({ limit: String(limit) });
  if (typeof after === "string") query.set("after", after);
  const response = await authenticatedFetch(`${stateBase(extensionId, sessionId)}?${query}`, {
    signal,
  });
  if (response.status === 404) return { entries: [], nextAfter: null };
  if (!response.ok) throw hostError(await apiErrorFromResponse(response), "State list");
  const body = (await response.json()) as { data: EntryWire[]; next_after: string | null };
  const page: ExtensionStatePage = {
    entries: body.data.map(entryFromWire),
    nextAfter: body.next_after,
  };
  // Values reach 16 KB each, so drop trailing entries until the reply fits;
  // the server pages by key, so the last kept key continues the listing.
  while (page.entries.length > 1 && !isExtensionPayloadWithinBudget(page)) {
    page.entries.pop();
    page.nextAfter = page.entries[page.entries.length - 1].key;
  }
  return page;
}
