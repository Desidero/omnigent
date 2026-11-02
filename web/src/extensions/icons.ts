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
  // Own keys only: manifest names like "constructor" must not reach Object.prototype.
  return name !== null && Object.hasOwn(ICONS, name) ? ICONS[name] : PuzzleIcon;
}
