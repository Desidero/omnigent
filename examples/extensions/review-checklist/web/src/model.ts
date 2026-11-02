// Checklist data and rules, independent of the DOM and the SDK.

export interface ChecklistItem {
  id: string;
  text: string;
}

export interface ChecklistSection {
  heading?: string;
  items: ChecklistItem[];
}

export interface ChecklistTemplate {
  id: string;
  name: string;
  sections: ChecklistSection[];
}

export interface TemplatesRecord {
  version: 1;
  templates: ChecklistTemplate[];
}

export interface DefaultsRecord {
  user?: string;
  projects: Record<string, string>;
}

/** Per-session progress: `t` an explicit template choice, `c` checked item ids, `k` the template the ticks were made on. */
export interface ProgressEntry {
  t?: string;
  c: string[];
  u: number;
  k?: string;
}

export type ProgressRecord = Record<string, ProgressEntry>;

export const STORAGE_KEYS = {
  templates: "templates.v1",
  defaults: "defaults.v1",
  progress: "progress.v1",
} as const;

export const LIMITS = {
  templates: 20,
  itemsPerTemplate: 60,
  itemText: 200,
  name: 60,
  templatesBytes: 30 * 1024,
  defaultsBytes: 8 * 1024,
  progressBytes: 30 * 1024,
  progressSessions: 150,
} as const;

export const DEFAULT_TEMPLATE_ID = "builtin.agent-change-review";

function section(prefix: string, heading: string | undefined, texts: string[]): ChecklistSection {
  return {
    ...(heading ? { heading } : {}),
    items: texts.map((text, index) => ({ id: `${prefix}.${index + 1}`, text })),
  };
}

export const BUILT_IN_TEMPLATES: readonly ChecklistTemplate[] = [
  {
    id: DEFAULT_TEMPLATE_ID,
    name: "Agent change review",
    sections: [
      section("acr.outcome", "Outcome", [
        "The agent's final message says what changed, and it matches what was asked.",
        "Anything the agent couldn't do, or chose not to do, is stated.",
      ]),
      section("acr.code", "Code", [
        "Every changed file is one you expected to change.",
        "No leftover debug output, commented-out code, or secrets in the diff.",
        "No new or raised dependency without a stated reason.",
      ]),
      section("acr.tests", "Tests", [
        "New or changed behaviour has a test.",
        "The test run appears in the session, and it passed. Check the output, not just the agent's claim.",
        "No test was skipped, deleted or loosened to get a pass.",
      ]),
      section("acr.handoff", "Hand-off", [
        "Docs or comments are updated where behaviour changed.",
        "The work is on the expected branch, with nothing left uncommitted.",
        "Follow-ups the agent mentioned are written down somewhere you'll see them.",
      ]),
    ],
  },
  {
    id: "builtin.pull-request-ready",
    name: "Pull request ready",
    sections: [
      section("prr", undefined, [
        "The PR title and description describe the change and why.",
        "The PR targets the right base branch.",
        "CI checks have finished and passed.",
        "Review comments are answered or resolved.",
        "The change is small enough to review, or is split.",
        "Release notes or changelog are updated if the project uses them.",
      ]),
    ],
  },
  {
    id: "builtin.research-answer",
    name: "Research or answer session",
    sections: [
      section("ras", undefined, [
        "The question answered is the one that was asked.",
        "Claims cite a source, a file or a command output.",
        "Assumptions and open questions are listed.",
        "Commands run were read-only, or their effects are stated.",
        "The next step is clear.",
      ]),
    ],
  },
];

export function isBuiltIn(templateId: string): boolean {
  return BUILT_IN_TEMPLATES.some((template) => template.id === templateId);
}

export function allTemplates(user: readonly ChecklistTemplate[]): ChecklistTemplate[] {
  return [...BUILT_IN_TEMPLATES, ...user];
}

export function itemsOf(template: ChecklistTemplate): ChecklistItem[] {
  return template.sections.flatMap((entry) => entry.items);
}

export function newId(prefix: string): string {
  const bytes = new Uint8Array(8);
  crypto.getRandomValues(bytes);
  return `${prefix}-${Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("")}`;
}

export function byteSize(value: unknown): number {
  return new TextEncoder().encode(JSON.stringify(value)).byteLength;
}

export type TemplateSource = "session" | "project" | "user";

export const SOURCE_LABELS: Record<TemplateSource, string> = {
  session: "Chosen for this session",
  project: "Project default",
  user: "Your default",
};

