// Device-local "Needs me" and recency filters that narrow the sidebar to the
// sessions worth looking at. Independent of the My/Shared/All/Archived scope
// and of the flagged grouping options, so they compose with either.

const STORAGE_KEY = "omnigent:sidebar-focus";

const DAY_MS = 24 * 60 * 60 * 1000;

/**
 * The "Updated" choices in menu order. Windows are rolling rather than
 * calendar days, so the shortest one doesn't empty out just after midnight.
 * Ids are persisted: add new ones freely, but don't rename existing ones.
 */
export const SIDEBAR_RECENCY_OPTIONS = [
  { id: "any", label: "Any time", shortLabel: null, windowMs: null },
  { id: "day", label: "Last 24 hours", shortLabel: "24h", windowMs: DAY_MS },
  { id: "three-days", label: "Last 3 days", shortLabel: "3d", windowMs: 3 * DAY_MS },
  { id: "week", label: "Last 7 days", shortLabel: "7d", windowMs: 7 * DAY_MS },
  { id: "month", label: "Last 30 days", shortLabel: "30d", windowMs: 30 * DAY_MS },
] as const;

export type SidebarRecencyOption = (typeof SIDEBAR_RECENCY_OPTIONS)[number];

/** How recently a session must have been updated to stay listed. */
export type SidebarRecency = SidebarRecencyOption["id"];

export interface SidebarFocus {
  /** Only sessions with a pending approval or an unread agent reply. */
  needsMe: boolean;
  recency: SidebarRecency;
}

export const DEFAULT_SIDEBAR_FOCUS: SidebarFocus = { needsMe: false, recency: "any" };

function findRecencyOption(id: unknown): SidebarRecencyOption | undefined {
  return SIDEBAR_RECENCY_OPTIONS.find((option) => option.id === id);
}

/** The menu entry for a recency id. */
export function sidebarRecencyOption(id: SidebarRecency): SidebarRecencyOption {
  return findRecencyOption(id) ?? SIDEBAR_RECENCY_OPTIONS[0];
}

/** Whether either filter narrows the list. */
export function isSidebarFocusActive(focus: SidebarFocus): boolean {
  return focus.needsMe || focus.recency !== "any";
}

/**
 * Read the persisted filters. Each field falls back to its default on its own,
 * so a stale or hand-edited entry can't strand the viewer on a filter the menu
 * no longer offers. Never throws.
 */
export function readSidebarFocus(): SidebarFocus {
  if (typeof window === "undefined") return DEFAULT_SIDEBAR_FOCUS;
  let stored: Partial<Record<keyof SidebarFocus, unknown>>;
  try {
    const parsed: unknown = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "null");
    if (typeof parsed !== "object" || parsed === null) return DEFAULT_SIDEBAR_FOCUS;
    stored = parsed;
  } catch {
    return DEFAULT_SIDEBAR_FOCUS;
  }
  return {
    needsMe: stored.needsMe === true,
    recency: findRecencyOption(stored.recency)?.id ?? DEFAULT_SIDEBAR_FOCUS.recency,
  };
}

/** Persist the filters. Swallows quota/access errors. */
export function writeSidebarFocus(value: SidebarFocus): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
  } catch {
    // A local view preference; losing it is harmless.
  }
}
