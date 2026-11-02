import type { ExtensionContext, ExtensionProjectSummary } from "@omnigent/extension-sdk";
import { button, confirmInline, el, errorMessage, renderKeepingFocus } from "./dom";
import {
  allTemplates,
  BUILT_IN_TEMPLATES,
  byteSize,
  type ChecklistSection,
  type ChecklistTemplate,
  DEFAULT_TEMPLATE_ID,
  duplicateTemplate,
  itemsOf,
  LIMITS,
  mergeTemplates,
  newId,
  parseTemplatesImport,
  STORAGE_KEYS,
  templatesProblem,
} from "./model";
import { BROWSER_ONLY_NOTICE, type ChecklistData, ChecklistStore, saveStateText, UNAVAILABLE_NOTICE } from "./store";

export interface TemplatesPage {
  dispose(): void;
}

export async function mountTemplates(root: HTMLElement, context: ExtensionContext): Promise<TemplatesPage> {
  const content = el("div", { class: "stack" });
  root.replaceChildren(
    el("main", { class: "page", "aria-labelledby": "page-title" }, el("h1", { id: "page-title" }, "Review checklists"), content),
  );
  const saveStatus = el("p", { class: "save-status", id: "save-status" });
  const store = new ChecklistStore(context.storage.user, (state) => {
    saveStatus.textContent = saveStateText(state);
    saveStatus.classList.toggle("is-error", state.kind === "error");
  });
  let data: ChecklistData = await store.load();
  let projects: ExtensionProjectSummary[] | null = null;
  let projectsFailed = false;
  let message = "";
  let exportText = "";
  let importText = "";

  const commitTemplates = (templates: ChecklistTemplate[]): boolean => {
    const problem = templatesProblem(templates);
    if (problem) {
      message = problem;
      render();
      return false;
    }
    data.templates = templates;
    message = "";
    store.saveTemplates(templates);
    return true;
  };

  const saveDefaults = () => {
    // Drop project defaults for projects that no longer exist, once the list is known.
    if (projects) {
      const known = new Set(projects.map((project) => project.id));
      data.defaults.projects = Object.fromEntries(
        Object.entries(data.defaults.projects).filter(([projectId]) => known.has(projectId)),
      );
    }
    if (byteSize(data.defaults) > LIMITS.defaultsBytes) {
      message = "Too many project defaults to save.";
      render();
      return;
    }
    store.save(STORAGE_KEYS.defaults, data.defaults);
  };

  const update = (templateId: string, change: (template: ChecklistTemplate) => ChecklistTemplate, rerender = true) => {
    const next = data.templates.map((template) => (template.id === templateId ? change(template) : template));
    if (commitTemplates(next) && rerender) render();
  };

  const updateSection = (
    templateId: string,
    sectionIndex: number,
    change: (section: ChecklistSection) => ChecklistSection,
    rerender = true,
  ) =>
    update(
      templateId,
      (template) => ({
        ...template,
        sections: template.sections.map((section, index) => (index === sectionIndex ? change(section) : section)),
      }),
      rerender,
    );

  const templateSelect = (id: string, label: string, value: string | undefined, includeDefault: boolean, key: string) => {
    const select = el("select", { id, "data-key": key });
    if (includeDefault) select.append(el("option", { value: "" }, "Use your default"));
    for (const template of allTemplates(data.templates)) {
      const option = el("option", { value: template.id }, template.name);
      option.selected = template.id === value;
      select.append(option);
    }
    if (!value && includeDefault) select.value = "";
    return el("span", { class: "field" }, el("label", { for: id }, label), select);
  };

  const builtInCard = (template: ChecklistTemplate) =>
    el(
      "li",
      { class: "template-row" },
      el("span", {}, el("strong", {}, template.name), el("span", { class: "muted" }, ` · ${itemsOf(template).length} items · built in, read-only`)),
      button("Duplicate to edit", () => {
        const copy = duplicateTemplate(template);
        if (commitTemplates([...data.templates, copy])) {
          render();
          content.querySelector<HTMLElement>(`[data-key="name:${copy.id}"]`)?.focus();
        }
      }, { "aria-label": `Duplicate ${template.name} to edit`, "data-key": `dup:${template.id}` }),
    );

  const itemRow = (template: ChecklistTemplate, sectionIndex: number, itemIndex: number) => {
    const section = template.sections[sectionIndex];
    const item = section.items[itemIndex];
    const inputId = `text-${item.id}`;
    const input = el("input", {
      id: inputId,
      type: "text",
      value: item.text,
      maxlength: LIMITS.itemText,
      "data-key": `text:${item.id}`,
    });
    input.addEventListener("input", () => {
      const text = input.value.trim();
      if (!text) return;
      updateSection(template.id, sectionIndex, (current) => ({
        ...current,
        items: current.items.map((entry) => (entry.id === item.id ? { ...entry, text } : entry)),
      }), false);
    });
    const move = (offset: number) => {
      updateSection(template.id, sectionIndex, (current) => {
        const items = [...current.items];
        const [moved] = items.splice(itemIndex, 1);
        items.splice(itemIndex + offset, 0, moved);
        return { ...current, items };
      });
      // At the top or bottom the pressed button is disabled; keep focus on the item.
      const find = (key: string) => content.querySelector<HTMLButtonElement | HTMLInputElement>(`[data-key="${key}"]`);
      const pressed = find(`${offset < 0 ? "up" : "down"}:${item.id}`);
      if (pressed && !pressed.disabled) return;
      const other = find(`${offset < 0 ? "down" : "up"}:${item.id}`);
      (other && !other.disabled ? other : find(`text:${item.id}`))?.focus();
    };
    const label = `Item ${itemIndex + 1}`;
    return el(
      "li",
      { class: "edit-row" },
      el("label", { for: inputId, class: "visually-hidden" }, `${label} in ${template.name}`),
      input,
      el(
        "span",
        { class: "row-buttons" },
        button("Up", () => move(-1), { disabled: itemIndex === 0, "aria-label": `Move ${label.toLowerCase()} up`, "data-key": `up:${item.id}` }),
        button("Down", () => move(1), {
          disabled: itemIndex === section.items.length - 1,
          "aria-label": `Move ${label.toLowerCase()} down`,
          "data-key": `down:${item.id}`,
        }),
        button("Delete", () => updateSection(template.id, sectionIndex, (current) => ({
          ...current,
          items: current.items.filter((entry) => entry.id !== item.id),
        })), { "aria-label": `Delete ${label.toLowerCase()}`, "data-key": `delete:${item.id}` }),
      ),
    );
  };

  const sectionEditor = (template: ChecklistTemplate, sectionIndex: number) => {
    const section = template.sections[sectionIndex];
    const headingId = `heading-${template.id}-${sectionIndex}`;
    const heading = el("input", {
      id: headingId,
      type: "text",
      value: section.heading ?? "",
      maxlength: LIMITS.name,
      placeholder: "No heading",
      "data-key": `heading:${template.id}:${sectionIndex}`,
    });
    heading.addEventListener("input", () =>
      updateSection(template.id, sectionIndex, (current) => {
        const { heading: _old, ...rest } = current;
        const text = heading.value.trim();
        return text ? { ...rest, heading: text } : rest;
      }, false),
    );
    const newItemId = `new-${template.id}-${sectionIndex}`;
    const newItem = el("input", { id: newItemId, type: "text", maxlength: LIMITS.itemText, "data-key": `new:${template.id}:${sectionIndex}` });
    const add = () => {
      const text = newItem.value.trim();
      if (!text) return;
      updateSection(template.id, sectionIndex, (current) => ({
        ...current,
        items: [...current.items, { id: newId("item"), text }],
      }));
      content.querySelector<HTMLElement>(`[data-key="new:${template.id}:${sectionIndex}"]`)?.focus();
    };
    newItem.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        add();
      }
    });
    return el(
      "fieldset",
      { class: "section-editor" },
      el("legend", {}, `Section ${sectionIndex + 1}`),
      el("span", { class: "field" }, el("label", { for: headingId }, "Heading (optional)"), heading),
      el("ol", { class: "edit-list" }, ...section.items.map((_item, itemIndex) => itemRow(template, sectionIndex, itemIndex))),
      el(
        "span",
        { class: "field add-item" },
        el("label", { for: newItemId }, "New item"),
        el("span", { class: "inline" }, newItem, button("Add item", add, { "data-key": `add:${template.id}:${sectionIndex}` })),
      ),
      template.sections.length > 1
        ? button("Remove section", () => update(template.id, (current) => ({
            ...current,
            sections: current.sections.filter((_section, index) => index !== sectionIndex),
          })), { "data-key": `remove-section:${template.id}:${sectionIndex}` })
        : null,
    );
  };

  const userCard = (template: ChecklistTemplate) => {
    const nameId = `name-${template.id}`;
    const name = el("input", { id: nameId, type: "text", value: template.name, maxlength: LIMITS.name, "data-key": `name:${template.id}` });
    name.addEventListener("input", () => {
      const text = name.value.trim();
      if (text) update(template.id, (current) => ({ ...current, name: text }), false);
    });
    name.addEventListener("change", () => render());
    const remove = button("Delete template", () =>
      confirmInline(remove, `Delete "${template.name}"?`, "Delete", () => {
        if (data.defaults.user === template.id) delete data.defaults.user;
        for (const [projectId, templateId] of Object.entries(data.defaults.projects)) {
          if (templateId === template.id) delete data.defaults.projects[projectId];
        }
        saveDefaults();
        commitTemplates(data.templates.filter((entry) => entry.id !== template.id));
        render();
      }), { class: "danger", "data-key": `delete-template:${template.id}` });
    return el(
      "li",
      { class: "card template-editor", "data-testid": "user-template" },
      el("span", { class: "field" }, el("label", { for: nameId }, "Template name"), name),
      ...template.sections.map((_section, index) => sectionEditor(template, index)),
      el(
        "div",
        { class: "actions" },
        button("Add section", () => update(template.id, (current) => ({ ...current, sections: [...current.sections, { items: [] }] })), {
          "data-key": `add-section:${template.id}`,
        }),
        button("Duplicate", () => {
          if (commitTemplates([...data.templates, duplicateTemplate(template)])) render();
        }, { "aria-label": `Duplicate ${template.name}`, "data-key": `dup:${template.id}` }),
        remove,
      ),
    );
  };

  const defaultsBlock = () => {
    const userDefault = templateSelect("user-default", "Your default template", data.defaults.user ?? DEFAULT_TEMPLATE_ID, false, "user-default");
    userDefault.querySelector("select")!.addEventListener("change", (event) => {
      data.defaults.user = (event.target as HTMLSelectElement).value;
      saveDefaults();
    });
    let projectRows: Node;
    if (projectsFailed) {
      projectRows = el("p", { class: "error" }, "Couldn't load your projects right now. Reload to try again.");
    }
    else if (!projects) projectRows = el("p", { class: "muted" }, "Loading projects…");
    else if (projects.length === 0) projectRows = el("p", { class: "muted" }, "You have no projects.");
    else {
      projectRows = el(
        "table",
        { class: "projects" },
        el("caption", {}, "Project defaults"),
        el("thead", {}, el("tr", {}, el("th", { scope: "col" }, "Project"), el("th", { scope: "col" }, "Template"))),
        el(
          "tbody",
          {},
          ...projects.map((project) => {
            const select = el("select", { id: `project-${project.id}`, "aria-label": `Template for ${project.name}`, "data-key": `project:${project.id}` });
            select.append(el("option", { value: "" }, "Use your default"));
            for (const template of allTemplates(data.templates)) {
              select.append(el("option", { value: template.id }, template.name));
            }
            select.value = data.defaults.projects[project.id] ?? "";
            if (select.value !== (data.defaults.projects[project.id] ?? "")) select.value = "";
            select.addEventListener("change", () => {
              if (select.value) data.defaults.projects[project.id] = select.value;
              else delete data.defaults.projects[project.id];
              saveDefaults();
            });
            return el("tr", {}, el("th", { scope: "row" }, project.name), el("td", {}, select));
          }),
        ),
      );
    }
    return el(
      "section",
      { class: "card", "aria-labelledby": "defaults-title" },
      el("h2", { id: "defaults-title" }, "Defaults"),
      el("p", { class: "muted" }, "A session uses the template you chose for it, then its project's default, then your default."),
      userDefault,
      projectRows,
    );
  };

  const transferBlock = () => {
    const exportArea = el("textarea", { id: "export-text", readonly: true, rows: 6, "data-key": "export-text" });
    exportArea.value = exportText;
    const importArea = el("textarea", { id: "import-text", rows: 6, "data-key": "import-text" });
    importArea.value = importText;
    importArea.addEventListener("input", () => {
      importText = importArea.value;
    });
    const importStatus = el("p", { id: "import-status", "aria-live": "polite" });
    const apply = (templates: ChecklistTemplate[]) => {
      if (commitTemplates(templates)) {
        importText = "";
        message = "Templates imported.";
        render();
      }
    };
    const importButton = button("Import", () => {
      let imported: ChecklistTemplate[];
      try {
        imported = parseTemplatesImport(importArea.value);
      } catch (error) {
        importStatus.textContent = errorMessage(error);
        importStatus.className = "error";
        return;
      }
      const { templates, replaced } = mergeTemplates(data.templates, imported);
      if (replaced.length === 0) return apply(templates);
      confirmInline(importButton, `This replaces: ${replaced.join(", ")}.`, "Replace and import", () => apply(templates));
    }, { "data-key": "import" });
    return el(
      "section",
      { class: "card", "aria-labelledby": "transfer-title" },
      el("h2", { id: "transfer-title" }, "Import and export"),
      el(
        "p",
        { class: "muted" },
        "Copy your templates as text to share them. This isn't sync: a teammate's later changes reach you only if they send a new export.",
      ),
      el("div", { class: "actions" }, button("Export", () => {
        exportText = JSON.stringify({ version: 1, templates: data.templates }, null, 2);
        exportArea.value = exportText;
        exportArea.focus();
        exportArea.select();
      }, { "data-key": "export" })),
      el("span", { class: "field" }, el("label", { for: "export-text" }, "Exported templates (select and copy)"), exportArea),
      el("span", { class: "field" }, el("label", { for: "import-text" }, "Paste templates to import"), importArea),
      el("div", { class: "actions" }, importButton),
      importStatus,
    );
  };

  const storageBlock = () => {
    const used = byteSize({ version: 1, templates: data.templates });
    const nearlyFull = used > LIMITS.templatesBytes * 0.8;
    const forget = button("Forget all review checks", () =>
      confirmInline(forget, "Forget the checks for every session?", "Forget checks", () => {
        data.progress = {};
        void store.remove(STORAGE_KEYS.progress);
      }), { class: "danger", "data-key": "forget" });
    return el(
      "section",
      { class: "card", "aria-labelledby": "storage-title" },
      el("h2", { id: "storage-title" }, "Storage"),
      el(
        "p",
        { class: nearlyFull ? "usage warn" : "usage" },
        nearlyFull ? el("span", { "aria-hidden": "true" }, "⚠ ") : null,
        `Templates use ${Math.ceil(used / 1024)} KB of ${LIMITS.templatesBytes / 1024} KB`,
        nearlyFull ? " (nearly full)" : "",
      ),
      el("p", {}, `Keeps checks for your ${LIMITS.progressSessions} most recent reviews.`),
      el("p", { class: "storage-notice", id: "storage-notice" }, el("span", { "aria-hidden": "true" }, "ⓘ "),
        store.available ? BROWSER_ONLY_NOTICE.replace("these checks", "these checks or templates") : UNAVAILABLE_NOTICE),
      el("div", { class: "actions" }, forget),
    );
  };

  const render = () =>
    renderKeepingFocus(content, () => [
      el("p", { class: "message", role: "status" }, message),
      el(
        "section",
        { class: "card", "aria-labelledby": "builtin-title" },
        el("h2", { id: "builtin-title" }, "Built-in templates"),
        el("ul", { class: "template-list" }, ...BUILT_IN_TEMPLATES.map(builtInCard)),
      ),
      el(
        "section",
        { "aria-labelledby": "yours-title" },
        el("h2", { id: "yours-title" }, "Your templates"),
        data.templates.length === 0 ? el("p", { class: "muted" }, "None yet. Duplicate a built-in template or start a new one.") : null,
        el("ul", { class: "template-editors" }, ...data.templates.map(userCard)),
        el("div", { class: "actions" }, button("New template", () => {
          const template: ChecklistTemplate = { id: newId("tpl"), name: "New template", sections: [{ items: [] }] };
          if (commitTemplates([...data.templates, template])) {
            render();
            content.querySelector<HTMLElement>(`[data-key="name:${template.id}"]`)?.focus();
          }
        }, { "data-key": "new-template" })),
      ),
      defaultsBlock(),
      transferBlock(),
      storageBlock(),
      saveStatus,
    ]);

  render();
  try {
    projects = await context.projects.list();
  } catch {
    projectsFailed = true;
  }
  render();
  return { dispose: () => store.flush() };
}
