// Core's own slot entries. They share the extension item contract but target
// React components, so core surfaces render with no catalog, network, or user.

import {
  BlocksIcon,
  DownloadIcon,
  GitBranchIcon,
  KeyboardIcon,
  PaletteIcon,
  PlugIcon,
  SettingsIcon,
  UserCogIcon,
  VectorSquareIcon,
  type LucideIcon,
} from "lucide-react";
import type { SettingsSectionId } from "@/shell/settingsNav";
import type { ExtensionSlotId, ExtensionSlotKind } from "./types";

export interface CoreSlotEntry<Component extends string, Context> {
  id: `core.${string}`;
  slot: ExtensionSlotId;
  kind: ExtensionSlotKind;
  label: string;
  icon: LucideIcon;
  /** Position among core's entries; extension items always follow them. */
  order: number;
  component: Component;
  /** Core-only and web-evaluated; extension items never carry one. */
  isVisible?: (context: Context) => boolean;
  hideOnMobile?: boolean;
}

export interface CoreSettingsContext {
  hasAuthSession: boolean;
  integrationsEnabled: boolean;
  mcpEnabled: boolean;
  customAgentsEnabled: boolean;
}

export type CoreSettingsSection = CoreSlotEntry<SettingsSectionId, CoreSettingsContext>;

function settingsSection(entry: Omit<CoreSettingsSection, "slot" | "kind">): CoreSettingsSection {
  return { ...entry, slot: "settings.sections", kind: "section" };
}

/** The General settings group, in display order. */
export const CORE_SETTINGS_SECTIONS: readonly CoreSettingsSection[] = [
  settingsSection({
    id: "core.settings.account",
    component: "account",
    label: "Account",
    icon: UserCogIcon,
    order: 100,
    // Leads the group on deploys with sign-in; it's the most-visited section there.
    isVisible: (context) => context.hasAuthSession,
  }),
  settingsSection({
    id: "core.settings.general",
    component: "general",
    label: "General",
    icon: SettingsIcon,
    order: 110,
  }),
  settingsSection({
    id: "core.settings.appearance",
    component: "appearance",
    label: "Appearance",
    icon: PaletteIcon,
    order: 120,
  }),
  settingsSection({
    id: "core.settings.mcp",
    component: "mcp",
    label: "MCP",
    icon: PlugIcon,
    order: 130,
    isVisible: (context) => context.mcpEnabled,
  }),
  settingsSection({
    // Provider credentials; MCP accounts have their own section above.
    id: "core.settings.integrations",
    component: "integrations",
    label: "Sandbox Integrations",
    icon: BlocksIcon,
    order: 140,
    isVisible: (context) => context.integrationsEnabled,
  }),
  settingsSection({
    // Moves to the Customize group when custom agents are on.
    id: "core.settings.harnesses",
    component: "harnesses",
    label: "Harnesses",
    icon: VectorSquareIcon,
    order: 150,
    isVisible: (context) => !context.customAgentsEnabled,
  }),
  settingsSection({
    id: "core.settings.git",
    component: "git",
    label: "Git",
    icon: GitBranchIcon,
    order: 160,
  }),
  settingsSection({
    id: "core.settings.shortcuts",
    component: "shortcuts",
    label: "Keyboard shortcuts",
    icon: KeyboardIcon,
    order: 170,
    hideOnMobile: true,
  }),
  settingsSection({
    id: "core.settings.import",
    component: "import",
    label: "Import sessions",
    icon: DownloadIcon,
    order: 180,
  }),
];

export function visibleCoreSettingsSections(context: CoreSettingsContext): CoreSettingsSection[] {
  return CORE_SETTINGS_SECTIONS.filter((entry) => entry.isVisible?.(context) ?? true);
}
