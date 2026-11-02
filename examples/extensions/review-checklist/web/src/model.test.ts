import { describe, expect, it } from "vitest";
import {
  BUILT_IN_TEMPLATES,
  checkedCount,
  chooseTemplate,
  DEFAULT_TEMPLATE_ID,
  duplicateTemplate,
  itemsOf,
  LIMITS,
  mergeTemplates,
  parseTemplatesImport,
  prune,
  type ProgressRecord,
  resolveTemplate,
  setChecked,
  templateChangedSinceTicks,
  uncheckAll,
} from "./model";

const [agentReview, prReady, research] = BUILT_IN_TEMPLATES;

describe("built-in templates", () => {
  it("default to the agent change review with eleven items", () => {
    expect(agentReview.id).toBe(DEFAULT_TEMPLATE_ID);
    expect(itemsOf(agentReview)).toHaveLength(11);
    expect(itemsOf(prReady)).toHaveLength(6);
    expect(itemsOf(research)).toHaveLength(5);
  });
});

describe("resolveTemplate", () => {
  const custom = duplicateTemplate(prReady);
  const base = { sessionId: "s1", projectId: "p1", templates: [custom] };

  it("prefers the session choice, then the project default, then your default", () => {
    const defaults = { user: research.id, projects: { p1: custom.id } };
    const chosen = chooseTemplate({}, "s1", prReady.id, 1);
    expect(resolveTemplate({ ...base, defaults, progress: chosen })).toMatchObject({
      template: { id: prReady.id },
      source: "session",
    });
    expect(resolveTemplate({ ...base, defaults, progress: {} })).toMatchObject({
      template: { id: custom.id },
      source: "project",
    });
    expect(resolveTemplate({ ...base, projectId: null, defaults, progress: {} })).toMatchObject({
      template: { id: research.id },
      source: "user",
    });
  });

  it("falls back to the built-in default when stored ids no longer exist", () => {
    const defaults = { user: "tpl-gone", projects: { p1: "tpl-gone" } };
    const progress = chooseTemplate({}, "s1", "tpl-gone", 1);
    expect(resolveTemplate({ ...base, defaults, progress })).toMatchObject({
      template: { id: DEFAULT_TEMPLATE_ID },
      source: "user",
    });
  });
});

describe("progress", () => {
  const [first, second] = itemsOf(agentReview);

  it("counts only the current template's items and survives a template switch", () => {
    let progress = setChecked({}, "s1", agentReview, first.id, true, 1);
    progress = setChecked(progress, "s1", agentReview, second.id, true, 2);
    expect(checkedCount(progress.s1, agentReview)).toBe(2);
    progress = chooseTemplate(progress, "s1", prReady.id, 3);
    expect(checkedCount(progress.s1, prReady)).toBe(0);
    progress = chooseTemplate(progress, "s1", undefined, 4);
    expect(progress.s1.t).toBeUndefined();
    expect(checkedCount(progress.s1, agentReview)).toBe(2);
    expect(checkedCount(uncheckAll(progress, "s1", agentReview, 5).s1, agentReview)).toBe(0);
  });

  it("notices when the template changed after ticks were saved", () => {
    const custom = duplicateTemplate(agentReview);
    const progress = setChecked({}, "s1", custom, itemsOf(custom)[0].id, true, 1);
    expect(templateChangedSinceTicks(progress.s1, custom)).toBe(false);
    const edited = {
      ...custom,
      sections: [{ items: [...itemsOf(custom), { id: "item-new", text: "Screenshots attached" }] }],
    };
    expect(templateChangedSinceTicks(progress.s1, edited)).toBe(true);
    expect(templateChangedSinceTicks(progress.s1, prReady)).toBe(false);
  });

  it("evicts the least recently updated sessions beyond the cap", () => {
    const progress: ProgressRecord = {};
    for (let index = 0; index < LIMITS.progressSessions + 5; index += 1) {
      progress[`s${index}`] = { c: [], u: index };
    }
    const kept = prune(progress);
    expect(Object.keys(kept)).toHaveLength(LIMITS.progressSessions);
    expect(kept.s0).toBeUndefined();
    expect(kept[`s${LIMITS.progressSessions + 4}`]).toBeDefined();
  });
});

describe("import", () => {
  const custom = duplicateTemplate(prReady);

  it("round-trips an export and merges by id", () => {
    const text = JSON.stringify({ version: 1, templates: [{ ...custom, name: "Renamed" }] });
    const imported = parseTemplatesImport(text);
    const merged = mergeTemplates([custom], imported);
    expect(merged.replaced).toEqual([custom.name]);
    expect(merged.templates).toHaveLength(1);
    expect(merged.templates[0].name).toBe("Renamed");
  });

  it.each([
    ["not json", "isn't valid JSON"],
    [JSON.stringify({ templates: [] }), "Expected an export"],
    [JSON.stringify({ version: 1, templates: [{ ...custom, id: DEFAULT_TEMPLATE_ID }] }), "built-in"],
    [JSON.stringify({ version: 1, templates: [{ ...custom, name: "x".repeat(61) }] }), "longer than 60"],
    [
      JSON.stringify({
        version: 1,
        templates: [{ ...custom, sections: [{ items: [{ id: "a", text: "<b>" }, { id: "a", text: "x" }] }] }],
      }),
      "repeats the item id",
    ],
  ])("rejects %s", (text, reason) => {
    expect(() => parseTemplatesImport(text)).toThrow(reason);
  });
});
