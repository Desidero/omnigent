// Per-device choice of whether starting a new session first asks which project it
// belongs to (the default), when the user has projects.

import { createStoredPreference } from "./storedChoicePreference";

export const NEW_CHAT_PROJECT_PROMPT_STORAGE_KEY = "omnigent:new-chat-project-prompt";

const promptPreference = createStoredPreference<boolean>(
  NEW_CHAT_PROJECT_PROMPT_STORAGE_KEY,
  // "off" is what this switch stored before it shared the stored-preference format.
  (stored) => (stored === "false" || stored === "off" ? false : undefined),
  true,
);

export const readNewChatProjectPromptEnabled = promptPreference.read;
export const writeNewChatProjectPromptEnabled = promptPreference.write;

/** Live switch value, including changes made in other windows. */
export function useNewChatProjectPromptPreference(): boolean {
  return promptPreference.use();
}
