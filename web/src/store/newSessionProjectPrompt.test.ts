import type { MouseEvent } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { writeNewChatProjectPromptEnabled } from "@/lib/newChatProjectPromptPreferences";

import {
  askForProjectOnNewSessionClick,
  startNewSession,
  useNewSessionProjectPromptStore,
} from "./newSessionProjectPrompt";

const promptOpen = () => useNewSessionProjectPromptStore.getState().open;

function click(init: Partial<MouseEvent<HTMLAnchorElement>> = {}) {
  const event = {
    button: 0,
    defaultPrevented: false,
    metaKey: false,
    ctrlKey: false,
    shiftKey: false,
    altKey: false,
    preventDefault: vi.fn(),
    ...init,
  };
  askForProjectOnNewSessionClick(event as unknown as MouseEvent<HTMLAnchorElement>);
  return event;
}

beforeEach(() => useNewSessionProjectPromptStore.setState({ open: false, hosted: true }));
afterEach(() => {
  useNewSessionProjectPromptStore.setState({ open: false, hosted: false });
  localStorage.clear();
});

describe("startNewSession", () => {
  it("asks for a project instead of navigating", () => {
    const navigate = vi.fn();
    startNewSession(navigate);

    expect(promptOpen()).toBe(true);
    expect(navigate).not.toHaveBeenCalled();
  });

  it("opens the plain composer when the prompt is turned off", () => {
    writeNewChatProjectPromptEnabled(false);
    const navigate = vi.fn();
    startNewSession(navigate);

    expect(promptOpen()).toBe(false);
    expect(navigate).toHaveBeenCalledExactlyOnceWith("/");
  });

  it("opens the plain composer where no shell mounts the prompt", () => {
    useNewSessionProjectPromptStore.setState({ hosted: false });
    const navigate = vi.fn();
    startNewSession(navigate);

    expect(promptOpen()).toBe(false);
    expect(navigate).toHaveBeenCalledExactlyOnceWith("/");
  });
});

describe("askForProjectOnNewSessionClick", () => {
  it("takes a plain click from the link", () => {
    const event = click();

    expect(event.preventDefault).toHaveBeenCalledTimes(1);
    expect(promptOpen()).toBe(true);
  });

  it.each([
    { metaKey: true },
    { ctrlKey: true },
    { shiftKey: true },
    { altKey: true },
    { button: 1 },
  ])("leaves a modified click %o to the link, which opens a new tab", (init) => {
    const event = click(init);

    expect(event.preventDefault).not.toHaveBeenCalled();
    expect(promptOpen()).toBe(false);
  });

  it("leaves the link alone when the prompt is off or not mounted", () => {
    writeNewChatProjectPromptEnabled(false);
    expect(click().preventDefault).not.toHaveBeenCalled();

    writeNewChatProjectPromptEnabled(true);
    useNewSessionProjectPromptStore.setState({ hosted: false });
    expect(click().preventDefault).not.toHaveBeenCalled();
    expect(promptOpen()).toBe(false);
  });
});
