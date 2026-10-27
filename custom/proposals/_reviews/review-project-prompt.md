# Pre-PR review: palette project rows + new-session project prompt

Reviewed 2026-10-21 against `upstream/main` = `eced2859d`. Report only; no branch was modified.

- `feat/palette-new-chat-in-project` = `6cc98f0bd` (1 commit, +84/-1, 2 files)
- `feat/new-chat-project-prompt` = `1401d53cc` (stacked, +369/-33, 13 files)
- Both are based on `b9e80e9d3`, **31 commits behind** `upstream/main`. Only `89638a742` (grid fix) touched one of our files (`Sidebar.tsx`); `git merge-tree` is clean for both branches. Rebase before opening.
- Checks run in the prompt worktree (`~/repos/omnigent-wt/feat/new-chat-project-prompt/web`, env stripped of `OMNIGENT_*`/`RUNNER_SERVER_URL`): `vitest run` on the 5 changed test files → 433/433 pass (40s); `tsc -b` → exit 0; `prettier --check` and `oxlint --deny-warnings` on the changed sources → clean.
- Side effect of this review: a trial `cherry-pick --no-commit` of the prompt commit onto `upstream/main` (in a throwaway worktree, since removed) recorded rerere **preimages** for `CommandPalette.tsx`/`.test.tsx` in the main checkout's `.git/rr-cache`. No resolution was recorded, so nothing will be replayed; harmless.

Line numbers below are from the prompt worktree unless marked `[palette-wt]`.

---

# Branch 1: `feat/palette-new-chat-in-project`

## Verdict

**Ready to open after a rebase and two small additions** (feature-map line, keyboard test). Small, self-contained, matches #4409's "surface each project directly as `New session in <project>`" option, and does exactly what pandalaohe's closing comment on #6627 asked for ("a much smaller PR against the current code"). #6627 had no reviewer comments or reviews to carry over. Merges clean on current `upstream/main`.

## Must fix

None.

## Should fix

