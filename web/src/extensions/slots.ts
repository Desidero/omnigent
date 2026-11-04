import type {
  ExtensionCatalogItem,
  ExtensionCommand,
  ExtensionFieldValue,
  ExtensionPage,
  ExtensionSlotId,
  ExtensionSlotItem,
  ExtensionSlotKind,
  ExtensionStateField,
  PublishedFields,
} from "./types";

// The slot contract shared with the Python validator (tests/extensions/test_slot_contract.py).
export const SLOT_KINDS: Readonly<Record<ExtensionSlotId, ExtensionSlotKind>> = {
  "chat.header.actions": "action",
  "composer.actions": "action",
  "session.rightRail.tabs": "tab",
  "settings.sections": "section",
  "session.row.decorations": "decoration",
  "session.row.menu": "command",
  "session.row.hover": "row",
};
/** Most items one extension may place in each slot. */
export const SLOT_ITEM_LIMITS: Readonly<Record<ExtensionSlotId, number>> = {
  "chat.header.actions": 2,
  "composer.actions": 2,
  "session.rightRail.tabs": 2,
  "settings.sections": 3,
  "session.row.decorations": 1,
  "session.row.menu": 1,
  "session.row.hover": 1,
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

/** A decoration or hover row bound to one of its extension's published fields. */
export interface ResolvedFieldSlotItem {
  extension: ExtensionCatalogItem;
  item: ExtensionSlotItem;
  field: ExtensionStateField;
}

/** One entry of a row-menu item's choices: the bound value, shown as its field lists it. */
export interface CommandChoice {
  /** The argument value sent with the command. */
  argument: string;
  /** The field value it writes, when the command writes the bare argument. */
  presentation: ExtensionFieldValue | null;
}

/** A row-menu item and the commands it runs. */
export interface ResolvedCommandSlotItem {
  extension: ExtensionCatalogItem;
  item: ExtensionSlotItem;
  command: ExtensionCommand;
  /** The listed choices of the command's one argument; null for a plain entry. */
  choices: CommandChoice[] | null;
  clear: ExtensionCommand | null;
  /** The published field whose current value the choices check, if any. */
  field: ExtensionStateField | null;
}

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

function publishedField(
  extension: ExtensionCatalogItem,
  key: string | undefined,
): ExtensionStateField | null {
  return (
    (extension.state_fields ?? []).find(
      (candidate) => candidate.key === key && candidate.visibility === "published",
    ) ?? null
  );
}

/** Session-row items whose binding names a published field of the same extension. */
export function resolveFieldSlotItems(
  extensions: ExtensionCatalogItem[],
  slot: ExtensionSlotId,
): ResolvedFieldSlotItem[] {
  return extensions
    .flatMap((extension) =>
      extension.slot_items.flatMap((item) => {
        if (item.slot !== slot || item.binding?.source !== "published_field") return [];
        const field = publishedField(extension, item.binding.key);
        return field ? [{ extension, item, field }] : [];
      }),
    )
    .sort(byOrder);
}

/**
 * Row-menu items whose command the catalog lists: a plain entry for a command
 * without arguments, or a list of choices for one with a single `choices` argument.
 */
export function resolveCommandSlotItems(
  extensions: ExtensionCatalogItem[],
  slot: ExtensionSlotId,
): ResolvedCommandSlotItem[] {
  return extensions
    .flatMap((extension) =>
      extension.slot_items.flatMap((item): ResolvedCommandSlotItem[] => {
        if (item.slot !== slot || item.kind !== "command") return [];
        const commands = extension.commands ?? [];
        const command = commands.find((candidate) => candidate.id === item.command);
        if (!command) return [];
        const clear = commands.find((candidate) => candidate.id === item.clear_command) ?? null;
        if (command.arguments.length === 0) {
          return [{ extension, item, command, choices: null, clear: null, field: null }];
        }
        const [argument] = command.arguments;
        if (command.arguments.length !== 1 || argument.choices.length === 0) return [];
        // Choices show as the field's values only when the command writes the bare argument.
        const field =
          command.action.type === "set_state" && command.action.value === `{${argument.name}}`
            ? publishedField(extension, command.action.field)
            : null;
        const choices = argument.choices.map((choice) => ({
          argument: choice,
          presentation: field?.values.find((value) => value.value === choice) ?? null,
        }));
        return [{ extension, item, command, choices, clear, field }];
      }),
    )
    .sort(byOrder);
}

/** A session's raw published value for one field, or null when absent or empty. */
export function publishedFieldText(
  publishedFields: PublishedFields | null | undefined,
  extensionId: string,
  key: string,
): string | null {
  const fields =
    publishedFields && Object.hasOwn(publishedFields, extensionId)
      ? publishedFields[extensionId]
      : null;
  if (!fields || !Object.hasOwn(fields, key)) return null;
  return fields[key] === "" ? null : fields[key];
}

/** The listed value a field holds, or null when absent, empty or unlisted. */
export function listedFieldValue(
  field: ExtensionStateField,
  text: string | null,
): ExtensionFieldValue | null {
  return text === null ? null : (field.values.find((value) => value.value === text) ?? null);
}
