// Asks which project a new session belongs to, for the store's entry points: a picker on
// desktop, and on phones a bottom sheet with no search field, so the keyboard stays down.
// On a project's home it doesn't ask: the session starts in that project.

import { useCallback, useEffect, useState } from "react";
import { CircleSlashIcon } from "lucide-react";

import { type QuickPickItem, QuickPickDialog } from "@/components/ui/quick-pick";
import { type ProjectSummary, useProjects } from "@/hooks/useConversations";
import { useIsMobileViewport } from "@/hooks/useIsMobileViewport";
import { useLocation, useNavigate } from "@/lib/routing";
import { useProjectComposerStore } from "@/projectHome/ProjectHomeHeader";
import { projectNameFromHomePath } from "@/projectHome/projectHomeNavigation";
import {
  closeNewSessionProjectPrompt,
  useNewSessionProjectPromptStore,
} from "@/store/newSessionProjectPrompt";

import { NewSessionProjectSheet } from "./NewSessionProjectSheet";
import { ProjectRowIcon } from "./ProjectPicker";

const NO_PROJECTS: readonly ProjectSummary[] = [];
const NO_PROJECT_ROW_ID = "no-project";
const projectRowId = (projectName: string) => `project:${projectName}`;

/** Where a new session starts: the composer with `projectName`'s defaults, or the plain one. */
export function newSessionPath(projectName: string | null): string {
  return projectName === null ? "/" : `/?project=${encodeURIComponent(projectName)}`;
}

/** The project the user is already in: its home page, or the composer filed under it. */
export function projectInView(pathname: string, search: string): string | null {
  return projectNameFromHomePath(pathname) ?? new URLSearchParams(search).get("project");
}

export interface NewSessionProjectPromptProps {
  /** The command palette is open; it and the prompt replace each other rather than stacking. */
  paletteOpen: boolean;
  closePalette: () => void;
}

/** Mount once, inside the app shell. */
export function NewSessionProjectPrompt({
  paletteOpen,
  closePalette,
}: NewSessionProjectPromptProps) {
  const open = useNewSessionProjectPromptStore((state) => state.open);
  const isMobile = useIsMobileViewport();
  const navigate = useNavigate();
  const { pathname, search } = useLocation();
  const { data: projects, isError } = useProjects();
  const setProjectComposerOpen = useProjectComposerStore((state) => state.setOpen);

  useEffect(() => {
    useNewSessionProjectPromptStore.setState({ hosted: true });
    return () => useNewSessionProjectPromptStore.setState({ open: false, hosted: false });
  }, []);
  // Whichever of the two opened last stays.
  useEffect(() => {
    if (open) closePalette();
    // oxlint-disable-next-line react-hooks/exhaustive-deps -- only as the prompt opens.
  }, [open]);
  useEffect(() => {
    if (paletteOpen) closeNewSessionProjectPrompt();
  }, [paletteOpen]);

  const homeProject = projectNameFromHomePath(pathname);
  const start = useCallback(
    (projectName: string | null) => {
      closeNewSessionProjectPrompt();
      // On that project's home, as its New session button: the composer over the board.
      if (projectName !== null && projectName === homeProject && !isMobile) {
        setProjectComposerOpen(true);
      } else {
        navigate(newSessionPath(projectName));
      }
    },
    [homeProject, isMobile, navigate, setProjectComposerOpen],
  );

  // Nothing to ask on a project's home, which takes the session, or with no project to choose.
  const nothingToOffer = projects ? projects.length === 0 : isError;
  const startUnasked = homeProject !== null || nothingToOffer;
  useEffect(() => {
    if (open && startUnasked) start(homeProject);
  }, [open, startUnasked, homeProject, start]);

  const shown = open && !startUnasked;
  const prompt = {
    open: shown,
    onOpenChange: (next: boolean) => {
      if (!next) closeNewSessionProjectPrompt();
    },
    projects: projects ?? NO_PROJECTS,
    loading: projects === undefined,
    currentProject: projectInView(pathname, search),
    onStart: start,
  };
  return isMobile ? (
    <NewSessionProjectSheet {...prompt} />
  ) : (
    <NewSessionProjectPicker {...prompt} />
  );
}

export interface NewSessionProjectChoiceProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projects: readonly ProjectSummary[];
  /** The project list hasn't arrived; its rows are listed as it does. */
  loading: boolean;
  /** The project in view, which the prompt marks as the likely choice. */
  currentProject: string | null;
  /** Start the session in `projectName`, or in no project for null. */
  onStart: (projectName: string | null) => void;
}

function NewSessionProjectPicker({
  open,
  onOpenChange,
  projects,
  loading,
  currentProject,
  onStart,
}: NewSessionProjectChoiceProps) {
  const [query, setQuery] = useState("");
  // The project in view starts active, so Enter starts the session there.
  const [activeId, setActiveId] = useState<string | null>(null);
  useEffect(() => {
    if (!open) return;
    setQuery("");
    setActiveId(
      currentProject !== null && projects.some((project) => project.name === currentProject)
        ? projectRowId(currentProject)
        : null,
    );
    // oxlint-disable-next-line react-hooks/exhaustive-deps -- set once per opening.
  }, [open]);

  const items: QuickPickItem<string | null>[] = [
    {
      id: NO_PROJECT_ROW_ID,
      label: "No project",
      icon: <CircleSlashIcon aria-hidden className="size-4 text-muted-foreground" />,
      value: null,
    },
    ...projects.map((project) => ({
      id: projectRowId(project.name),
      label: project.name,
      icon: <ProjectRowIcon icon={project.icon} className="size-4 text-[16px]" />,
      detail: project.name === currentProject ? "Current project" : undefined,
      value: project.name,
    })),
  ];

  return (
    <QuickPickDialog<string | null>
      open={open}
      onOpenChange={onOpenChange}
      title="New session"
      description="Choose the project the new session belongs to, or No project."
      label="New session"
      placeholder="Start a new session in…"
      segments={[{ sourceId: "projects", ranking: "client", fuzzyMatching: "words", items }]}
      query={query}
      onQueryChange={(next) => {
        setActiveId(null);
        setQuery(next);
      }}
      activeId={activeId}
      onActiveIdChange={() => setActiveId(null)}
      // Once the picker has closed, so the composer it opens keeps the focus.
      onAccept={(item) => ({ afterClose: () => onStart(item.value) })}
      status={
        loading ? (
          <p role="status" className="px-3 py-2 text-xs text-muted-foreground">
            Loading projects…
          </p>
        ) : undefined
      }
      emptyMessage="No matching projects"
      inputTestId="new-session-project-input"
    />
  );
}
