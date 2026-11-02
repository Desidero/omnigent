import type { ExtensionContext } from "@omnigent/extension-sdk";
import { afterEach, describe, expect, it } from "vitest";
import { mountTemplates, type TemplatesPage } from "./templates";

function memoryStorage(): ExtensionContext["storage"]["user"] {
  const values = new Map<string, unknown>();
  return {
    get: async <T>(key: string) => (values.get(key) as T | undefined) ?? null,
    set: async (key, value) => void values.set(key, value),
    delete: async (key) => void values.delete(key),
  };
}

function stubContext(): ExtensionContext {
  return {
    storage: { user: memoryStorage() },
    projects: { list: async () => [], create: async () => ({ id: "p", name: "p", icon: null }) },
  } as unknown as ExtensionContext;
}

let page: TemplatesPage | null = null;

afterEach(() => {
  page?.dispose();
  page = null;
});

function buttonNamed(root: HTMLElement, name: string): HTMLButtonElement {
  const found = root.querySelector<HTMLButtonElement>(`button[aria-label="${name}"]`);
  if (!found) throw new Error(`no button ${name}`);
  return found;
}

describe("templates page", () => {
  it("keeps keyboard focus on the item when Up or Down reaches the end", async () => {
    document.body.innerHTML = '<div id="root"></div>';
    const root = document.getElementById("root")!;
    page = await mountTemplates(root, stubContext());
    buttonNamed(root, "Duplicate Research or answer session to edit").click();

    const down = buttonNamed(root, "Move item 4 down");
    down.focus();
    down.click();
    // The item is now last: its Down button is disabled, so focus moves to its Up.
    expect(buttonNamed(root, "Move item 5 down").disabled).toBe(true);
    expect(document.activeElement).toBe(buttonNamed(root, "Move item 5 up"));

    const up = buttonNamed(root, "Move item 2 up");
    up.focus();
    up.click();
    expect(buttonNamed(root, "Move item 1 up").disabled).toBe(true);
    expect(document.activeElement).toBe(buttonNamed(root, "Move item 1 down"));
  });
});
