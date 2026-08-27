import {
  LayoutDashboardIcon,
  PanelsTopLeftIcon,
  PuzzleIcon,
  SearchIcon,
  type LucideIcon,
} from "lucide-react";

const ICONS: Record<string, LucideIcon> = {
  dashboard: LayoutDashboardIcon,
  "panels-top-left": PanelsTopLeftIcon,
  puzzle: PuzzleIcon,
  search: SearchIcon,
};

export function extensionIcon(name: string | null): LucideIcon {
  return ICONS[name ?? ""] ?? PuzzleIcon;
}
