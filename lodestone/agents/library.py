"""The agents Lodestone ships, and which of them the user has taken on.

Four agents used to be *the* agents: Inbox, Launch, Research, Personal, all
present, none of them chosen. That is a worse first run than it looks. Somebody
who has connected Gmail and nothing else still gets a go-to-market operator
sitting in their sidebar, and an agent nobody picked is an agent nobody has a
reason to open.

So this is a library and a roster. The library is what Lodestone offers; the
roster is what this person actually uses. A template is added and removed, and
the sidebar shows a team someone assembled rather than a default they ignored.

Two rules hold the set honest, and both come straight from `/CLAUDE.md`:

* **Never show a control that cannot work.** Every template names the sources it
  works with, and `needs` says which of them it genuinely cannot function
  without. The library reports that per template, so the UI can say "connect
  Gmail first" instead of offering an agent that will disappoint.
* **An agent is only told what it can do.** `actions` is per template, so a
  template with nothing to send with is never taught how to send — and so can
  never claim it did. See `prompt.py`.

Retiring the old four does not delete anything. Their conversations stay in
`agent_messages` and their model bindings stay in `agent_model_configs`,
untouched: losing somebody's chat history to a change in *our* default roster is
exactly the failure `/CLAUDE.md` forbids.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from ..log import suppressed
from .agent import Agent
from .mcp_tools import SENTINEL as MCP_TOOLS

#: Where the user's roster is stored.
ROSTER_KEY = "agent_roster"

#: The shelves in the library, in the order they are shown.
CATEGORIES = (
    "Run your day",
    "Work & career",
    "Creative studio",
    "Money & home",
    "Health & everyday life",
    "Your Mac",
)

#: What every agent gets: the brain, the web, each other, and a plan.
#: **Public, and shared with `custom.py`** — a custom agent is an agent, and two
#: different defaults for the same capability is exactly the accident that let a
#: user's own agent sit next to a connected Notion it could not read.
#: `forget_fact` and `run_python` are absent on purpose — see `presets`-era
#: notes in `brain_tools.py` and `code_tools.py`. Both are opt-in per agent.
BASE_TOOLS = [
    "search_brain", "who_is", "whats_true_about_me", "timeline",
    "why_do_you_think_that", "correct_fact", "remember", "list_entities",
    "web_search", "ask_agent", "ask_agents", "update_plan",
    "list_routines", "pause_routine", "list_pending_approvals", "list_scheduled",
    MCP_TOOLS,
]

#: Reading and writing files is safe to ship with any agent: it reaches nothing
#: until the user opens a folder, and that grant is the consent.
_FILES = ["list_dir", "read_file", "write_file"]

_TASKS = ["add_task", "list_tasks", "complete_task"]
_LOOPS = ["create_open_loop", "list_open_loops", "complete_open_loop"]
_MAIL = ["search_source", "sync_source", "gmail_search"]
_DIARY = ["calendar_lookup", "sync_source"]

_ALL_ACTIONS = ["send_email", "create_event", "set_reminder", "create_routine"]

#: Stands for "every tool there is" in a template's list.
#:
#: Written as a marker rather than as the list itself, because the list is the
#: thing that goes stale: a generalist enumerated by hand stops being a
#: generalist the first time somebody adds a tool and forgets one template.
#: Expanded when the agent is built, so a tool added tomorrow reaches it.
EVERYTHING = "*"


def expand_tools(names: list[str]) -> list[str]:
    """A template's tool list with `EVERYTHING` resolved.

    Imported inside the function: `tools.py` reaches back into this module
    through `presets` when it builds `ask_agent`'s description, and a
    module-level import here would close that loop at import time.
    """
    if EVERYTHING not in names:
        return list(names)
    from .tools import TOOL_DEFS

    every = [*TOOL_DEFS, MCP_TOOLS]
    # Anything named beside the marker is already covered; keep the order
    # stable so a stored list and a rebuilt one compare equal.
    return every + [n for n in names if n != EVERYTHING and n not in every]


@dataclass(frozen=True)
class Template:
    """One agent Lodestone offers, before anybody has taken it on."""

    id: str
    name: str
    role: str
    category: str
    #: One line, in the user's terms — what it does, not how.
    description: str
    system_prompt: str
    tools: list[str]
    actions: list[str] = field(default_factory=list)
    recall_sources: list[str] = field(default_factory=list)
    #: Sources this agent uses, for the "works with" line on its card.
    works_with: list[str] = field(default_factory=list)
    #: Sources it genuinely cannot function without. A subset of `works_with`.
    needs: list[str] = field(default_factory=list)
    #: May it reach the user's connectors without asking each time?
    #:
    #: A field rather than a hardcoded id, so the exception is visible in the
    #: library beside the agent that has it, and a second generalist would need
    #: no code change to behave the same way. See
    #: `docs/development/connector-permissions.md`.
    unrestricted_connectors: bool = False

    def resolved_tools(self) -> list[str]:
        """What this template actually grants, with `EVERYTHING` expanded."""
        return expand_tools(list(self.tools))

    def to_agent(self) -> Agent:
        return Agent(
            id=self.id, name=self.name, role=self.role,
            system_prompt=self.system_prompt, tools=self.resolved_tools(),
            recall_sources=list(self.recall_sources), actions=list(self.actions),
        )


TEMPLATES: tuple[Template, ...] = (
    Template(
        id="chief-of-staff",
        name="Chief of Staff",
        role="your day, end to end",
        category="Run your day",
        description="Runs your daily brief: what's on, what needs a reply, "
                    "what you promised and haven't done.",
        system_prompt=(
            "You run the user's day, and you are the generalist: you hold every "
            "tool this app has and reach every source they have connected. "
            "Whatever they ask for, the answer is yours to get.\n"
            "When they ask for a brief, give a short one: what is on the "
            "calendar, what in the inbox needs a response, which commitments "
            "are still open, and what you would do first. Lead with the answer, "
            "not the method. If they want that every morning, propose a standing "
            "automation for it rather than describing one — it will not happen "
            "on its own otherwise.\n"
            "When something needs doing, capture it as a task or an open loop "
            "rather than leaving it in prose. Compute with `run_python` rather "
            "than counting in your head — a number you estimated is a number you "
            "made up.\n"
            "You are the one agent with the whole picture, and you know who else "
            "is on the team. When a question belongs to a specialist, ask them "
            "with `ask_agent` — several at once with `ask_agents` — and answer "
            "the user yourself. You stay responsible for the reply."
        ),
        # Everything. A generalist enumerated by hand stops being one the first
        # time a tool is added and this line is not.
        tools=[EVERYTHING],
        # The one agent that does not stop to ask. Asking on every turn for the
        # agent whose whole job is "whatever you need" is a prompt nobody reads.
        unrestricted_connectors=True,
        actions=_ALL_ACTIONS,
        recall_sources=["gmail", "gcal"],
        works_with=["gmail", "gcal"],
    ),
    Template(
        id="inbox",
        name="Inbox",
        role="email & messages",
        category="Run your day",
        description="Triages your mail, drafts replies in your voice, and "
                    "surfaces what actually needs you.",
        system_prompt=(
            "You handle the user's email and messages. You triage what arrived, "
            "summarise threads, and surface what needs a response and what can "
            "wait.\n"
            "Draft replies in their voice, and learn that voice rather than "
            "inventing one: look up what they have written to THIS person "
            "before, and match how they actually talk to them. `who_is` on the "
            "sender tells you who they are to the user.\n"
            "Email is where commitments are made. When they promise something "
            "— or someone promises them — record it with `create_open_loop` so "
            "it does not live only in a thread nobody reopens. Check "
            "`list_open_loops` before saying nothing is outstanding.\n"
            "Count with `run_python`, never in your head: how many are unread, "
            "how many days until a deadline, which of these is oldest. A number "
            "you estimated is a number you made up.\n"
            "Draft; never claim to have sent."
        ),
        # Open loops matter more here than anywhere: email is where people
        # commit to things. run_python because triage is counting and dates.
        tools=[*BASE_TOOLS, *_FILES, *_MAIL, *_DIARY, *_TASKS, *_LOOPS,
               "run_python"],
        actions=_ALL_ACTIONS,
        recall_sources=["gmail", "gcal"],
        works_with=["gmail", "gcal"],
        needs=["gmail"],
    ),
    Template(
        id="research",
        name="Researcher",
        role="research & analysis",
        category="Work & career",
        description="Investigates a question properly, compares the options, "
                    "and cites where each answer came from.",
        system_prompt=(
            "You are the user's researcher. You investigate topics, compare "
            "options and synthesise findings, combining the public web with "
            "what they already know. Say where each claim came from. When the "
            "brain and the web disagree, say so rather than picking one. You "
            "report; you do not send, schedule or act on the world."
        ),
        # No actions, deliberately: a researcher with no way to send should not
        # be taught how, and then cannot claim it did.
        tools=[*BASE_TOOLS, *_FILES],
        works_with=[],
    ),
    Template(
        id="engineer",
        name="Engineer",
        role="code, issues & reviews",
        category="Work & career",
        description="Works in your repositories and issue tracker: "
                    "investigates, drafts changes, reviews what's open.",
        system_prompt=(
            "You work on the user's software. You investigate issues, read "
            "code in the folders they have opened to you, draft changes, and "
            "review what is in flight. Read a file before you change it, and "
            "say exactly what you wrote and where. Prefer running a small "
            "script over reasoning about what a program would print. When you "
            "are not sure a change is right, say which part you are unsure of."
        ),
        tools=[*BASE_TOOLS, *_FILES, "run_python", *_TASKS, *_LOOPS],
        recall_sources=["github", "linear"],
        works_with=["github", "linear", "files"],
    ),
    Template(
        id="writer",
        name="Writer",
        role="drafting & editing",
        category="Creative studio",
        description="Drafts and edits in your voice — announcements, posts, "
                    "long pieces — grounded in what you actually did.",
        system_prompt=(
            "You draft and edit for the user: announcements, posts, documents, "
            "long-form. Write in their voice, which you learn from what they "
            "have written before — look it up rather than inventing a register. "
            "Ground claims in their real projects. Offer one strong draft, not "
            "three weak options, and say what you would cut."
        ),
        tools=[*BASE_TOOLS, *_FILES, *_TASKS],
        actions=["set_reminder", "create_routine"],
        recall_sources=["notes", "gdrive", "notion"],
        works_with=["notes", "gdrive", "notion", "files"],
    ),
    Template(
        id="money",
        name="Money",
        role="spending & subscriptions",
        category="Money & home",
        description="Builds a current picture of what you spend — from your "
                    "own receipts and statements, not a guess.",
        system_prompt=(
            "You help the user see their money clearly. You find receipts, "
            "invoices and statements in what they have synced, pull the numbers "
            "out, and keep a current picture of what goes out and on what. "
            "Always compute with a script rather than in your head, and show "
            "the figures you used. Flag a subscription that renewed and was not "
            "used. Never guess an amount — say you could not find it."
        ),
        tools=[*BASE_TOOLS, *_FILES, "run_python", *_MAIL, *_TASKS, *_LOOPS],
        actions=["set_reminder", "create_routine"],
        recall_sources=["gmail", "files"],
        works_with=["gmail", "files"],
        needs=["gmail"],
    ),
    Template(
        id="health",
        name="Health & Fitness",
        role="training, food & recovery",
        category="Health & everyday life",
        description="Plans training, meals and recovery around your actual "
                    "week, and checks in on how it went.",
        system_prompt=(
            "You help the user train, eat and recover sustainably. Plan around "
            "the week they actually have — check the calendar before proposing "
            "a schedule. Use what the brain knows about their goals, their "
            "constraints and what they have tried. Be concrete: sets, portions, "
            "times. Review honestly rather than encouragingly, and adjust the "
            "plan when it is not being followed instead of repeating it. You "
            "are not a clinician; say so when a question needs one."
        ),
        tools=[*BASE_TOOLS, *_DIARY, *_TASKS, *_LOOPS],
        actions=["set_reminder", "create_event", "create_routine"],
        recall_sources=["gcal", "notes"],
        works_with=["gcal", "notes"],
    ),
    Template(
        id="personal",
        name="Personal",
        role="life admin",
        category="Health & everyday life",
        description="Keeps the small things from falling through: errands, "
                    "renewals, birthdays, the thing you said you'd book.",
        system_prompt=(
            "You are the user's personal assistant for everything that is not "
            "work. Errands, renewals, appointments, the people in their life. "
            "When they mention something to do, add it as a task; when they "
            "make a commitment to someone, record it as an open loop. Warm, "
            "discreet and brief — and proactive about what is coming up."
        ),
        tools=[*BASE_TOOLS, *_FILES, *_TASKS, *_LOOPS, *_DIARY],
        actions=_ALL_ACTIONS,
        recall_sources=["gcal", "imessage", "notes"],
        works_with=["gcal", "imessage", "notes"],
    ),
    Template(
        id="files",
        name="Files",
        role="what's on your Mac",
        category="Your Mac",
        description="Finds what's taking up room and what's gone stale in the "
                    "folders you open to it — and proposes, never deletes.",
        system_prompt=(
            "You help the user understand the folders they have opened to you: "
            "what is large, what is duplicated, what has not been touched in a "
            "year. Measure with a script rather than guessing from names. "
            "Report, group and PROPOSE — you never delete anything, and you say "
            "so plainly when asked to. If no folder has been opened yet, say "
            "that is the first step rather than describing what you would find."
        ),
        tools=[*BASE_TOOLS, *_FILES, "run_python", *_TASKS],
        works_with=["files"],
        needs=["files"],
    ),
)

BY_ID: dict[str, Template] = {t.id: t for t in TEMPLATES}

#: Empty on purpose. Nothing is pre-added.
#:
#: Four agents used to arrive with onboarding, and an agent nobody picked is an
#: agent nobody has a reason to open — a sidebar of strangers, three of which do
#: not match the work this person does. The Agent Library exists so a team is
#: assembled rather than issued, and shipping four anyway made the library look
#: like a page of spares.
#:
#: A new install is not empty: onboarding still builds the user their own lead
#: agent. So the first run is one agent that knows them, plus a library — which
#: is a starting point, not a blank screen.
DEFAULT_ROSTER: list[str] = []


def _store():
    from ..core.store import get_store
    return get_store()


def roster() -> list[str]:
    """The template ids this user has taken on."""
    raw = None
    with suppressed("reading the agent roster"):
        raw = _store().get_meta(ROSTER_KEY)
    if raw is None:
        return list(DEFAULT_ROSTER)
    try:
        saved = json.loads(raw)
    except (TypeError, ValueError):
        return list(DEFAULT_ROSTER)
    if not isinstance(saved, list):
        return list(DEFAULT_ROSTER)
    # An id that no longer exists is dropped rather than breaking the sidebar:
    # a roster written by an older version can name a retired template.
    return [str(i) for i in saved if str(i) in BY_ID]


def _save_roster(ids: list[str]) -> list[str]:
    _store().set_meta(ROSTER_KEY, json.dumps(ids))
    return ids


def add_to_roster(template_id: str) -> list[str]:
    if template_id not in BY_ID:
        raise KeyError(f"there is no agent template called '{template_id}'")
    current = roster()
    if template_id not in current:
        current.append(template_id)
        _save_roster(current)
    return current


def remove_from_roster(template_id: str) -> list[str]:
    """Take an agent out of the sidebar. Its conversation is kept.

    Removing is not deleting: the chat stays in `agent_messages`, so adding the
    agent back returns the user to where they left off rather than to an empty
    room.
    """
    current = roster()
    if template_id in current:
        current.remove(template_id)
        _save_roster(current)
    return current


def rostered_agents() -> list[Agent]:
    """The user's team, in the order they added them."""
    return [BY_ID[i].to_agent() for i in roster()]


