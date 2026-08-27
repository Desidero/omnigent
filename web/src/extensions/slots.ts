import type {
  ExtensionCatalogItem,
  ExtensionPage,
  ExtensionSlotId,
  ExtensionSlotItem,
} from "./types";

export interface ResolvedSlotItem {
  extension: ExtensionCatalogItem;
  item: ExtensionSlotItem;
  page: ExtensionPage;
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
    .sort(
      (left, right) =>
        left.item.order - right.item.order || left.item.id.localeCompare(right.item.id),
    );
}
