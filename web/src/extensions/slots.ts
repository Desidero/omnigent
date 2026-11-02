import type {
  ExtensionCatalogItem,
  ExtensionLabelDeclaration,
  ExtensionLabelValue,
  ExtensionPage,
  ExtensionSlotId,
  ExtensionSlotItem,
} from "./types";

export interface ResolvedSlotItem {
  extension: ExtensionCatalogItem;
  item: ExtensionSlotItem;
  page: ExtensionPage;
}

export interface ResolvedLabelSlotItem {
  extension: ExtensionCatalogItem;
  item: ExtensionSlotItem;
  label: ExtensionLabelDeclaration;
}

const SET_LABEL_PERMISSION = "sessions.labels.write";

function byOrder(left: { item: ExtensionSlotItem }, right: { item: ExtensionSlotItem }): number {
  return left.item.order - right.item.order || left.item.id.localeCompare(right.item.id);
}

export function resolveSlotItems(
  extensions: ExtensionCatalogItem[],
  slot: ExtensionSlotId,
): ResolvedSlotItem[] {
  return extensions
    .flatMap((extension) =>
      extension.slot_items.flatMap((item) => {
        if (item.slot !== slot) return [];
        const page = extension.pages.find((candidate) => candidate.id === item.page);
        return page ? [{ extension, item, page }] : [];
      }),
    )
    .sort(byOrder);
}

/** Session-row items whose binding names a label the same extension declares. */
export function resolveLabelSlotItems(
  extensions: ExtensionCatalogItem[],
  slot: ExtensionSlotId,
): ResolvedLabelSlotItem[] {
  return extensions
    .flatMap((extension) =>
      extension.slot_items.flatMap((item) => {
        if (item.slot !== slot || item.binding?.source !== "label") return [];
        if (item.kind === "set-label" && !extension.permissions.includes(SET_LABEL_PERMISSION)) {
          return [];
        }
        const key = item.binding.key;
        const label = (extension.labels ?? []).find((candidate) => candidate.key === key);
        return label ? [{ extension, item, label }] : [];
      }),
    )
    .sort(byOrder);
}

/** The declared value a session's labels hold, or null when absent, empty or unknown. */
export function declaredLabelValue(
  label: ExtensionLabelDeclaration,
  labels: Record<string, string> | null | undefined,
): ExtensionLabelValue | null {
  if (!labels || !Object.hasOwn(labels, label.key)) return null;
  const current = labels[label.key];
  return label.values.find((candidate) => candidate.value === current) ?? null;
}