def _source_ready(name: str) -> bool:
    if name == "files":
        from .file_tools import granted_roots
        return bool(granted_roots())
    try:
        from ..connectors import get_connector
        return bool(get_connector(name).is_configured()[0])
    except Exception:
        return False


def describe(include_status: bool = True) -> list[dict]:
    """The library, for the Agent Library screen.

    `missing` is what makes the difference between offering an agent and
    offering a disappointment: the card can say "connect Gmail first" rather
    than adding something that will not work.
    """
    have = set(roster())
    ready: dict[str, bool] = {}
    rows = []
    for t in TEMPLATES:
        missing: list[str] = []
        if include_status:
            for source in t.needs:
                if source not in ready:
                    ready[source] = _source_ready(source)
                if not ready[source]:
                    missing.append(source)
        rows.append({
            "id": t.id,
            "name": t.name,
            "role": t.role,
            "category": t.category,
            "description": t.description,
            "works_with": list(t.works_with),
            "needs": list(t.needs),
            "missing": missing,
            # Said on the card, before the user adds it: adding an agent IS the
            # consent for what it can do, so the consent has to be informed.
            # Against the RESOLVED list: a generalist holds its tools behind a
            # marker, and a card that read the marker would tell the user it
            # runs no code while handing it the interpreter.
            "runs_code": "run_python" in t.resolved_tools(),
            "touches_files": "read_file" in t.resolved_tools(),
            # Retracting something from the brain is a real power and the card
            # says so. It is a soft retraction that keeps provenance, so a
            # mistake is recoverable — but "recoverable" is not "unremarkable".
            "forgets_facts": "forget_fact" in t.resolved_tools(),
            "unrestricted_connectors": t.unrestricted_connectors,
            "in_roster": t.id in have,
        })
    return rows
