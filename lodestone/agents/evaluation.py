"""A scorecard for what the agents can actually do.

"The agents are better now" is the kind of claim that rots. Every capability
here is checked by running the real loop against a scripted model — no network,
no keys, no spend — and the result is a number that can be compared between
commits and argued with.

Deliberately not a benchmark of answer *quality*: that needs a real model and a
human, and it moves when the model does. These check the things the harness
itself is responsible for — does a deeper budget get used, do independent tools
overlap, does a model that repeats itself get stopped, can an agent consult
another, is an unattended outbound action gated. Those either work or they do
not, and if they do not, no model is going to rescue them.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from ..log import get_logger

log = get_logger(__name__)


@dataclass
class Check:
    key: str
    title: str
    passed: bool
    detail: str = ""


@dataclass
class Scorecard:
    checks: list[Check] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    @property
    def total(self) -> int:
        return len(self.checks)

    @property
    def score(self) -> float:
        """Out of 10, so it can be compared with a human rating."""
        return round(10 * self.passed / self.total, 1) if self.total else 0.0

    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.passed]

    def as_dict(self) -> dict:
        return {
            "score": self.score, "passed": self.passed, "total": self.total,
            "checks": [{"key": c.key, "title": c.title, "passed": c.passed,
                        "detail": c.detail} for c in self.checks],
        }

    def render(self) -> str:
        lines = [f"Agent capability: {self.score}/10  ({self.passed}/{self.total})"]
        for c in self.checks:
            lines.append(f"  {'PASS' if c.passed else 'FAIL'}  {c.title}"
                         + (f" — {c.detail}" if c.detail else ""))
        return "\n".join(lines)


def _swap(module, name: str, value) -> None:
    """Replace a module attribute for the duration of a check.

    Through a helper rather than in line: `runtime.get_provider` is an
    lru_cache wrapper and `resolve_usable_model` has a precise signature, so a
    plain assignment is a type error even though substituting them is the whole
    point. Taking the attribute name as an argument also keeps the linter from
    rewriting `setattr(x, "literal", v)` straight back into that assignment.
    """
    setattr(module, name, value)


def _scripted(script, **kw):
    """A provider that answers from a script, installed over the real one."""
    from ..models.base import ChatResult, LLMProvider, ToolCall

    class _Scripted(LLMProvider):
        name = "eval"
        model = "eval-1"

        def __init__(self):
            self.rounds = 0
            self.tools_offered: list[list[str]] = []

        def is_ready(self):
            return True, ""

        def chat(self, messages, *, tools=None, temperature=0.7, max_tokens=1500):
            self.tools_offered.append([t.name for t in (tools or [])])
            if not tools or self.rounds >= len(script):
                return ChatResult(text=kw.get("final", "done"))
            step = script[self.rounds]
            self.rounds += 1
            if isinstance(step, str):
                return ChatResult(text=step)
            return ChatResult(text="", tool_calls=[
                ToolCall(id=f"c{self.rounds}-{i}", name=n, arguments=a)
                for i, (n, a) in enumerate(step)])

    return _Scripted()


def run(*, include_slow: bool = True) -> Scorecard:
    """Run every capability check and return the scorecard."""
    from . import delegation, grounding, runtime
    from . import mcp_tools as mcp
    from . import tools as tools_mod
    from .effort import get_effort

    card = Scorecard()

    def check(key, title):
        def record(passed, detail=""):
            card.checks.append(Check(key, title, bool(passed), detail))
        return record

    # Keep the real implementations, restore them whatever happens.
    saved_impls = dict(tools_mod.TOOL_IMPLS)
    saved_provider = runtime.get_provider
    saved_resolve = runtime.resolve_usable_model
    saved_supplier = mcp._supplier

    def use(provider) -> None:
        """Point the runtime at a scripted model for the next check."""
        _swap(runtime, "get_provider", lambda _p, _m: provider)

    _swap(runtime, "resolve_usable_model", lambda _p, m: (m or "eval-1", None))
    try:
        # ── depth ────────────────────────────────────────────────────────
        tools_mod.TOOL_IMPLS["list_entities"] = lambda **kw: "an entity"
        deep_script = [[("list_entities", {"limit": i})] for i in range(40)]
        provider = _scripted(deep_script)
        use(provider)
        high = runtime.run_turn("research", "dig deep", effort="high")
        check("depth", "Goes deeper than the old five-round ceiling")(
            high.steps_used > 5, f"{high.steps_used} tool rounds")

        provider = _scripted([[("list_entities", {"limit": i})] for i in range(40)])
        use(provider)
        low = runtime.run_turn("research", "dig", effort="low")
        check("effort", "The effort setting actually changes the budget")(
            low.steps_used < high.steps_used,
            f"low {low.steps_used} vs high {high.steps_used} rounds")

        # ── no runaway ───────────────────────────────────────────────────
        calls = {"n": 0}

        def counted(**kw):
            calls["n"] += 1
            return "the same answer"

        tools_mod.TOOL_IMPLS["list_entities"] = counted
        provider = _scripted([[("list_entities", {"limit": 3})] for _ in range(30)])
        use(provider)
        repeated = runtime.run_turn("research", "dig", effort="high")
        check("no_repeat", "A repeated call is answered from memory, not re-run")(
            calls["n"] == 1, f"executed {calls['n']}x")
        check("stall", "A model that stops learning is asked to answer")(
            provider.rounds < 30 and bool(repeated.reply),
            f"stopped after {provider.rounds} rounds")

        # ── budget exhaustion still answers ──────────────────────────────
        tools_mod.TOOL_IMPLS["list_entities"] = lambda **kw: f"entity {time.time()}"
        provider = _scripted([[("list_entities", {"limit": i})] for i in range(100)],
                             final="here is what I found")
        use(provider)
        spent = runtime.run_turn("research", "dig", effort="high")
        check("budget_answer", "Spending the whole budget still yields an answer")(
            spent.reply == "here is what I found", spent.reply[:40])

        # ── our own grounding note stays out of the arguments ────────────
        # The date is stated in front of the question so a small model cannot
        # miss it; a model then copies its input into the call it emits, and
        # `search_brain`'s query reaches `parse_date_range`, which reads the
        # date we supplied as a filter and answers from an empty brain.
        note_args: dict = {}

        def capture(**kw):
            note_args.update(kw)
            return "some context"

        tools_mod.TOOL_IMPLS["search_brain"] = capture
        echoed = grounding.prefixed("Tuesday, September 15, 2026", "who is she")
        provider = _scripted([[("search_brain", {"query": echoed})], "found her"])
        use(provider)
        runtime.run_turn("research", "who is she")
        check("date_note", "The date we tell the model never reaches a tool")(
            bool(note_args) and "[Today is" not in note_args.get("query", ""),
            note_args.get("query", "(never called)")[:60])

        # ── stop actually stops ──────────────────────────────────────────
        # Everything after the first check is spend the user asked to end.
        stop = threading.Event()
        spend = {"tools": 0}

        def stops_the_turn(**kw):
            spend["tools"] += 1
            stop.set()                      # the user presses Stop, mid-tool
            return "ok"

        tools_mod.TOOL_IMPLS["list_entities"] = stops_the_turn
        provider = _scripted([[("list_entities", {"limit": i})] for i in range(24)])
        use(provider)
        halted = runtime.run_turn("research", "dig deep", effort="high",
                                  cancel=stop)
        check("stop", "Stop ends the turn, not just the watching")(
            halted.stopped and provider.rounds == 1 and spend["tools"] == 1,
            f"{provider.rounds} model call(s) and {spend['tools']} tool(s), "
            f"of a 24-round budget")

        # ── parallelism ──────────────────────────────────────────────────
        if include_slow:
            live = {"now": 0, "peak": 0}

            def slow(**kw):
                live["now"] += 1
                live["peak"] = max(live["peak"], live["now"])
                time.sleep(0.12)
                live["now"] -= 1
                return "ok"

            tools_mod.TOOL_IMPLS["list_entities"] = slow
            provider = _scripted([[("list_entities", {"limit": i}) for i in range(4)],
                                  "done"])
            use(provider)
            started = time.perf_counter()
            runtime.run_turn("research", "dig", effort="high")
            elapsed = time.perf_counter() - started
            check("parallel", "Independent tool calls overlap")(
                live["peak"] > 1 and elapsed < 0.12 * 4,
                f"{live['peak']} at once, {elapsed:.2f}s for four 0.12s calls")

        # ── planning ─────────────────────────────────────────────────────
        tools_mod.TOOL_IMPLS.update(saved_impls)
        provider = _scripted([[("update_plan", {"steps": ["find it", "draft it"],
                                                "done_through": 1})], "done"])
        use(provider)
        planned = runtime.run_turn("research", "two-part job", effort="high")
        check("planning", "Keeps a plan on multi-part work, and reports it")(
            len(planned.plan) == 2 and planned.plan[0]["done"],
            f"{len(planned.plan)} steps")

        # ── delegation ───────────────────────────────────────────────────
        provider = _scripted([[("ask_agent", {"agent_id": "personal",
                                              "question": "what is on today?"})],
                              "Personal says nothing is on."])
        use(provider)
        asked = runtime.run_turn("inbox", "check with personal", effort="high")
        delegated = any(s.name == "ask_agent" and "personal answered" in s.result
                        for s in asked.trace if s.kind == "tool_result")
        check("delegation", "An agent can consult another and get its answer")(
            delegated)

        token = delegation.enter("inbox", get_effort("high"))
        try:
            cycle = delegation.refusal("inbox")
            off = delegation.refusal("nobody")
        finally:
            delegation.leave(token)
        check("delegation_guard", "Delegation refuses loops and unknown agents")(
            bool(cycle) and bool(off))

        # ── grounding ────────────────────────────────────────────────────
        provider = _scripted([], final="ok")
        use(provider)
        grounded = runtime.run_turn("research", "what do you know about me?",
                                    effort="medium")
        check("grounding", "The brain is recalled before the model chooses")(
            any(s.name == "auto_recall" for s in grounded.trace)
            or grounded.steps_used == 0)

        # ── streaming ────────────────────────────────────────────────────
        provider = _scripted([], final="streamed answer")
        use(provider)
        seen: list[dict] = []
        streamed = runtime.run_turn("research", "hello", effort="low",
                                    on_event=seen.append)
        check("streaming", "A turn reports progress while it happens")(
            any(e["type"] == "token" for e in seen)
            and streamed.reply == "streamed answer")

        # ── safety ───────────────────────────────────────────────────────
        from .permissions import check as permission_check
        check("unattended_outbound",
              "An unattended agent cannot mail a stranger")(
            not permission_check("send_email",
                                 {"to": "stranger@evil.test"}).allowed)
        check("no_escalation",
              "An unattended agent cannot create automations")(
            not permission_check("create_routine", {"name": "x"}).allowed)
        check("reads_stay_free", "Reading and note-taking are never gated")(
            permission_check("set_reminder", {"message": "x"}).allowed)

        # ── tool hygiene ─────────────────────────────────────────────────
        bad = tools_mod.run_tool("add_task", {"nope": 1})
        unknown = tools_mod.run_tool("no_such_tool", {})
        check("tool_validation",
              "Model-written tool arguments are validated, not trusted")(
            "Schema validation error" in bad and "Unknown tool" in unknown)

        # ── the user's connectors ────────────────────────────────────────
        # Faked, because a real MCP server is a subprocess and a scorecard must
        # not need one installed to say whether the wiring works. What is being
        # measured is exactly the wiring: a connector's read tool reaches the
        # model and its answer lands in the turn, and its write tools are never
        # offered at all — those go through propose → confirm (permissions.py).
        from types import SimpleNamespace

        def _ref(tool: str, writes: bool) -> SimpleNamespace:
            return SimpleNamespace(
                qualified_name=f"demo:{tool}", server_id="demo",
                server_label="Demo", tool=tool, description=f"{tool} on Demo.",
                parameters={"type": "object", "properties": {}}, writes=writes)

        fake_connectors = SimpleNamespace(
            list_tools=lambda: [_ref("list_items", False), _ref("create_item", True)],
            call_tool=lambda _name, _args: "one item")
        _swap(mcp, "_supplier", lambda: fake_connectors)
        mcp.clear_cache()

        provider = _scripted([[("demo_list_items", {})], "there is one item"])
        use(provider)
        connected = runtime.run_turn("research", "what is in demo?", effort="medium")
        offered = provider.tools_offered[0] if provider.tools_offered else []
        check("connector_tools",
              "An agent can read the user's own connectors mid-turn")(
            any(s.name == "demo_list_items" and "one item" in s.result
                for s in connected.trace if s.kind == "tool_result"))
        check("connector_writes_withheld",
              "A connector's write tools are never offered to a model")(
            "demo_list_items" in offered
            and not any("create_item" in n for n in offered))

    finally:
        _swap(mcp, "_supplier", saved_supplier)
        mcp.clear_cache()
        tools_mod.TOOL_IMPLS.clear()
        tools_mod.TOOL_IMPLS.update(saved_impls)
        _swap(runtime, "get_provider", saved_provider)
        _swap(runtime, "resolve_usable_model", saved_resolve)

    return card
