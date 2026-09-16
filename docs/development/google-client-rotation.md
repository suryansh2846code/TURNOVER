# Rotating the bundled Google OAuth client

> **What this is:** the procedure for replacing the Google OAuth client that
> ships inside the app, and what users experience when it happens.
>
> **Why it exists:** the client is committed (`DECISIONS.md` → H12) so that a
> stranger who installs the `.dmg` can press *Sign in with Google* and have it
> work. That decision is right, and it has one consequence nobody had written
> down: **the day we have to replace that client, every user has to re-consent,
> and the procedure has to work first time.** A rotation rehearsed for the first
> time during an outage is not a procedure.

---

## 1. When you would do this

Three situations, in rising order of how bad the day is:

* **A secret scanner revokes it.** GitHub's push protection and Google's own
  scanning both recognise an installed-app client. Revocation is unilateral and
  the first symptom is every Google sync failing at once.
* **The Cloud project gets rate-limited or suspended for abuse.** Anyone can
  stand up their own consent screen branded "Lodestone" using the committed
  `client_id`. Abuse attributed to the project lands on *our* quota, and it
  takes Gmail, Calendar and Drive down for **every** user simultaneously, with
  no fix shippable from our side except a new client.
* **The repository goes public.** At that point treat the id as burned on
  principle rather than waiting for evidence, and plan per-user clients as the
  longer-term escape hatch.

None of these is hypothetical enough to leave undocumented, and the first one
can happen on a Tuesday for no reason.

## 2. Why rotation does not need a new build

`config.py::google_client_secrets` already resolves the client in precedence
order, and **this is the property the whole procedure rests on**:

| # | source | who uses it |
|---|---|---|
| 1 | `$GOOGLE_CLIENT_SECRETS` (if the path exists) | CI, and you, while verifying |
| 2 | `~/Library/Lodestone/google_client_secret.json` | a user we can reach before the next release |
| 3 | `lodestone/data/google_client.json`, bundled | everyone else, on first launch |

So a replacement client can be **proven against a real Google account before it
is committed**, and an affected user can be unblocked by dropping one file —
no release, no terminal.

`tests/test_google_client_rotation.py` pins this order. If that test goes red,
this document is fiction and the rotation cannot be performed.

## 3. The procedure

**Do steps 1–3 before touching the repository.** The point of the precedence
chain is that the new client is verified while the old one is still bundled.

1. **Create the replacement.** Google Cloud Console → *APIs & Services* →
   *Credentials* → *Create credentials* → *OAuth client ID* → **Desktop app**.
   Download the JSON. It must have an `installed` top-level key — a *Web*
   client has `web` instead and will fail at `InstalledAppFlow`, which is the
   single most likely way to get this wrong.

2. **Check the consent screen before you need it.** The scopes requested by
   `google_auth.SCOPES` must all be listed on the OAuth consent screen, and the
   app must be in **Production**, not *Testing*. A Testing-mode app expires
   every refresh token after seven days — `get_credentials` self-heals from that
   by re-consenting, so it looks like "Google keeps signing me out" rather than
   like a misconfiguration.

3. **Verify it against a real account, without committing anything:**

   ```bash
   export GOOGLE_CLIENT_SECRETS=~/Downloads/client_secret_NEW.json
   rm -f ~/Library/Lodestone/google_token.json    # force a fresh consent
   ./.venv/bin/python -c "
   from lodestone.connectors.google_auth import get_credentials, granted_services
   get_credentials(interactive=True); print(granted_services())"
   ```

   Expect a browser consent screen and then `['Gmail', 'Drive', 'Calendar']`.
   Anything less means a scope is missing from the consent screen, not from us.

4. **Commit the replacement** over `lodestone/data/google_client.json`, in a
   commit that does nothing else. The commit message is a user-facing sentence
   like any other — *"fix(connectors): Google sign-in works again after the
   client was replaced"*.

5. **Revoke the old client** in the Console — but only *after* the release is
   out, because until then the shipped build is still using it.

6. **Tell users what to expect**, in the release note: *"You'll be asked to sign
   in to Google once more. Nothing else changes."* That sentence is the whole
   user-facing cost, and it is worth spending a line on so it does not read as a
   malfunction.

## 4. What an existing user actually experiences

Their `google_token.json` was issued by the **old** client, so:

* Their current access token keeps working until it expires — **up to an hour
  during which calls 401 rather than self-heal.** This is the confusing window;
  it is short and it ends on its own.
* The first refresh after that fails `invalid_client`, which arrives as a
  `RefreshError`. `get_credentials` deletes the token and falls through to
  consent, so an interactive reconnect just works.
* The **background scheduler** calls with `interactive=False`, which cannot open
  a consent screen. It raises the "Google sign-in expired or missing. Open
  Lodestone and reconnect Google" message, and that lands in the connector row's
  error in the Connectors panel. That is the intended path — a background thread
  must never pop a browser window at someone.

**One known wrinkle:** the self-heal deletes `google_token.json` but leaves
`google_account.json`, which caches the signed-in address. A user who re-consents
with a *different* Google account will briefly see the old address in the UI
until something refreshes it. Cosmetic, recorded here rather than fixed, because
the fix belongs with whoever next touches `connected_email()`.

## 5. If you are here because it is already broken

Fastest unblock for one user, no release:

```bash
# they drop the new client where their app will find it
cp client_secret_NEW.json ~/Library/Lodestone/google_client_secret.json
rm -f ~/Library/Lodestone/google_token.json
```

Then reconnect Google from Connectors. This is the fallback path, and per
`CLAUDE.md` it is the fallback and never the plan — the plan is §3.
