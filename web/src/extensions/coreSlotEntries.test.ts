import { describe, expect, it } from "vitest";
import { CORE_SETTINGS_SECTIONS, visibleCoreSettingsSections } from "./coreSlotEntries";
import {
  CONTRIBUTION_ID_PATTERN,
  CORE_ENTRY_ID_PREFIX,
  MAX_SLOT_TEXT_LENGTH,
  SLOT_KINDS,
} from "./slots";

describe("core slot entries", () => {
  it.each(CORE_SETTINGS_SECTIONS.map((entry) => [entry.id, entry] as const))(
    "%s meets the slot item contract",
    (_id, entry) => {
      expect(entry.id.startsWith(CORE_ENTRY_ID_PREFIX)).toBe(true);
      expect(entry.id).toMatch(CONTRIBUTION_ID_PATTERN);
      expect(entry.kind).toBe(SLOT_KINDS[entry.slot]);
      expect(entry.label).toBe(entry.label.trim());
      expect(entry.label.length).toBeGreaterThan(0);
      expect(entry.label.length).toBeLessThanOrEqual(MAX_SLOT_TEXT_LENGTH);
      expect(Number.isInteger(entry.order)).toBe(true);
    },
  );

  it("keeps ids, targets and orders unique and in registry order", () => {
    const ids = CORE_SETTINGS_SECTIONS.map((entry) => entry.id);
    const components = CORE_SETTINGS_SECTIONS.map((entry) => entry.component);
    const orders = CORE_SETTINGS_SECTIONS.map((entry) => entry.order);
    expect(new Set(ids).size).toBe(ids.length);
    expect(new Set(components).size).toBe(components.length);
    expect(orders).toEqual([...orders].sort((left, right) => left - right));
    expect(new Set(orders).size).toBe(orders.length);
  });

  it("evaluates visibility on the web from deploy capabilities", () => {
    const ids = (context: Parameters<typeof visibleCoreSettingsSections>[0]) =>
      visibleCoreSettingsSections(context).map((entry) => entry.component);
    const none = {
      hasAuthSession: false,
      integrationsEnabled: false,
      mcpEnabled: false,
      customAgentsEnabled: false,
    };
    expect(ids(none)).toEqual(["general", "appearance", "harnesses", "git", "shortcuts", "import"]);
    expect(
      ids({
        hasAuthSession: true,
        integrationsEnabled: true,
        mcpEnabled: true,
        customAgentsEnabled: true,
      }),
    ).toEqual([
      "account",
      "general",
      "appearance",
      "mcp",
      "integrations",
      "git",
      "shortcuts",
      "import",
    ]);
  });
});
