import {
  CircleCheckIcon,
  CircleEllipsisIcon,
  EyeIcon,
  LayoutDashboardIcon,
  ListChecksIcon,
  OctagonAlertIcon,
  PanelsTopLeftIcon,
  PuzzleIcon,
  SearchIcon,
  SquareParkingIcon,
  type LucideIcon,
} from "lucide-react";

// Mirrors APPROVED_ICONS in omnigent/extensions/registry.py.
const ICONS: Record<string, LucideIcon> = {
  "circle-check": CircleCheckIcon,
  "circle-ellipsis": CircleEllipsisIcon,
  dashboard: LayoutDashboardIcon,
  eye: EyeIcon,
  "list-checks": ListChecksIcon,
  "octagon-alert": OctagonAlertIcon,
  "panels-top-left": PanelsTopLeftIcon,
  puzzle: PuzzleIcon,
  search: SearchIcon,
  "square-parking": SquareParkingIcon,
};

/** An approved icon, or null; for session-row items and field values, which have no fallback. */
export function approvedExtensionIcon(name: string | null): LucideIcon | null {
  // Own keys only: manifest names like "constructor" must not reach Object.prototype.
  return name !== null && Object.hasOwn(ICONS, name) ? ICONS[name] : null;
}

export function extensionIcon(name: string | null): LucideIcon {
  return approvedExtensionIcon(name) ?? PuzzleIcon;
}
