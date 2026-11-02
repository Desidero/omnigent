export const EXTENSION_RPC_SOURCE = "omnigent-extension";
export const EXTENSION_RPC_VERSION = 1;

export interface ExtensionIdentity {
  extensionId: string;
  pageId: string;
  view: string;
  nonce: string;
  apiVersion: number;
}

export interface ExtensionInitMessage extends ExtensionIdentity {
  source: typeof EXTENSION_RPC_SOURCE;
  type: "init";
  capabilities: string[];
  /** Invocation context, such as `conversationId`; hosts without slots omit it. */
  context?: Record<string, string>;
}

/** Read an init message's invocation context, or `null` when it is malformed. */
export function readInvocationContext(value: unknown): Readonly<Record<string, string>> | null {
  if (value === undefined) return Object.freeze({});
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const entries = Object.entries(value);
  if (!entries.every(([, item]) => typeof item === "string")) return null;
  return Object.freeze(Object.fromEntries(entries) as Record<string, string>);
}

export interface ExtensionReadyMessage extends ExtensionIdentity {
  source: typeof EXTENSION_RPC_SOURCE;
  type: "ready";
}

export interface ExtensionIncompatibleMessage extends ExtensionIdentity {
  source: typeof EXTENSION_RPC_SOURCE;
  type: "incompatible";
  sdkApiVersion: number;
}

export interface ExtensionErrorMessage extends ExtensionIdentity {
  source: typeof EXTENSION_RPC_SOURCE;
  type: "error";
  message: string;
}

export interface ExtensionRequestMessage extends ExtensionIdentity {
  source: typeof EXTENSION_RPC_SOURCE;
  type: "request";
  requestId: string;
  method: string;
  params: unknown;
}

export interface ExtensionCancelMessage extends ExtensionIdentity {
  source: typeof EXTENSION_RPC_SOURCE;
  type: "cancel";
  requestId: string;
}

export interface ExtensionResponseMessage extends ExtensionIdentity {
  source: typeof EXTENSION_RPC_SOURCE;
  type: "response";
  requestId: string;
  result?: unknown;
  error?: { code: string; message: string };
}

export interface ExtensionEventMessage extends ExtensionIdentity {
  source: typeof EXTENSION_RPC_SOURCE;
  type: "event";
  event: string;
  value: unknown;
}

export interface ExtensionDisposeMessage extends ExtensionIdentity {
  source: typeof EXTENSION_RPC_SOURCE;
  type: "dispose";
}
