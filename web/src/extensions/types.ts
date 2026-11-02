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
  kind: "action" | "tab" | "section" | "decoration" | "set-label" | "row";
  label: string;
  /** Set on page-backed kinds; session-row kinds bind a label instead. */
  page: string | null;
  icon: string | null;
  order: number;
  when: string | null;
  binding?: { source: "label"; key: string } | null;
  /** A set-label item's clear entry, e.g. "Clear status". */
  clear_label?: string | null;
}

export type ExtensionLabelTone = "neutral" | "info" | "success" | "warning" | "danger";

export interface ExtensionLabelValue {
  value: string;
  label: string;
  icon: string;
  tone: ExtensionLabelTone;
}

/** An ordinary session label whose key and allowed values an extension declares. */
export interface ExtensionLabelDeclaration {
  key: string;
  title: string;
  values: ExtensionLabelValue[];
}

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
  labels?: ExtensionLabelDeclaration[];
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
