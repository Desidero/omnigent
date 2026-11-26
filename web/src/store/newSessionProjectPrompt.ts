import type { MouseEvent } from "react";
import { create } from "zustand";

import { readNewChatProjectPromptEnabled } from "@/lib/newChatProjectPromptPreferences";

// The "Start a new session in…" project prompt, and the entry points that open it: the
// new-session shortcut, the sidebar's New session links and ⌘K's New chat.

interface NewSessionProjectPromptState {
  open: boolean;
  /** The app shell has mounted the prompt; without it, a new session starts unasked. */
  hosted: boolean;
}

export const useNewSessionProjectPromptStore = create<NewSessionProjectPromptState>(() => ({
  open: false,
  hosted: false,
}));

export function closeNewSessionProjectPrompt(): void {
  useNewSessionProjectPromptStore.setState({ open: false });
}

/** Opens the prompt if it's on and mounted; false means the caller starts the session itself. */
function askForProject(): boolean {
  if (!useNewSessionProjectPromptStore.getState().hosted) return false;
  if (!readNewChatProjectPromptEnabled()) return false;
  useNewSessionProjectPromptStore.setState({ open: true });
  return true;
}

/** Start a new session: ask for its project first, or open the plain composer. */
export function startNewSession(navigate: (to: string) => void): void {
  if (!askForProject()) navigate("/");
}

/**
 * For a New session link's `onClick`: a plain click asks for a project instead of following
 * the link. Modified clicks still open the composer in a new tab.
 */
export function askForProjectOnNewSessionClick(event: MouseEvent<HTMLAnchorElement>): void {
  if (event.defaultPrevented || event.button !== 0) return;
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  if (askForProject()) event.preventDefault();
}
