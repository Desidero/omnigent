import type {
  ExtensionCatalogItem,
  ExtensionPage,
  ExtensionSlotId,
  ExtensionSlotItem,
  ExtensionSlotKind,
} from "./types";

// The slot contract shared with the Python validator (tests/extensions/test_slot_contract.py).
export const SLOT_KINDS: Readonly<Record<ExtensionSlotId, ExtensionSlotKind>> = {
  "chat.header.actions": "action",
  "composer.actions": "action",
  "session.rightRail.tabs": "tab",
  "settings.sections": "section",
};
/** Most items one extension may place in each slot. */
export const SLOT_ITEM_LIMITS: Readonly<Record<ExtensionSlotId, number>> = {
  "chat.header.actions": 2,
  "composer.actions": 2,
  "session.rightRail.tabs": 2,
  "settings.sections": 3,
};
export const MAX_SLOT_TEXT_LENGTH = 512;
/** Reserved for core entries; the server rejects extension ids that use it. */
export const CORE_ENTRY_ID_PREFIX = "core.";
const ID_SEGMENT = "[a-z0-9](?:[a-z0-9-]*[a-z0-9])?";
export const CONTRIBUTION_ID_PATTERN = new RegExp(`^${ID_SEGMENT}(?:[.-]${ID_SEGMENT})+$`);

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
