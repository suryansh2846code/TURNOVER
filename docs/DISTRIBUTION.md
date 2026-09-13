# Shipping Lodestone as a `.dmg`

> How a Mac you have never touched ends up running this app, and what each step
> exists to prevent. Written after building it: the numbers below are measured
> on an Apple Silicon Mac, not estimated.

## Are we going in the right direction?

Partly. `scripts/build-macos-app.sh` was the right instinct at the wrong
altitude. It writes a real `Lodestone.app` with a real `Info.plist` — but its
launcher is three lines that `cd` into the source checkout and run
`.venv/bin/lodestone app`. There is no Python inside that bundle. Copy it to
another Mac and it fails immediately, because the thing it points at does not
exist there.

That script is still useful, and it has been relabelled rather than replaced:
it is the fastest way to get an icon in `~/Applications` while developing.

The distributable path is `scripts/build-dmg.sh`, which is four steps. Each one
is load-bearing, and skipping any of them produces something that looks finished
and is not.

```
  1. Bundle    PyInstaller → interpreter + deps + web assets inside the .app
  2. Sign      Developer ID Application + Hardened Runtime + entitlements
  3. Notarise  upload to Apple, get a ticket back
  4. Staple    attach the ticket so first launch works offline
```

## Why each step

**1. Bundle.** The user has no Python, no `uv`, and no checkout. PyInstaller
puts a CPython and every dependency in `Lodestone.app/Contents/Frameworks`, and
`lodestone/web` in `Contents/Resources` where `api/assets.py::WEB` finds it.

The interesting decision is what to leave out. `sentence-transformers` pulls
torch, and the environment used to build this one has it installed: **1.1 GB of
venv for a feature that is off by default**, since the default embedder is the
pure-Python `hash` one. The spec excludes it, and the difference is the whole
download:

| | size |
|---|---|
| `Lodestone.app` (torch excluded) | **189 MB** |
| `Lodestone-0.1.0.dmg` (compressed) | **74 MB** |
| the same bundle with torch | ~2 GB |

A user who wants local embeddings installs the extra into a source checkout.
That is the right trade for a download page.

**2. Sign.** Notarisation refuses anything not built with the Hardened Runtime,
and the Hardened Runtime kills CPython on launch unless three exceptions are
granted. They are in `packaging/entitlements.plist` with the reason for each;
the short version is that CPython maps writable-executable memory, and the
bundle loads `.so` files that were not signed by us.

Signing is **inside-out**: every nested `.dylib` and `.so` first, then the
bundle. One pass over the `.app` leaves the nested binaries unsigned and Apple
rejects the entire upload for any one of them.

**3. Notarise.** Without a ticket, Gatekeeper tells the user the app *"cannot be
opened because Apple cannot check it for malicious software"*, and the only way
through is right-click → Open. For this product that is not a minor rough edge —
it is precisely the instruction `CLAUDE.md` says never to give:

> **Never ask the user to open a terminal.** … If a path cannot succeed, say
> why, in the place the user is looking.

An app whose very first interaction is a scary dialog and a workaround has
already failed the standard the rest of the codebase is held to. **Notarisation
is not optional for a shipped Lodestone.**

**4. Staple.** The ticket is fetchable online, so an unstapled build usually
works — until someone installs it on a plane. Stapling attaches it to the `.dmg`.

## What you need

| | |
|---|---|
| Apple Developer Program | **$99/yr** — there is no free path to notarisation |
| A *Developer ID Application* certificate | in the login keychain |
| A notarytool profile | `xcrun notarytool store-credentials lodestone-notary --apple-id you@example.com --team-id TEAMID --password <app-specific-password>` |

An **app-specific password** is generated at appleid.apple.com, not your Apple
ID password.

## Running it

```bash
uv pip install pyinstaller
./scripts/build-dmg.sh              # signed + notarised + stapled
./scripts/build-dmg.sh --unsigned   # a real .dmg, but Gatekeeper will warn
```

The script preflights everything it needs and tells you exactly which command
fixes what is missing, rather than failing halfway through a five-minute build.

### The smoke test is part of the build

After bundling and before signing, the script launches the bundled binary, waits
for it to write `~/Library/Lodestone/.port`, and requests `/api/sync/status`.
A PyInstaller bundle that is missing a hidden import looks perfectly well-formed
and dies on launch; this catches that in fifteen seconds instead of in a user's
Downloads folder. It is the same reason the frontend has executed harnesses
rather than `node --check`.

## macOS permissions this app actually needs

These are the ones that will surprise you, because nothing in the build catches
them — they only appear on someone else's Mac.

**Full Disk Access** — `connectors/imessage.py` reads
`~/Library/Messages/chat.db` and `connectors/apple_mail.py` reads
`~/Library/Mail`. macOS protects both. A signed, notarised app still gets
`PermissionError` until the user grants Full Disk Access in
System Settings → Privacy & Security. This cannot be requested by a prompt; the
user has to do it by hand.

Which means it has to be *handled*, per the product rule: those two connectors
should detect the refusal and say "macOS is blocking access to your Messages —
open System Settings → Privacy & Security → Full Disk Access and add Lodestone",
with a button that opens that pane
(`x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles`).
**This is not built yet** and is the largest gap between "the `.dmg` builds" and
"the `.dmg` works for a stranger".

**Automation / Apple Events** — anything driving Notes or Calendar through
AppleScript triggers a consent prompt, which needs
`NSAppleEventsUsageDescription` in `Info.plist`. It is set in the spec; the
string it contains is the entire explanation the user gets, so it says what
Lodestone does with the data and that it stays on the machine.

## Known gaps

* **Architecture.** This builds for the machine it runs on — arm64 here. Intel
  Macs need a separate build, or a universal2 Python to build a fat binary from.
  Decide whether Intel is supported before publishing a download link.
* **Updates.** A `.dmg` has no update mechanism. Every new version is a fresh
  download unless something like Sparkle is added. Worth deciding early: the
  in-app "check for updates" affordance is much easier to add before there are
  users on old versions.
* **The bundled Google OAuth client.** `lodestone/data/google_client.json`
  ships inside the `.app`. That is a deliberate decision recorded in
  `.gitignore` (an installed-app client, which Google treats as
  non-confidential — the security is PKCE plus the loopback redirect). Shipping
  it in a public download is a larger audience than shipping it in a repo, so
  re-confirm that decision before publishing, and know how to rotate it.
* **Icon.** `packaging/icon.icns` is not present, so the bundle gets the generic
  application icon. Add one before anyone sees this.

## What was verified, and what was not

Built and run on this machine: the bundle, the smoke test, and the unsigned
`.dmg` — 189 MB app, 74 MB image, the app launches, serves its API and answers
`/api/sync/status`.

**Not verified: signing, notarisation and stapling.** No Developer ID
certificate exists on this machine (`security find-identity -v -p codesigning`
→ *0 valid identities found*), so steps 2-4 have never been executed. They are
written from Apple's documented process and the script preflights for them, but
the first person to run it with a real certificate should expect to debug it.
