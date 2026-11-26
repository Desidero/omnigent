// Whether the route is bare /settings, with no Settings page open.

import { useLocation } from "@/lib/routing";

/** True on bare `/settings`, where no page is open; the phone layout shows the page list there. */
export function useAtSettingsRoot(): boolean {
  const segments = useLocation().pathname.split("/").filter(Boolean);
  return segments.length > 0 && segments.lastIndexOf("settings") === segments.length - 1;
}
