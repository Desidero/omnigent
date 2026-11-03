// The Goals page's model: the view the server writes to the `goals` key.

export interface GoalItem {
  id: string;
  url: string;
  label: string;
  title: string;
  toggle: "on" | "off" | "";
  status: "watching" | "unmet" | "met" | "stopped" | "";
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

const STATUSES = new Set(["watching", "unmet", "met", "stopped", ""]);

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
  "": "Not watched",
};

/** One line describing a PR's goal. */
export function describe(item: GoalItem): string {
  const parts = [STATUS_LABELS[item.status]];
  if (item.max_wakes > 0 && item.status) parts.push(`${item.wakes}/${item.max_wakes} wakes`);
  if (item.note && (item.status === "met" || item.status === "stopped")) parts.push(item.note);
  return parts.join(" · ");
}