/** Applies the precedence: session choice, project default, your default, the built-in default. */
export function resolveTemplate(options: {
  sessionId: string;
  projectId: string | null;
  templates: readonly ChecklistTemplate[];
  defaults: DefaultsRecord;
  progress: ProgressRecord;
}): { template: ChecklistTemplate; source: TemplateSource } {
  const available = allTemplates(options.templates);
  const find = (id: string | undefined) =>
    id === undefined ? undefined : available.find((template) => template.id === id);
  const chosen = find(options.progress[options.sessionId]?.t);
  if (chosen) return { template: chosen, source: "session" };
  const projectDefault = options.projectId
    ? find(options.defaults.projects[options.projectId])
    : undefined;
  if (projectDefault) return { template: projectDefault, source: "project" };
  return {
    template: find(options.defaults.user) ?? BUILT_IN_TEMPLATES[0],
    source: "user",
  };
}

/** A short content hash, so ticks can tell when their template was edited. */
export function fingerprint(template: ChecklistTemplate): string {
  let hash = 0x811c9dc5;
  const text = JSON.stringify(itemsOf(template).map((item) => [item.id, item.text]));
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return `${template.id}:${(hash >>> 0).toString(36)}`;
}

export function checkedCount(entry: ProgressEntry | undefined, template: ChecklistTemplate): number {
  if (!entry) return 0;
  const checked = new Set(entry.c);
  return itemsOf(template).filter((item) => checked.has(item.id)).length;
}

export function templateChangedSinceTicks(
  entry: ProgressEntry | undefined,
  template: ChecklistTemplate,
): boolean {
  if (!entry?.k || !entry.k.startsWith(`${template.id}:`)) return false;
  return entry.k !== fingerprint(template);
}

export function setChecked(
  progress: ProgressRecord,
  sessionId: string,
  template: ChecklistTemplate,
  itemId: string,
  checked: boolean,
  now: number,
): ProgressRecord {
  const current = progress[sessionId] ?? { c: [], u: now };
  const ids = new Set(current.c);
  if (checked) ids.add(itemId);
  else ids.delete(itemId);
  return prune({
    ...progress,
    [sessionId]: { ...current, c: [...ids], u: now, k: fingerprint(template) },
  });
}

export function uncheckAll(
  progress: ProgressRecord,
  sessionId: string,
  template: ChecklistTemplate,
  now: number,
): ProgressRecord {
  const current = progress[sessionId];
  if (!current) return progress;
  const remove = new Set(itemsOf(template).map((item) => item.id));
  return {
    ...progress,
    [sessionId]: { ...current, c: current.c.filter((id) => !remove.has(id)), u: now },
  };
}

export function chooseTemplate(
  progress: ProgressRecord,
  sessionId: string,
  templateId: string | undefined,
  now: number,
): ProgressRecord {
  const current = progress[sessionId] ?? { c: [], u: now };
  const next: ProgressEntry = { ...current, u: now };
  if (templateId === undefined) delete next.t;
  else next.t = templateId;
  return prune({ ...progress, [sessionId]: next });
}

/** Keeps the most recently updated sessions within the count and size budgets. */
export function prune(progress: ProgressRecord): ProgressRecord {
  const entries = Object.entries(progress).sort(([, left], [, right]) => right.u - left.u);
  let kept = entries.slice(0, LIMITS.progressSessions);
  while (kept.length > 0 && byteSize(Object.fromEntries(kept)) > LIMITS.progressBytes) {
    kept = kept.slice(0, -1);
  }
  return Object.fromEntries(kept);
}

export function duplicateTemplate(template: ChecklistTemplate): ChecklistTemplate {
  return {
    id: newId("tpl"),
    name: `${template.name} (copy)`.slice(0, LIMITS.name),
    sections: template.sections.map((entry) => ({
      ...(entry.heading ? { heading: entry.heading } : {}),
      items: entry.items.map((item) => ({ id: newId("item"), text: item.text })),
    })),
  };
}

/** Returns a reason the templates can't be saved, or null when they fit. */
export function templatesProblem(templates: readonly ChecklistTemplate[]): string | null {
  if (templates.length > LIMITS.templates) {
    return `You can keep at most ${LIMITS.templates} templates.`;
  }
  for (const template of templates) {
    if (itemsOf(template).length > LIMITS.itemsPerTemplate) {
      return `"${template.name}" has more than ${LIMITS.itemsPerTemplate} items.`;
    }
  }
  if (byteSize({ version: 1, templates }) > LIMITS.templatesBytes) {
    return "Templates would use more than 30 KB.";
  }
  return null;
}

