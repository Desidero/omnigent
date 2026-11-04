"""Manifest: state, commands, the Goals page and the session-row and composer items."""

from omnigent.extensions import (
    EXTENSION_API_VERSION,
    CommandArgument,
    CommandContribution,
    ExtensionEntrypoints,
    ExtensionManifest,
    FieldBinding,
    FieldTone,
    FieldValue,
    PageContribution,
    SetState,
    SlotId,
    SlotItemContribution,
    SlotItemKind,
    StateContribution,
    StateField,
    StateVisibility,
)

EXTENSION_ID = "desidero.goal-loop"
PAGE_ID = f"{EXTENSION_ID}.goals"
# ``<owner>/<repo>/<number>``, as GitHub spells them.
PR_ID_PATTERN = r"[A-Za-z0-9_.-]{1,39}/[A-Za-z0-9_.-]{1,100}/[0-9]{1,9}"
_MODE = CommandArgument("mode", choices=("on", "off"))


def get_manifest() -> ExtensionManifest:
    """Return the goal loop's manifest; the page bundle is built from ``web/``."""
    return ExtensionManifest(
        id=EXTENSION_ID,
        display_name="Goal loop",
        distribution="desidero-goal-loop",
        version="0.1.0",
        requires_omnigent=">=0.11,<1",
        extension_api=EXTENSION_API_VERSION,
        entrypoints=ExtensionEntrypoints(
            browser="dist/extension.js",
            browser_css="dist/extension.css",
            server="desidero_goal_loop.server:activate",
        ),
        pages=(PageContribution(id=PAGE_ID, title="Goals", route="goals", view="goals"),),
        state=StateContribution(
            fields=(
                StateField("all", StateVisibility.EDITORS),
                StateField("pr:*", StateVisibility.EDITORS, max_keys=16),
                StateField("stop", StateVisibility.EDITORS),
                StateField("resume", StateVisibility.EDITORS),
                StateField("refresh", StateVisibility.EDITORS),
                StateField("goals", StateVisibility.READERS),
                StateField(
                    "goal",
                    StateVisibility.PUBLISHED,
                    max_length=16,
                    values=(
                        FieldValue("watching", "Watching", "eye", FieldTone.INFO),
                        FieldValue("unmet", "Needs work", "octagon-alert", FieldTone.DANGER),
                        FieldValue("met", "Met", "circle-check", FieldTone.SUCCESS),
                        FieldValue("stopped", "Stopped", "square-parking", FieldTone.NEUTRAL),
                        FieldValue("paused", "Paused", "circle-ellipsis", FieldTone.WARNING),
                    ),
                ),
                StateField("count", StateVisibility.PUBLISHED, max_length=4),
                StateField("summary", StateVisibility.PUBLISHED, max_length=32),
            )
        ),
        commands=(
            CommandContribution(
                id=f"{EXTENSION_ID}.all",
                title="All PRs in this session",
                action=SetState(key="all", value="{mode}"),
                arguments=(_MODE,),
            ),
            CommandContribution(
                id=f"{EXTENSION_ID}.pr",
                title="Keep this PR green",
                action=SetState(key="pr:{pr}", value="{mode}"),
                arguments=(CommandArgument("pr", pattern=PR_ID_PATTERN, max_length=120), _MODE),
            ),
            CommandContribution(
                id=f"{EXTENSION_ID}.stop",
                title="Stop all goals",
                action=SetState(key="stop", value="requested"),
                confirm="Stop every goal in this session?",
            ),
            CommandContribution(
                id=f"{EXTENSION_ID}.resume",
                title="Resume this PR's goal",
                action=SetState(key="resume", value="{pr}"),
                arguments=(CommandArgument("pr", pattern=PR_ID_PATTERN, max_length=120),),
            ),
            CommandContribution(
                id=f"{EXTENSION_ID}.refresh",
                title="Refresh goals",
                action=SetState(key="refresh", value="requested"),
            ),
        ),
        slot_items=(
            SlotItemContribution(
                id=f"{EXTENSION_ID}.composer",
                slot=SlotId.COMPOSER_ACTIONS,
                kind=SlotItemKind.ACTION,
                label="Goals",
                page=PAGE_ID,
                icon="list-checks",
                label_field="summary",
            ),
            SlotItemContribution(
                id=f"{EXTENSION_ID}.badge",
                slot=SlotId.SESSION_ROW_DECORATIONS,
                kind=SlotItemKind.DECORATION,
                label="Goal",
                binding=FieldBinding("goal"),
            ),
            SlotItemContribution(
                id=f"{EXTENSION_ID}.hover",
                slot=SlotId.SESSION_ROW_HOVER,
                kind=SlotItemKind.ROW,
                label="Goals",
                binding=FieldBinding("summary"),
            ),
            SlotItemContribution(
                id=f"{EXTENSION_ID}.stop-menu",
                slot=SlotId.SESSION_ROW_MENU,
                kind=SlotItemKind.COMMAND,
                label="Stop all goals",
                command=f"{EXTENSION_ID}.stop",
            ),
        ),
    )
