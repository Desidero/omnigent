import type { QueryClient } from "@tanstack/react-query";
import { writeSessionLabelOptimistically } from "../sessionLabels";
import type { ExtensionCatalogItem } from "../types";
import { ExtensionHostServiceError } from "./errors";

const SESSION_ID_MAX_LENGTH = 256;

export interface LabelWrite {
  sessionId: string;
  key: string;
  value: string;
}

/** Validate a page's label write against its own extension's declaration. */
export function parseLabelWrite(
  extension: ExtensionCatalogItem,
  params: unknown,
  clear: boolean,
): LabelWrite {
  if (!params || typeof params !== "object" || Array.isArray(params)) {
    throw new ExtensionHostServiceError("InvalidParams", "Expected an object");
  }
  const { sessionId, key, value } = params as Record<string, unknown>;
  if (typeof sessionId !== "string" || !sessionId || sessionId.length > SESSION_ID_MAX_LENGTH) {
    throw new ExtensionHostServiceError("InvalidParams", "sessionId is invalid");
  }
  const label = (extension.labels ?? []).find((candidate) => candidate.key === key);
  if (!label) {
    throw new ExtensionHostServiceError("PermissionDenied", "Label is not declared by extension");
  }
  if (clear) return { sessionId, key: label.key, value: "" };
  if (!label.values.some((candidate) => candidate.value === value)) {
    throw new ExtensionHostServiceError("InvalidParams", "Value is not declared for this label");
  }
  return { sessionId, key: label.key, value: value as string };
}

/** Write through the server as the viewer, in order with the row menu's writes to the key. */
export async function writeExtensionLabel(
  queryClient: QueryClient,
  write: LabelWrite,
  signal: AbortSignal,
): Promise<null> {
  if (signal.aborted) throw new DOMException("Host operation cancelled", "AbortError");
  try {
    // The page's cancel (or its SDK timeout) aborts the write too.
    await writeSessionLabelOptimistically(
      queryClient,
      write.sessionId,
      write.key,
      write.value,
      signal,
    );
  } catch (error) {
    if (signal.aborted) throw error;
    const status = (error as { status?: unknown }).status;
    if (status === 401 || status === 403 || status === 404) {
      throw new ExtensionHostServiceError("PermissionDenied", "Label write was denied");
    }
    throw new ExtensionHostServiceError("HostError", "Label write failed");
  }
  return null;
}
