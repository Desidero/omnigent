import type { ExtensionContext } from "@omnigent/extension-sdk";
import {
  type ChecklistTemplate,
  type DefaultsRecord,
  type ProgressEntry,
  type ProgressRecord,
  prune,
  STORAGE_KEYS,
  type TemplatesRecord,
} from "./model";

type UserStorage = ExtensionContext["storage"]["user"];
type Key = (typeof STORAGE_KEYS)[keyof typeof STORAGE_KEYS];

export const SAVE_DELAY_MS = 500;

export type SaveState =
  | { kind: "idle" }
  | { kind: "saving" }
  | { kind: "saved" }
  | { kind: "error"; message: string };

export interface ChecklistData {
  templates: ChecklistTemplate[];
  defaults: DefaultsRecord;
  progress: ProgressRecord;
}

function isUnavailable(error: unknown): boolean {
  return (error as { code?: unknown } | null)?.code === "Unavailable";
}

function progressRecord(value: ProgressRecord | null): ProgressRecord {
  return value && typeof value === "object" ? value : {};
}

/**
 * Browser-local persistence through the SDK's `storage.user`.
 * Saves are debounced; failures are reported and the state stays in memory.
 */
export class ChecklistStore {
  available = true;
  private timers = new Map<Key, ReturnType<typeof setTimeout>>();
  private pending = new Map<Key, unknown>();
  // Sessions this page changed since its last progress write.
  private progressChanges: ProgressRecord = {};

  constructor(
    private readonly storage: UserStorage,
    private readonly onSaveState: (state: SaveState) => void,
  ) {}

  async load(): Promise<ChecklistData> {
    const empty: ChecklistData = { templates: [], defaults: { projects: {} }, progress: {} };
    try {
      const [templates, defaults, progress] = await Promise.all([
        this.storage.get<TemplatesRecord>(STORAGE_KEYS.templates),
        this.storage.get<DefaultsRecord>(STORAGE_KEYS.defaults),
        this.storage.get<ProgressRecord>(STORAGE_KEYS.progress),
      ]);
      return {
        templates: templates?.version === 1 && Array.isArray(templates.templates) ? templates.templates : [],
        defaults: {
          ...(typeof defaults?.user === "string" ? { user: defaults.user } : {}),
          projects: defaults?.projects && typeof defaults.projects === "object" ? defaults.projects : {},
        },
        progress: progressRecord(progress),
      };
    } catch (error) {
      if (!isUnavailable(error)) throw error;
      this.available = false;
      return empty;
    }
  }

  save(key: Key, value: unknown): void {
    if (!this.available) return;
    this.pending.set(key, value);
    clearTimeout(this.timers.get(key));
    this.onSaveState({ kind: "saving" });
    this.timers.set(
      key,
      setTimeout(() => void this.write(key), SAVE_DELAY_MS),
    );
  }

  saveTemplates(templates: ChecklistTemplate[]): void {
    this.save(STORAGE_KEYS.templates, { version: 1, templates } satisfies TemplatesRecord);
  }

  /**
   * Saves one session's progress. The write merges it into the stored record,
   * so pages open on other sessions keep their ticks.
   */
  saveProgress(sessionId: string, entry: ProgressEntry | undefined): void {
    if (!entry) return;
    this.progressChanges = { ...this.progressChanges, [sessionId]: entry };
    this.save(STORAGE_KEYS.progress, this.progressChanges);
  }

  async remove(key: Key): Promise<void> {
    clearTimeout(this.timers.get(key));
    this.pending.delete(key);
    if (key === STORAGE_KEYS.progress) this.progressChanges = {};
    if (!this.available) return;
    try {
      await this.storage.delete(key);
      this.onSaveState({ kind: "saved" });
    } catch (error) {
      this.fail(error);
    }
  }

  /** Writes anything still waiting for its debounce, e.g. when the page goes away. */
  flush(): void {
    for (const key of [...this.pending.keys()]) {
      clearTimeout(this.timers.get(key));
      void this.write(key);
    }
  }

  private async write(key: Key): Promise<void> {
    if (!this.pending.has(key)) return;
    let value = this.pending.get(key);
    this.pending.delete(key);
    try {
      if (key === STORAGE_KEYS.progress) {
        this.progressChanges = {};
        const stored = await this.storage.get<ProgressRecord>(key);
        value = prune({ ...progressRecord(stored), ...(value as ProgressRecord) });
      }
      await this.storage.set(key, value);
      if (this.pending.size === 0) this.onSaveState({ kind: "saved" });
    } catch (error) {
      if (isUnavailable(error)) this.available = false;
      this.fail(error);
    }
  }

  private fail(error: unknown): void {
    const reason =
      (error as { code?: unknown } | null)?.code === "QuotaExceeded"
        ? "browser storage for this extension is full"
        : error instanceof Error
          ? error.message
          : "storage failed";
    this.onSaveState({
      kind: "error",
      message: `Couldn't save (${reason}). Your changes stay on this page until you leave it.`,
    });
  }
}

export const BROWSER_ONLY_NOTICE =
  "Saved in this browser only. Collaborators, other devices and other browsers don't see these checks; clearing site data removes them.";

export const UNAVAILABLE_NOTICE =
  "Can't save in this browser: your checks will be lost when you leave this page.";

export function saveStateText(state: SaveState): string {
  switch (state.kind) {
    case "saving":
      return "Saving in this browser…";
    case "saved":
      return "Saved in this browser.";
    case "error":
      return state.message;
    default:
      return "";
  }
}
