import type { StoredOpenItem } from "@/lib/openItems";

const KINDS = { Q: "question", R: "risk", F: "finding", T: "follow_up", L: "link" } as const;

/** A stored item as `GET …/open-items` returns it, open unless `fields` say otherwise. */
export function storedItem(label: string, fields: Partial<StoredOpenItem> = {}): StoredOpenItem {
  return {
    label,
    kind: KINDS[label[0] as keyof typeof KINDS],
    number: Number(label.slice(1)),
    status: "open",
    title: `Title of ${label}`,
    detail: "",
    topic: null,
    links: [],
    url: null,
    raised_by: null,
    created_at: 1_764_100_000,
    updated_at: 1_764_100_000,
    closed_at: null,
    resolution: null,
    closed_by: null,
    replies: [],
    ...fields,
  };
}
