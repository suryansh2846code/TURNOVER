/**
 * "What just happened" — the app's own record, where a stuck user can read it.
 *
 * The app keeps every failure it survives rather than swallowing it, and wrote
 * that evidence to a file a shipped `.app` user cannot open. So "it just doesn't
 * work" stayed unfalsifiable in exactly the cases the logging was built for: a
 * connector macOS blocked, a vendor CLI that would not install, a sync that
 * failed overnight. `/CLAUDE.md` forbids sending anyone to a terminal, and
 * "open Console.app and find our file" is that instruction in a hat.
 *
 * **Read-only by construction.** There is no input, no command, nothing that
 * runs. The value here is being able to *see* and *send* what happened; adding
 * a way to act would be a different feature with a completely different
 * security story.
 *
 * Lines are written with `textContent`, never `innerHTML`. A log line can carry
 * an email subject, which is to say text a stranger wrote, and a `<pre>` needs
 * no markup at all — so the safe path is also the simpler one.
 */

//: Newest-last, matching the file, because a sequence of events only reads in
//: the order it happened. The box is scrolled to the bottom instead.
async function loadDiagnosticsLog() {
  const box = $("#logBox"), meta = $("#logMeta");
  if (!box) return;
  let body;
  try {
    body = await api("/api/diagnostics/log?lines=200");
  } catch (e) {
    if (meta) meta.textContent = "Could not read the log.";
    box.textContent = "";
    return;
  }

  if (!body.ok) {
    // An empty box reads as "nothing went wrong", which is a different answer.
    box.textContent = "";
    if (meta) meta.textContent = body.detail || "Nothing recorded yet.";
    return;
  }

  const lines = body.lines || [];
  box.textContent = lines.join("\n");
  // Scrolled to the newest line, because that is what "what just happened"
  // means and nobody wants to drag a scrollbar to find out.
  box.scrollTop = box.scrollHeight;

  if (meta) {
    const size = body.bytes ? ` · ${Math.round(body.bytes / 1024)} KB on disk` : "";
    meta.textContent = lines.length
      ? `Last ${lines.length} lines${body.truncated ? " (older ones not shown)" : ""}${size}`
      : "Nothing recorded yet.";
  }
}

{
  const refresh = $("#logRefresh");
  if (refresh) refresh.onclick = () => loadDiagnosticsLog();

  const copy = $("#logCopy");
  if (copy) copy.onclick = async () => {
    const box = $("#logBox");
    const text = (box && box.textContent) || "";
    if (!text) { toast("Nothing to copy yet"); return; }
    // The point of this panel: getting what happened into a bug report without
    // anyone having to find a file. Keys are already stripped server-side.
    toast(await copyToClipboard(text) ? "Copied — paste it into your report"
                                      : "Could not copy");
  };
}