1. **`web/src/shell/CommandPalette.tsx:196-206 [palette-wt]` — typing "project" finds nothing.** The group is headed "New chat in project", but the match text is `new chat in <name>`, so a user who types `project` (the obvious discovery query, and the word the issue uses) sees no rows unless a project name contains it. Suggest matching against `new chat in project <name>` (or add `project` as an implicit keyword) so the heading's own words reach the rows. Add a test (`"project"` → every project listed).
2. **No keyboard test.** The palette is keyboard-first (that is the point of #4409), but all four new tests click. `CommandPalette.test.tsx:89` and `:192` already show the pattern (`fireEvent.keyDown(input, { key: "Enter" })`). Add: type `omni`, press Enter → `navigate("/?project=omnigent")`, `onOpenChange(false)`.
3. **`feature-map/composer.md` has no entry for this.** The map is "the maintained source for verifying user-facing behavior" and already lists `new-command` (`/new`) and `new-session-hotkey`. Add a one-line sub-feature (e.g. `palette-new-chat-in-project`: typing in ⌘K lists "New chat in <project>" rows that open the composer with the project's defaults; hidden while the query is empty) plus a line under "How to get to it". The prompt commit adds its own entry but this commit ships first.
4. **Commit message / PR text promises "stored defaults" for every row.** Legacy label-only projects (`ProjectSummary.id === null`, `useConversations.ts:2115-2127`) have no config; `/?project=<name>` then opens a plain composer that only files the session under the label (`NewChatDialog.tsx:2165-2177`). Same as the pencil, so the behaviour is right, but say so in the PR so a reviewer testing with a legacy project doesn't report a bug.

## Nits

- `CommandPalette.tsx:442-455 [palette-wt]`: `key={project.name}` and `value={`project:${project.name}`}` are fine (the server unions by name, `routes_core.py:1437-1446`), but a short comment that names are unique would save the reviewer the lookup.
- `CommandPalette.tsx:279-282 [palette-wt]`: `encodeURIComponent` yields `home%20lab` while the sidebar pencil yields the same via a template (`Sidebar.tsx:1623`); the composer's `searchParams.get` decodes both. OK, just noting the test's `/?project=home%20lab` literal is tied to this choice.
- Wording: the palette says "New chat", the sidebar "New session", #4409 "New session in <project>". Keeping the existing palette label is defensible; mention it in the PR so nobody asks for a rename mid-review.
- Header comment (lines 14-16) is 3 lines and scenario-focused; fine per CLAUDE.md. No issue numbers in code. Good.

## Tests

`CommandPalette.test.tsx:348-391 [palette-wt]`, 4 tests:
- hides rows while query empty — covered
- every-word matching (`new omni`) + icon rendered — covered
- click → `/?project=home%20lab` + close — covered
- `sessionsOnly` omits rows — covered
Not covered: keyboard Enter; `projects` undefined/loading (the `= []` default handles it, trivially); a project with `icon: null` renders the folder fallback (asserted only indirectly). The mock of `useProjects` in the test file (lines 13-17) is new and reasonable.

## Upstream drift

- #10995 (Sidebar.tsx @1552), #10778 (Sidebar.tsx, many hunks in `ProjectFolder`/`ConversationList`), #10992 (NewChatDialog/ProjectSettingsDialog), #10720 (ChatHeader), #10858 (hostPreferences/NewChatDialog): **none touch `CommandPalette.tsx`**. No overlap with this branch.
- **#9686** (dennyglee, "clear all notifications via shortcut + command palette", updated 10-10) touches `CommandPalette.tsx` @20, @53 (props), @108, @147-187 (actions array) and `AppShell.tsx` @2789. This branch touches @30-49 (imports), @189-206, @260-282, @418-455. Imports and the `actions` region are adjacent; expect a small textual conflict for whichever merges second. Low risk.
- #5724 / #5728 (fanzeyi, Sept 14 refactors of the palette and shell shortcuts) are stale but open; if revived they rewrite the actions list and `useNewSessionHotkey`. Not worth waiting for.
- #11007 and #6319 (btli) touch `CommandPalette.test.tsx` (not the component). Test-file conflicts only.

---

# Branch 2: `feat/new-chat-project-prompt`

## Verdict

**Hold; do not open yet.** The code is sound (tests, tsc, lint pass; one shared `handleNewSession` drives hotkey, sidebar and palette; `/?project=` prefill is real), but:

1. It flips the default flow for every user who has projects, and the issue you filed (#11083, 04:15 today) explicitly says "can open it once there's agreement on the default". Wait for a maintainer reply. Also answer the duplicate-check bot on #11083 (it asked whether #4409 already covers it) so the issue doesn't get auto-closed as a dupe.
2. It is genuinely stacked: the commit does **not** apply to `upstream/main` without the palette commit (conflicts in `CommandPalette.tsx` and its test). So the palette PR has to merge first anyway.
3. A few correctness edges and coverage gaps below are worth fixing while waiting.

## Must fix

1. **`web/src/shell/CommandPalette.tsx:225-228` + `:395-412` — stale session-load error leaks into the picker.** The conversations query is disabled on the project step (`enabled: open && !projectStep`), but `isError` still reflects the cached state of the empty-query key. If the last ⌘K fetch failed, the picker renders "Couldn't load sessions. Retry" above the project rows and suppresses `CommandEmpty`. Gate the status row and `loadError` on `!projectStep` (and probably reset `isError` by not reading it at all in that mode).
2. **Keyboard path untested.** The headline UX claims ("Enter on No project immediately gives a plain composer"; "type part of a name and press Enter") are never exercised; every new test clicks. cmdk's first-item auto-select is what makes Enter work, and a reorder of `CommandGroup`s or a non-empty Sessions group (see #1) would silently break it. Add to `CommandPalette.test.tsx` "project step": (a) Enter with empty query → `navigate("/")`; (b) type `lab`, Enter → `/?project=home%20lab`.
3. **Settings switch has no test.** `SettingsPage.test.tsx:357-368` already tests the neighbouring `background-session-titles-toggle` (default checked; click → localStorage `"off"`). Copy those two tests for `new-chat-project-prompt-toggle`. Without it the only coverage of the setting is the pure read/write test.

## Should fix

1. **`web/src/hooks/useNewChatProjectPrompt.ts:66-70` — projects still loading means "skip the prompt", silently.** `data` is `undefined` until `/v1/sessions/projects` returns, so `hasProjects` is false and the hotkey/sidebar/palette open the plain composer. On a cold load (deep link to `/c/<id>`, then immediately ⌘⇧O or a tap on New session) the user gets the old behaviour once and the new one afterwards. The same happens if the projects fetch errored. The sidebar also subscribes (`Sidebar.tsx:1806`) and `staleTime` is 30s, so it is rare, but it is a behaviour the PR should state explicitly ("while projects are loading or failed to load, no prompt"). Alternative: use `isPending` to open the picker with its own loading state. Add a test for `data: undefined`.
2. **Escape does not restore focus (pre-existing palette behaviour, now much more visible).** The palette is a Radix modal `Dialog` with no `DialogTrigger`; Radix's modal content calls `event.preventDefault()` in `onCloseAutoFocus` and focuses the trigger ref, which is null, so focus lands on `<body>`. Before, ⌘⇧O went straight to the composer; now Escape from the picker leaves the user with no focus. Fix in `CommandPalette.tsx` by capturing `document.activeElement` when `open` flips true and passing `onCloseAutoFocus={(e) => { e.preventDefault(); previous?.focus(); }}` to `DialogContent`. Verify manually (jsdom will not tell you) — I could not confirm the installed Radix build's exact code path; treat as "check on a real browser".
3. **Mobile drawer → picker is only reasoned about, not tested.** `Sidebar.tsx:805-817`: `onNavClick` closes the drawer (`onClose` → `setSidebarOpen(false)`, AppShell 1714-1717), then `onNewSessionClick` prevents the Link and calls `onNewSession`. The drawer is CSS + `inert` (not a Radix dialog), so there is no focus-trap fight with the palette sheet; by reading it works. But `Sidebar.test.tsx:1842-1856` only asserts `onNewSession` is called, and the AppShell tests run at desktop width. Add an AppShell test at mobile viewport (there are existing mobile-viewport helpers in `AppShell.test.tsx`) asserting the scrim is hidden and the "Start a new session in…" input is present after a tap, or at minimum do it on a phone and include the screenshot.
4. **`web/src/shell/Sidebar.tsx:1198-1202` — `switchTab("mine")` runs before the user has chosen.** Cancelling the picker with Escape leaves the Sessions tab switched to "Mine" with no session created. Move the tab switch into the non-prompt path (or call it from `handleNewSession` only on selection). Same for `onActiveTabChange("mine")` at 2593-2598.
5. **`web/src/shell/AppShell.tsx:1732-1742` + `CommandPalette.tsx:304-307` — "New chat" from the palette remounts the dialog.** `runAction` closes (`onOpenChange(false)`), then `handleNewSession` sets `projectStep=true` and `open=true` in the same batch; the `key` flips `commands` → `project`, so Radix unmounts and remounts the dialog: no close animation, open animation replays, `query` resets. Functionally fine (test at `CommandPalette.test.tsx:384-391` covers the call), but check it does not flash on desktop. If it does, have `handleNewSession` switch mode without closing when the palette is already open.
6. **`web/src/shell/CommandPalette.tsx:360-368` — mobile close button is labelled "Close search" in the picker.** Use `paletteLabel`-aware text ("Close") or "Cancel" on the project step.
7. **Preference storage.** `web/src/lib/newChatProjectPromptPreferences.ts` is a byte-for-byte copy of the `backgroundSessionTitlesPreferences.ts` pattern: per-browser `localStorage`, key `omnigent:new-chat-project-prompt`, absent = on, `"off"` = off, try/catch around storage. That **is** the General-settings convention today (every other General toggle does the same; `SettingsPage.tsx:1640-1781` all use `componentId="settings.general.*"` Switches), so it is consistent. Note for the PR: the just-merged #10826 (`feat(preferences): persist shared edits…`) adds a server-side shared-preferences foundation but, per `feature-map/preferences.md:5-8` and the "Shared scopes" paragraph, there is no UI entry yet, so a maintainer might ask whether this toggle should become a shared preference later. Mention it as a follow-up and keep localStorage now.
8. **Name the behaviour for archived/legacy projects in the PR.** `routes_core.py:1413-1455`: first-class projects are always listed (even empty); legacy label-projects only while one owned session still carries the label. So "my only project is a legacy label and all its sessions are archived" → `projects=[]` → no prompt (same as the sidebar, which also hides it). There is no "hidden project" concept in the web code (grep found none). Fine, but state it.

## Nits

- `web/src/hooks/useNewSessionHotkey.ts:23-26` + `AppShell.tsx:1758`: `useNewSessionHotkey(true, undefined, handleNewSession)` — a positional `undefined` to reach the third parameter. Either make `onNewSession` the second parameter with `isMac` last, or take an options object.
- `web/src/hooks/useNewChatProjectPrompt.ts`: file is `useNewChatProjectPrompt.ts` but exports `useShouldPromptForProject`; rename one to match (repo convention is file = hook name).
- `AppShell.tsx:1744-1757`: the ⌘K callbacks read `sessionSearch`/`projectStep` from render scope (pre-existing pattern for `sessionSearch`); the `prev =>` updater and the closure variable can disagree for one render. Not new, just now two variables wide.
- `CommandPalette.tsx:293-302`: nested ternaries for `paletteLabel`/`placeholder`; a tiny `mode` discriminant (`"project" | "sessions" | "commands"`) would read better and already exists as the `key` expression in AppShell 2833.
- `SettingsPage.tsx:1739`: description says "New session and its shortcut" but the palette's New chat also prompts; say "every New session entry point".
- `feature-map/composer.md:72-75`: good; matches neighbours (sub-feature key, 3-4 lines, user POV, no selectors). `:156-161`: the "How to get to it" line says "press the hotkey or click New session (also from the mobile drawer)" but not the palette's New chat; add it since it is the third entry point. Also it says "Turn off … in Settings" without the group name; neighbours name the path (`Settings › General › Sessions` is used in the sub-feature line, keep it consistent).
- Commit message says "Modified clicks on the links still open the composer in a new tab" — `Sidebar.test.tsx:1849` asserts `fireEvent.click(link, { metaKey: true })` returns `true` (default not prevented), which is the right assertion; middle-click (`button: 1`) is not simulated but `e.button !== 0` is guarded at `Sidebar.tsx:813`. Fine.
- No issue numbers in code comments; comments are 1-3 lines. Good.

## Tests

What the new tests assert (all pass):
- `useNewSessionHotkey.test.tsx:137-146`: hotkey calls `onNewSession`, not `navigate`. Covered.
- `newChatProjectPromptPreferences.test.ts`: default on; off persists `"off"`; on clears the key. Covered.
- `AppShell.test.tsx:5651-5697`: with one project, ⌘⇧O opens the picker and does not render the composer; clicking "No project" renders the composer. With the preference off, no picker. Covered (hotkey path only).
- `CommandPalette.test.tsx:384-391`: "New chat" action → `onNewSession`, closes, no navigate. Covered.
- `CommandPalette.test.tsx:402-440`: project step lists `["No project","🔥omnigent","home lab"]` in order and disables the sessions query; filter by `lab`; click each row → `/` and `/?project=home%20lab`. Covered.
- `Sidebar.test.tsx:1842-1856`: for both links, meta-click is not intercepted, plain click is prevented and calls `onNewSession`. Covered.

Not covered (user-visible claims from the issue/commit): Enter on first row; Escape; focus restore; mobile drawer closes before the sheet opens; projects loading/undefined and fetch error; Settings switch in the page; `/?project=` actually prefilling (relies on existing `NewChatDialog` coverage, which is fine to cite); ⌘K pressed while on the project step switching to commands; `/`, `/new`, logo, post-archive redirect and `openNewSession` not prompting (true by construction, `ChatPage.tsx:1105-1117` and `:2907` call `navigate`/`onNewSession` directly, but one assertion that `/new` does not open the picker would lock it in).

Reported "803 tests / 30 files" was not reproduced here; the 5 changed files give 433. Likely the full `src/shell` glob — fine either way.

## Upstream drift

Open PRs vs this branch's files (`CommandPalette.tsx`, `Sidebar.tsx`, `AppShell.tsx`, `SettingsPage.tsx`, `useNewSessionHotkey.ts`, `composer.md`):
- **#10995** (amitdahan, 10-21): `Sidebar.tsx` @1552 only (`ProjectFolder`). Ours: @466, @674, @801, @1184, @1348, @1669, @1713, @2574. No overlap; clean.
- **#10778** (hzub, 10-19): `Sidebar.tsx` @1417-1567 (`ProjectFolder`), @1793-1957 and @2214-2284, @2763-2824 (`ConversationList`), @5759+ (menus), plus `useConversations.ts`, `Sidebar.test.tsx`. Our `ConversationListProps`/destructure hunks (@1669, @1713) sit just above their @1793; 3-way merge should be clean, line drift only. `Sidebar.test.tsx` both add tests → trivial conflict possible.
- **#10992** (bot): `NewChatDialog.tsx`, `ProjectSettingsDialog*`. No overlap.
- **#10720** (dosenr): `ChatHeader.tsx`. No overlap.
- **#10858** (dbczumar): `hostPreferences.ts`, `NewChatDialog*`. No overlap. (Note it changes which host a new session defaults to; `/?project=` prefill with `hostId` from project config still wins per `NewChatDialog.tsx:2179-2195`; re-check after it merges.)
- **#9686** (dennyglee): `CommandPalette.tsx` props + actions, `AppShell.tsx` @2789 (palette props). **Likely conflicts** with our `onNewSession` prop and `run:` change and the `<CommandPalette …>` props block (@2804-2840). Medium.
- **#11007 / #6319** (btli, 10-20/21): `SettingsPage.tsx` @44-100 imports, @224, @917-1111 (Appearance); `AppShell.tsx` @116-128, @356, @908, @2402, @2893; `Sidebar.tsx` @1023-1126, @1388, many more; `CommandPalette.test.tsx`. Our `SettingsPage.tsx` import hunk (@210) is adjacent to their @224; our `AppShell.tsx` palette props (@2804-2840) is adjacent to their @2893; our `Sidebar.tsx` @1184 is adjacent to their @1095-1126. Expect line-drift and one or two import-block conflicts. Medium.
- **#257115ae8** (merged today, session rename hotkey) adds `useRenameSessionHotkey` next to ours; no file overlap.
- **#10826** (merged today, shared preferences): no web files touched; see Should fix 7.
- Branch base is 31 commits behind; `git merge-tree --write-tree upstream/main feat/new-chat-project-prompt` is clean. Rebase anyway so CI runs on head.

---

# Splitting recommendation

- The palette commit is independent (84 lines, 2 files, merges clean). The prompt commit **is not**: cherry-picking it onto `upstream/main` alone conflicts in `CommandPalette.tsx` (it rewrites `filteredProjects` into `matchesEveryWord` and extends the `newChatInProject` helper) and in the test file. So the order is forced: palette PR first.
- **First PR = the palette commit only**, titled for #4409 ("Closes #4409"), plus: the "project" keyword match (Should fix 1), an Enter test, and a feature-map line. In the PR body, note #6627 was closed by its author asking for exactly this smaller change, and that legacy label-only projects open a plain composer filed under the label (same as the pencil). Release notes: Yes (user-facing palette feature), one changelog line.
- **Second PR after a maintainer responds on #11083.** The issue already lists the alternatives (opt-in, prompt-on-`/`, remember-last) and the chosen default; if they ask for opt-in, the change is a one-line flip in `readNewChatProjectPromptEnabled` plus the Settings copy, so there is no cost to waiting. Open it stacked on the first PR's branch only if GitHub stacked PRs are acceptable there; otherwise wait for the first to merge and rebase.
- Do not fold the prompt into the #4409 PR: #4409 is palette-only, and the prompt changes the default flow for sidebar/hotkey users who never asked for it; a reviewer skimming "closes #4409" would not expect that.

# Screenshot plan

PR 1 (palette), desktop 1280×800, light and dark not required but one dark is nice:
1. ⌘K with empty query: Sessions + Actions only, no project rows (proves "hidden until typed").
2. Query `new omni`: "New chat in project" group with the 🔥 omnigent row and the "New chat" action above it; highlighted row via keyboard (arrow down) to show it is selectable.
3. Query `home`: a project with no emoji (folder fallback icon) to show the icon fallback.
4. After Enter: the composer at `/?project=omnigent` with the host/workspace/agent chips prefilled and the sidebar pencil highlighted for that project (proves the defaults applied).
5. Optional: ⌘⇧K sessions-only switcher with query `omni` showing no project rows.
Short GIF (5-8s): ⌘K → type → Enter → composer prefilled.

PR 2 (prompt):
1. Desktop: press ⌘⇧O from an open session → "Start a new session in…" picker with "No project" first (highlighted) and the projects below with icons.
2. Same picker after typing `lab`: filtered to one row, "No project" gone.
3. After Enter on a project: composer at `/?project=…` prefilled (same framing as PR 1 #4).
4. Sidebar: hover on "New session" and on the Sessions "+" to show both entry points; a second shot of a ⌘-click having opened a plain composer in a new tab (tab strip visible).
5. Phone width (390×844): drawer open with "New session" visible → next frame the drawer closed and the full-screen picker sheet with the keyboard up and the X button (proves drawer→sheet handoff and keyboard-aware height).
6. Settings › General › Sessions card showing the new "Ask for a project when starting a session" switch under "Background session titles", on and off.
7. With the switch off: ⌘⇧O lands directly on the composer (one shot, caption).
8. Edge, optional but persuasive: a user with zero projects pressing ⌘⇧O → straight to composer (shows no change for project-less users).
Short GIF: hotkey → type → Enter → prefilled composer; second GIF on phone: tap New session → sheet → pick → composer.
