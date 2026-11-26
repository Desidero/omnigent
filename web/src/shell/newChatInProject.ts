// ⌘K's "New chat in <project>" rows, one per project, as both palettes list them. They show
// only once the user types, so a long project list doesn't push Actions out of view.

import { type ProjectSummary, useProjects } from "@/hooks/useConversations";

export const NEW_CHAT_IN_PROJECT_HEADING = "New chat in project";

const NO_PROJECTS: readonly ProjectSummary[] = [];

/** Where a new session filed under `projectName` starts: the composer with its defaults. */
export function newChatInProjectPath(projectName: string): string {
  return `/?project=${encodeURIComponent(projectName)}`;
}

export function newChatInProjectLabel(projectName: string): string {
  return `New chat in ${projectName}`;
}

/** The palette's row id for a project, unique among its rows. */
export function newChatInProjectRowId(projectName: string): string {
  return `project:${projectName}`;
}

/** The projects to offer rows for: none until the user types, or while `listed` is false. */
export function useNewChatInProjectChoices(
  listed: boolean,
  query: string,
): readonly ProjectSummary[] {
  const { data: projects = NO_PROJECTS } = useProjects({ enabled: listed });
  return listed && query.trim() !== "" ? projects : NO_PROJECTS;
}

/**
 * The projects whose row holds every typed word in its label or group heading, so
 * "new omni", "omni" and "project" all reach "New chat in omnigent".
 */
export function matchNewChatInProject(
  projects: readonly ProjectSummary[],
  query: string,
): readonly ProjectSummary[] {
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return NO_PROJECTS;
  return projects.filter((project) => {
    const text = `${NEW_CHAT_IN_PROJECT_HEADING} ${project.name}`.toLowerCase();
    return words.every((word) => text.includes(word));
  });
}