const ID_PATTERN = /^[A-Za-z0-9_.-]{1,64}$/;

function readString(value: unknown, max: number, what: string): string {
  if (typeof value !== "string") throw new Error(`${what} must be text.`);
  const trimmed = value.trim();
  if (!trimmed) throw new Error(`${what} is empty.`);
  if (trimmed.length > max) throw new Error(`${what} is longer than ${max} characters.`);
  return trimmed;
}

function readId(value: unknown, what: string): string {
  if (typeof value !== "string" || !ID_PATTERN.test(value)) {
    throw new Error(`${what} has an invalid id.`);
  }
  return value;
}

/** Parses exported JSON into templates, enforcing the storage limits. Throws with a readable reason. */
export function parseTemplatesImport(text: string): ChecklistTemplate[] {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    throw new Error("That isn't valid JSON.");
  }
  const record = data as Partial<TemplatesRecord> | null;
  if (!record || record.version !== 1 || !Array.isArray(record.templates)) {
    throw new Error('Expected an export: {"version": 1, "templates": [...]}.');
  }
  const seen = new Set<string>();
  const templates = record.templates.map((raw, index): ChecklistTemplate => {
    const source = raw as Partial<ChecklistTemplate> | null;
    const label = `Template ${index + 1}`;
    if (!source || typeof source !== "object") throw new Error(`${label} isn't an object.`);
    const id = readId(source.id, label);
    if (isBuiltIn(id) || id.startsWith("builtin.")) {
      throw new Error(`${label} uses a built-in template's id.`);
    }
    if (seen.has(id)) throw new Error(`${label} repeats the id ${id}.`);
    seen.add(id);
    const name = readString(source.name, LIMITS.name, `${label}'s name`);
    if (!Array.isArray(source.sections)) throw new Error(`${label} has no sections.`);
    const itemIds = new Set<string>();
    const sections = source.sections.map((rawSection): ChecklistSection => {
      const entry = rawSection as Partial<ChecklistSection> | null;
      if (!entry || !Array.isArray(entry.items)) throw new Error(`${label} has a section with no items.`);
      const heading =
        entry.heading === undefined || entry.heading === ""
          ? undefined
          : readString(entry.heading, LIMITS.name, `A heading in ${name}`);
      const items = entry.items.map((rawItem): ChecklistItem => {
        const item = rawItem as Partial<ChecklistItem> | null;
        const itemId = readId(item?.id, `An item in ${name}`);
        if (itemIds.has(itemId)) throw new Error(`${name} repeats the item id ${itemId}.`);
        itemIds.add(itemId);
        return { id: itemId, text: readString(item?.text, LIMITS.itemText, `An item in ${name}`) };
      });
      return { ...(heading ? { heading } : {}), items };
    });
    return { id, name, sections };
  });
  const problem = templatesProblem(templates);
  if (problem) throw new Error(problem);
  return templates;
}

/** Merges imported templates by id; returns the result and the names of templates it replaces. */
export function mergeTemplates(
  existing: readonly ChecklistTemplate[],
  imported: readonly ChecklistTemplate[],
): { templates: ChecklistTemplate[]; replaced: string[] } {
  const incoming = new Map(imported.map((template) => [template.id, template]));
  const replaced = existing.filter((template) => incoming.has(template.id)).map((template) => template.name);
  const kept = existing.map((template) => incoming.get(template.id) ?? template);
  const added = imported.filter((template) => !existing.some((current) => current.id === template.id));
  return { templates: [...kept, ...added], replaced };
}

export function relativeTime(timestampMs: number, nowMs: number): string {
  const seconds = Math.round((nowMs - timestampMs) / 1000);
  if (seconds < 45) return "just now";
  const units: [number, string][] = [
    [60, "minute"],
    [3600, "hour"],
    [86400, "day"],
  ];
  for (let index = units.length - 1; index >= 0; index -= 1) {
    const [size, unit] = units[index];
    if (seconds >= size) {
      const count = Math.round(seconds / size);
      if (unit === "day" && count > 30) break;
      return `${count} ${unit}${count === 1 ? "" : "s"} ago`;
    }
  }
  return new Date(timestampMs).toLocaleDateString();
}
