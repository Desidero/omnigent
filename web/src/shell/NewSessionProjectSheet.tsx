// Phone form of the new-session project prompt: a bottom sheet listing No project and
// every project, without a search field so the keyboard stays down.

import type React from "react";
import { CircleSlashIcon } from "lucide-react";

import { BottomSheet, BottomSheetContent } from "@/components/ui/bottom-sheet";
import { cn } from "@/lib/utils";

import { MOBILE_GLASS_SURFACE } from "./mobileGlass";
import type { NewSessionProjectChoiceProps } from "./NewSessionProjectPrompt";
import { ProjectRowIcon } from "./ProjectPicker";

function SheetRow({
  icon,
  label,
  current = false,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  /** The project in view. */
  current?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-current={current ? "true" : undefined}
      className={cn(
        "flex min-h-12 w-full items-center gap-3.5 px-4 text-left text-[17px] text-foreground outline-none active:bg-foreground/[0.06] focus-visible:bg-foreground/[0.06]",
        current && "font-medium",
      )}
    >
      {icon}
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {current && <span className="shrink-0 text-[15px] text-muted-foreground">Current</span>}
    </button>
  );
}

export function NewSessionProjectSheet({
  open,
  onOpenChange,
  projects,
  loading,
  currentProject,
  onStart,
}: NewSessionProjectChoiceProps) {
  return (
    <BottomSheet open={open} onOpenChange={onOpenChange}>
      <BottomSheetContent title="Start a new session in" className={MOBILE_GLASS_SURFACE}>
        <div className="min-h-0 overflow-y-auto overscroll-contain px-2 pb-2">
          <div className="flex flex-col divide-y divide-border overflow-hidden rounded-2xl bg-foreground/[0.04]">
            <SheetRow
              icon={<CircleSlashIcon aria-hidden="true" className="size-5 text-muted-foreground" />}
              label="No project"
              onClick={() => onStart(null)}
            />
            {projects.map((project) => (
              <SheetRow
                key={project.name}
                icon={<ProjectRowIcon icon={project.icon} className="size-5 text-[18px]" />}
                label={project.name}
                current={project.name === currentProject}
                onClick={() => onStart(project.name)}
              />
            ))}
            {loading && (
              <p role="status" className="px-4 py-3 text-[15px] text-muted-foreground">
                Loading projects…
              </p>
            )}
          </div>
        </div>
      </BottomSheetContent>
    </BottomSheet>
  );
}
