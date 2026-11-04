// The Goals page's model: the view the server writes to the `goals` key.

export interface GoalItem {
  id: string;
  url: string;
  label: string;
  title: string;
  toggle: "on" | "off" | "";
  status: "watching" | "unmet" | "met" | "stopped" | "paused" | "";
  reason: string;
  note: string;
  wakes: number;
  max_wakes: number;
}

export interface GoalsView {
  all: boolean;
  enabled: boolean;
  items: GoalItem[];
}

export const EMPTY_VIEW: GoalsView = { all: false, enabled: false, items: [] };

const STATUSES = new Set(["watching", "unmet", "met", "stopped", "paused", ""]);

/** Parses the `goals` value; anything unreadable is an empty view. */
export function parseView(raw: string | null | undefined): GoalsView {
  if (!raw) return EMPTY_VIEW;
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return EMPTY_VIEW;
  }
  if (!data || typeof data !== "object") return EMPTY_VIEW;
  const record = data as Record<string, unknown>;
  const items = Array.isArray(record.items) ? record.items : [];
  return {
    all: record.all === true,
    enabled: record.enabled === true,
    items: items.flatMap((item): GoalItem[] => {
      if (!item || typeof item !== "object") return [];
      const value = item as Record<string, unknown>;
      if (typeof value.id !== "string" || typeof value.url !== "string") return [];
      const text = (key: string) => (typeof value[key] === "string" ? (value[key] as string) : "");
      const number = (key: string) => (typeof value[key] === "number" ? (value[key] as number) : 0);
      const toggle = text("toggle");
      const status = text("status");
      return [
        {
          id: value.id,
          url: value.url,
          label: text("label") || value.id,
          title: text("title"),
          toggle: toggle === "on" || toggle === "off" ? toggle : "",
          status: (STATUSES.has(status) ? status : "") as GoalItem["status"],
          reason: text("reason"),
          note: text("note"),
          wakes: number("wakes"),
          max_wakes: number("max_wakes"),
        },
      ];
    }),
  };
}

/** Whether a PR's goal offers Resume: a person's Stop paused it. */
export function canResume(item: GoalItem): boolean {
  return item.status === "paused";
}

/** Whether a PR's box is checked: its own toggle wins, else "All PRs" decides. */
export function isWatched(view: GoalsView, item: GoalItem): boolean {
  if (item.toggle) return item.toggle === "on";
  return view.all;
}

const STATUS_LABELS: Record<GoalItem["status"], string> = {
  watching: "Watching",
  unmet: "Needs work",
  met: "Met",
  stopped: "Stopped",
  paused: "Paused by Stop",
  "": "Not watched",
};

const NOTED = new Set<GoalItem["status"]>(["met", "stopped"]);

/**
 * One line describing a PR's goal; ended goals add why, paused ones how to go on.
 *
 * @param readOnly The viewer can't edit the session, so has no Resume button.
 */
export function describe(item: GoalItem, readOnly = false): string {
  const parts = [STATUS_LABELS[item.status]];
  if (item.max_wakes > 0 && item.status) parts.push(`${item.wakes}/${item.max_wakes} wakes`);
  if (item.status === "paused") {
    parts.push(readOnly ? "someone who can edit this session can resume it" : "Resume to continue");
  } else if (item.note && NOTED.has(item.status)) {
    parts.push(item.note);
  }
  return parts.join(" · ");
}

/** A PR row's status line, and whether it offers Resume (never to read-only viewers). */
export function rowView(item: GoalItem, readOnly: boolean): { detail: string; resume: boolean } {
  return { detail: describe(item, readOnly), resume: canResume(item) && !readOnly };
}
