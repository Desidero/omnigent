export interface ExtensionPage {
  id: string;
  title: string;
  route: string;
  view: string;
}

export interface ExtensionPrimaryNavigation {
  id: string;
  label: string;
  page: string;
  icon: string | null;
  order: number;
  when: string | null;
}

export interface ExtensionSessionSummary {
  id: string;
  title: string | null;
  status: "idle" | "running" | "waiting" | "failed";
  /** A finished turn the current user has not viewed yet (the sidebar's unread rule). */
  unread: boolean;
  /** True when `title` is the shell's provisional first-message title (no server title yet). */
  titleProvisional: boolean;
  workspace: string | null;
  gitBranch: string | null;
  projectId: string | null;
  createdAt: number;
  updatedAt: number;
}

export interface ExtensionSessionPage {
  sessions: ExtensionSessionSummary[];
  nextCursor: string | null;
  hasMore: boolean;
}

export interface ExtensionPullRequest {
  number: number;
  title: string;
  state: string;
  url: string;
}

export interface ExtensionProjectSummary {
  id: string;
  name: string;
  icon: string | null;
}

export type ExtensionSlotId =
  | "chat.header.actions"
  | "composer.actions"
  | "session.rightRail.tabs"
  | "settings.sections"
  | "session.row.decorations"
  | "session.row.menu"
  | "session.row.hover";

export interface ExtensionSlotItem {
  id: string;
  slot: ExtensionSlotId;
  kind: "action" | "tab" | "section" | "decoration" | "command" | "row";
  label: string;
  /** Set on page-backed kinds; session-row kinds bind a field or name a command instead. */
  page: string | null;
  icon: string | null;
  order: number;
  when: string | null;
  /** The published state field a decoration or hover row shows. */
  binding?: { source: "published_field"; key: string } | null;
  /** The command a row-menu item runs, or whose single `choices` argument it lists. */
  command?: string | null;
  /** A no-argument command listed after a row-menu item's choices, e.g. "Clear status". */
  clear_command?: string | null;
  /** A published field whose value, when set, a header or composer action shows as its label. */
  label_field?: string | null;
}

export type ExtensionFieldTone = "neutral" | "info" | "success" | "warning" | "danger";

/** One listed value of a published field, with how session rows show it. */
export interface ExtensionFieldValue {
  value: string;
  label: string;
  icon: string;
  tone: ExtensionFieldTone;
}

/** A declared state key (or `prefix*`) and who may read it. */
export interface ExtensionStateField {
  key: string;
  visibility: "service" | "editors" | "readers" | "published";
  max_length: number | null;
  values: ExtensionFieldValue[];
}

export interface ExtensionCommandArgument {
  name: string;
  choices: string[];
  pattern: string | null;
  max_length: number;
}

/** A command users run on a session; the server checks `required_access`. */
export interface ExtensionCommand {
  id: string;
  title: string;
  arguments: ExtensionCommandArgument[];
  required_access: "read" | "edit";
  /** Shown before running; the server does not enforce it. */
  confirm: string | null;
  action: { type: "set_state" | "clear_state"; field: string; value: string | null };
}

/** Enabled extensions' published fields on a session, by extension id then key. */
export type PublishedFields = Record<string, Record<string, string>>;

export interface ExtensionBrowserBundle {
  declared: boolean;
  has_styles: boolean;
  digest: string | null;
  script_url: string | null;
  style_url: string | null;
}

export interface ExtensionCatalogItem {
  object: "extension";
  id: string;
  display_name: string;
  distribution: string;
  version: string;
  extension_api: number;
  status: "enabled" | "unavailable";
  permissions: string[];
  pages: ExtensionPage[];
  primary_navigation: ExtensionPrimaryNavigation[];
  slot_items: ExtensionSlotItem[];
  /** Published fields only; absent from servers without extension state, empty until enabled. */
  state_fields?: ExtensionStateField[];
  commands?: ExtensionCommand[];
  browser: ExtensionBrowserBundle;
}

export interface ExtensionCatalogResponse {
  object: "list";
  data: ExtensionCatalogItem[];
}

export interface ResolvedExtensionPage {
  extension: ExtensionCatalogItem;
  page: ExtensionPage;
}
