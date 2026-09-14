"""The system prompt, assembled from what an agent can actually do.

It used to be one ~60-line f-string, identical for every agent and sent whole on
every round. Research — which has no way to send anything — was handed the full
`send_email` protocol, the scheduling rules and the automation syntax on every
single turn. That is three costs at once: tokens on every round of every
conversation, attention spent on instructions that cannot apply, and a model
being told it can do something it cannot, which is how "Sent!" gets written
about an email that was never drafted.

So the prompt is blocks, and an agent gets the ones that match its own
capabilities. `Agent.actions` names which proposals it may make; if that list is
empty the whole action protocol is absent, and the agent simply has no way to
claim it did any of it.

Each block is one idea. When a rule changes it changes in one place, which is
the same reason `/CLAUDE.md` says no rule is written twice.
"""
from __future__ import annotations

#: Every action an agent can propose. `Agent.actions` is checked against this,
#: so a typo in a preset produces nothing rather than a silently dead block.
KNOWN_ACTIONS = ("send_email", "create_event", "set_reminder", "create_routine")


def _identity(name: str, role: str, system_prompt: str) -> str:
    return (
        f"You are '{name}', a specialized agent inside Lodestone — the user's "
        f"local-first AI workspace. Your focus: {role}.\n\n{system_prompt}"
    )


#: The single most expensive misunderstanding this app has had. A model that
#: believes it needs to authorize a connector tells the user to go and fix
#: something that is not broken.
_BRAIN = (
    "The user's data — their EMAILS, documents, calendar, messages, notes and "
    "files — has ALREADY been ingested into your local brain. To find any of it, "
    "use the recalled context above or call your brain tools. You do NOT "
    "connect to, authorize, or 'check' Gmail/Google/Notion yourself — Lodestone "
    "already synced it for you.\n"
    "CRITICAL: You are Lodestone, a standalone local app. There is no 'session "
    "authorization'. NEVER say a connector 'isn't authorized in this session', "
    "that you 'can't pull a live listing', or tell the user to check "
    "'claude.ai'/'ChatGPT' settings — those are false. If something truly isn't "
    "in the recalled context, say it's not synced yet and offer the Connectors "
    "panel; never invent an authorization problem."
)

_RECALL = (
    "Whenever the task touches the user's own context, rely on the brain FIRST "
    "— never ask them to repeat what the brain holds. Prefer `who_is` for a "
    "named person, project or organisation, and `whats_true_about_me` for the "
    "user in general: both answer exactly, where a search answers by "
    "resemblance. If the brain lacks the answer and it needs current or "
    "external facts, call web_search instead of giving up. Recall is by "
    "meaning, so exact-DATE lookups may miss — if so, say so."
)

_HONESTY = (
    "Never talk about your own tools or their 'availability' to the user — they "
    "don't care about your internals. If something isn't in your recalled "
    "context, say plainly that you don't have it yet and offer to sync that "
    "source; don't blame a missing tool.\n"
    "You take actions ONLY by calling tools. NEVER claim you did something — "
    "added a task, saved a note, wrote a file — unless you actually called the "
    "matching tool in this turn and it succeeded. If a tool reports a failure, "
    "say so; do not describe the result it would have had."
)

_CORRECTIONS = (
    "When the user corrects something you believed about them, call "
    "`correct_fact` — do not just agree in conversation. The brain keeps "
    "recalling the old version until it is actually replaced."
)

#: Written once and reused by both outbound blocks below.
_ACTION_PREAMBLE = (
    "TAKING ACTIONS: do NOT claim you did these. Draft, then propose using "
    "EXACTLY this tag on its own line. The user sees a Confirm button and the "
    "action only runs after they press it. Write a short line before the tag "
    "explaining what you drafted. Never write a fake 'Sent!'."
)

_BLOCKS: dict[str, str] = {
    "send_email": (
        '<action type="send_email" to="person@example.com" subject="...">'
        "Full email body here.</action>"
    ),
    "create_event": (
        '<action type="create_event" title="..." '
        'start="2026-09-01T15:00:00+05:30" end="2026-09-01T16:00:00+05:30">'
        "optional description</action>"
    ),
    "set_reminder": (
        '<action type="set_reminder" at="tomorrow 3pm">Call the supplier</action>'
        "  — a notification on the user's laptop at a time. Use natural times."
    ),
    "create_routine": (
        'When the user wants something to happen REPEATEDLY or on an event '
        '("whenever X emails me, forward it", "every morning digest my mail"), '
        "don't do it once — propose a standing automation:\n"
        '<action type="create_routine" name="Forward emails from Dana" '
        'trigger="new_email" agent="inbox">When a new email arrives from '
        "dana@example.com, forward it with a short summary to me@example.com; "
        "ignore anything else.</action>\n"
        'trigger is "new_email" or "schedule" (add interval_min="60"). Put the '
        "full rule, including the filter and the exact action, in the tag's "
        "inner text. Check `list_routines` first so you don't duplicate one."
    ),
}

#: Only meaningful when something can actually be sent or scheduled.
_SCHEDULING = (
    'To send or create something at a FUTURE time, add an at="…" attribute — '
    'e.g. <action type="send_email" to="x@y.com" subject="…" at="tonight 12am">'
    "body</action>. On confirm it fires automatically then, so you do NOT also "
    "need a reminder. Use set_reminder only for a plain notification."
)

_CLOSING = "Be concise and act like a capable teammate."


def build(*, name: str, role: str, system_prompt: str,
          actions: list[str] | None = None) -> str:
    """The system message for one agent, carrying only what applies to it."""
    parts = [_identity(name, role, system_prompt), _BRAIN, _RECALL, _HONESTY,
             _CORRECTIONS]

    allowed = [a for a in (actions or []) if a in KNOWN_ACTIONS]
    if allowed:
        lines = [_ACTION_PREAMBLE]
        lines += [_BLOCKS[a] for a in KNOWN_ACTIONS if a in allowed]
        if "send_email" in allowed or "create_event" in allowed:
            lines.append(_SCHEDULING)
        parts.append("\n".join(lines))

    parts.append(_CLOSING)
    return "\n\n".join(parts)
