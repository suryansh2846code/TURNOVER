"""Lodestone command line."""
from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(add_completion=False, help="Lodestone — local-first AI agent workspace.")
console = Console()


@app.command()
def serve():
    """Start the workspace server (open in a browser)."""
    from .api.app import run
    run()


@app.command("app")
def desktop_app():
    """Launch Lodestone as a native desktop window."""
    from .desktop import run_app
    run_app()


@app.command()
def mcp():
    """Run the MCP bridge (stdio) so terminal Claude / Cursor can use the brain."""
    from .mcp_server.server import main
    main()


@app.command("mcp-install")
def mcp_install():
    """Print the command to connect the Lodestone brain to Claude Code."""
    import sys
    from .config import get_settings
    py = sys.executable
    home = get_settings().home
    console.print("[bold]Connect Lodestone to your terminal Claude:[/]\n")
    console.print(
        f'  claude mcp add lodestone --env LODESTONE_HOME="{home}" '
        f'-- "{py}" -m lodestone.mcp_server.server\n'
    )
    console.print("Then in Claude Code these tools are available: search_brain, "
                  "about, remember, web_search, brain_stats, list_tasks, add_task, "
                  "complete_task — your terminal Claude now shares your brain.")


@app.command()
def chat(agent: str = typer.Argument("research"), message: str = typer.Argument(...),
         provider: str = typer.Option(None, help="override model provider")):
    """Send one message to an agent from the terminal."""
    from .agents import run_turn
    res = run_turn(agent, message, provider_name=provider)
    console.print(f"[dim]{res.provider}/{res.model}[/]")
    for s in res.trace:
        if s.kind == "tool_call":
            console.print(f"[cyan]→ {s.name}[/]({s.arguments})")
    console.rule(res.agent_id)
    console.print(res.reply)


@app.command()
def agents():
    """List the built-in agents."""
    from .agents import list_agents
    t = Table(title="Agents")
    t.add_column("id"); t.add_column("name"); t.add_column("focus"); t.add_column("tools")
    for a in list_agents():
        t.add_row(a.id, a.name, a.role, ", ".join(a.tools))
    console.print(t)


@app.command()
def sync(connector: str = typer.Argument(..., help="gmail|gcal|gdrive|notion|imessage|files"),
         path: str = typer.Option(None, help="folder path (files connector only)")):
    """Sync a connector. Runs interactive browser auth if needed (Gmail/Calendar/Drive)."""
    from .connectors import get_connector
    params = {"path": path} if path else {}
    console.print(f"[dim]syncing {connector}…[/]")
    res = get_connector(connector).sync(**params)
    if res.errors:
        console.print(f"[red]errors:[/] {res.errors}")
    console.print(f"[green]+{res.added}[/] added, {res.skipped} skipped — {res.detail}")


@app.command()
def ingest(path: str = typer.Option(None), text: str = typer.Option(None)):
    """Add data to the brain (a file/folder path or raw text)."""
    from .brain import get_brain
    from .connectors import get_connector
    if path:
        res = get_connector("files").sync(path=path)
        console.print(res.as_dict())
    elif text:
        console.print(get_brain().ingest(text, source="notes"))
    else:
        console.print("[yellow]pass --path or --text[/]")


@app.command()
def recall(query: str):
    """Show the context the brain would inject for a query."""
    from .brain import get_brain
    res = get_brain().recall(query)
    console.print(res["context"] or "[yellow]nothing relevant[/]")


@app.command()
def stats():
    """Show brain + graph stats."""
    from .brain import get_brain
    s = get_brain().stats()
    console.print_json(data=s)


@app.command()
def clean():
    """Prune junk entities/facts from the knowledge graph (quality filter)."""
    from .brain import get_brain
    out = get_brain().graph.prune_noise()
    console.print(f"removed [red]{out['removed_entities']}[/] noisy entities, "
                  f"[red]{out['removed_facts']}[/] facts")
    console.print_json(data=get_brain().stats()["graph"])


@app.command("rebuild-graph")
def rebuild_graph():
    """Rebuild the knowledge graph from prose memories with the current extractor."""
    from .brain import get_brain
    console.print(get_brain().rebuild_graph())


@app.command()
def reembed():
    """Re-embed the whole brain with the current embedder (after switching providers)."""
    from .brain import get_brain
    with console.status("re-embedding brain…"):
        out = get_brain().reembed()
    console.print(out)


@app.command()
def providers():
    """List model providers and readiness."""
    from .models import list_providers
    from .config import get_settings
    t = Table(title=f"Model providers (active: {get_settings().model_provider})")
    t.add_column("provider"); t.add_column("ready"); t.add_column("note")
    for p in list_providers():
        t.add_row(p["name"], "✓" if p["ready"] else "✗", p["reason"])
    console.print(t)


if __name__ == "__main__":
    app()
