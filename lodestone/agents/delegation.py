"""One agent asking another.

The README calls this "four agents, one brain", and until now the second half
was true and the first was not: Inbox, Launch, Research and Personal shared a
database and never spoke. Four separate chats is not a team, and the user was
left doing the routing by hand — reading an answer in one tab and pasting it
into another.

Delegation is the whole feature and also the whole risk, because an agent that
can call an agent can call itself. Three guards, all enforced here rather than
trusted to a prompt:

* **Depth.** From the effort profile: none at Low, one hop at Medium, two at
  High. A sub-agent's budget is its parent's halved, so a chain cannot multiply
  a single question into dozens of model calls.
* **Cycles.** An agent already somewhere in the current chain cannot be asked
  again. Without this, Inbox → Research → Inbox is a loop that ends only when
  the budget runs out, having spent it learning nothing.
* **Context propagation.** The chain lives in a `ContextVar`, and tool calls run
  in a thread pool — which does *not* copy context by default. Missing that
  would silently reset the depth counter to zero inside every parallel call,
  turning both guards above into decoration.
"""
from __future__ import annotations

import contextvars
import threading
from dataclasses import dataclass

from ..log import get_logger
from .effort import Effort, get_effort

log = get_logger(__name__)


@dataclass(frozen=True)
class Chain:
    """Who is currently asking whom, on what budget, and until when."""

    agents: tuple[str, ...] = ()
    effort: Effort | None = None
    #: The parent turn's stop event, carried down the chain. Without it, Stop
    #: ends the agent the user is talking to and leaves the one it delegated to
    #: running — which is the same lie one level further in.
    cancel: threading.Event | None = None

    @property
    def depth(self) -> int:
        """Hops taken. The first agent is the user's, so it is depth 0."""
        return max(0, len(self.agents) - 1)


#: `None` rather than an empty `Chain`: a ContextVar default is created once at
#: import and shared by every context that never sets it, so a default must not
#: be something anyone could mutate. `Chain` is frozen today; the indirection
#: below means it stays safe even if that changes.
_CHAIN: contextvars.ContextVar[Chain | None] = contextvars.ContextVar(
    "lodestone_agent_chain", default=None)

_EMPTY = Chain()


def current_chain() -> Chain:
    return _CHAIN.get() or _EMPTY


def enter(agent_id: str, effort: Effort,
          cancel: threading.Event | None = None):
    """Record that `agent_id` is now running. Returns a token for `leave`."""
    chain = current_chain()
    return _CHAIN.set(Chain(agents=(*chain.agents, agent_id), effort=effort,
                            cancel=cancel if cancel is not None else chain.cancel))


def leave(token) -> None:
    _CHAIN.reset(token)


def refusal(agent_id: str) -> str | None:
    """Why this agent may not be asked right now, or None if it may.

    Returns prose rather than raising: the caller is a model, and a sentence it
    can act on ("you are already inside that agent") produces a better next move
    than an exception the loop has to translate.
    """
    from .presets import get_agent

    chain = current_chain()
    effort = chain.effort or get_effort()

    try:
        get_agent(agent_id)
    except KeyError:
        return (f"There is no agent called '{agent_id}'. "
                f"Available: {', '.join(available_agents())}.")

    if effort.max_delegation_depth <= 0:
        return ("Asking other agents is switched off at the current effort "
                "level. Answer using your own tools.")
    if chain.depth >= effort.max_delegation_depth:
        return (f"You have already passed this question through "
                f"{chain.depth + 1} agents, which is the limit. Answer with "
                "what you have.")
    if agent_id in chain.agents:
        return (f"'{agent_id}' is already working on this question further up "
                "the chain — asking it again would loop. Answer yourself.")
    return None


def available_agents(exclude: str | None = None) -> list[str]:
    from .presets import list_agents

    return [a.id for a in list_agents() if a.id != exclude]


def roster(exclude: str | None = None) -> str:
    """A one-line description of each agent, for the tool's description."""
    from .presets import list_agents

    return "; ".join(
        f"{a.id} ({a.role})" for a in list_agents() if a.id != exclude)
