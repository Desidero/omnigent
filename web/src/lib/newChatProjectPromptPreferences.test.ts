import { afterEach, describe, expect, it } from "vitest";
import {
  NEW_CHAT_PROJECT_PROMPT_STORAGE_KEY,
  readNewChatProjectPromptEnabled,
  writeNewChatProjectPromptEnabled,
} from "./newChatProjectPromptPreferences";

describe("newChatProjectPromptPreferences", () => {
  afterEach(() => localStorage.clear());

  it("defaults on when storage is unset", () => {
    expect(readNewChatProjectPromptEnabled()).toBe(true);
  });

  it("persists an off preference and restores the default by clearing it", () => {
    writeNewChatProjectPromptEnabled(false);
    expect(localStorage.getItem(NEW_CHAT_PROJECT_PROMPT_STORAGE_KEY)).toBe("false");
    expect(readNewChatProjectPromptEnabled()).toBe(false);

    writeNewChatProjectPromptEnabled(true);
    expect(localStorage.getItem(NEW_CHAT_PROJECT_PROMPT_STORAGE_KEY)).toBeNull();
    expect(readNewChatProjectPromptEnabled()).toBe(true);
  });

  it("still reads the value an earlier build stored for off", () => {
    localStorage.setItem(NEW_CHAT_PROJECT_PROMPT_STORAGE_KEY, "off");
    expect(readNewChatProjectPromptEnabled()).toBe(false);
  });
});
