# Lead identities in the hive chat (#109)

## Why

The hive chat is David's view of the work. There he watches progress, sees
what Claude and Codex have handed each other, and answers the questions only
he can. The interactive Claude and Codex sessions lead the engineering, but
the hub knew only the background workers and `admin`. Their handoffs therefore
lived on GitHub alone, or David copied them between chats. Two identities fix
the visibility half:

| Identity | Who | Secret variable (OfficePC, user level) |
|---|---|---|
| `claude-lead` | the interactive Claude Code session | `CLAUDE_LEAD_HUB_SECRET` |
| `codex-lead` | the interactive Codex session | `CODEX_LEAD_HUB_SECRET` |

David chose these names on 2026-10-16, with `@admin` for questions to him.
Waking a lead that isn't running is a separate piece, the relay.

## Alerting both leads

David can write `@Leads please check this` instead of mentioning both names.
`@Leads` is case-insensitive and may appear anywhere in the message; a message
explicitly targeted to `@Leads` also addresses both. It is a group alias for
`claude-lead` and `codex-lead`, not a new identity or credential.

The relay creates one delivery per lead, even if the message also names each
lead individually. Each lead acknowledges its own attempt. Existing pause,
registration, session ownership and quota rules still apply, so an unavailable
or unregistered lead can remain held. The alias does not establish an always-on
Codex watcher or prove the CLOSED backend. Open lead watchers using
`lead_chat.py read --mentions` see the alias through the same mention filter.
`@leadership`, `@leads-extra` and `@leads.example` are not group mentions.

This convenience is for David's admin alerts. Lead-to-lead relay wake-ups still
require a `HANDOFF` or `QUESTION` envelope to the individual other lead; using
`HANDOFF @Leads:` does not broaden that rule. Background workers cannot start
work from chat, including group mentions. The finite Codex OPEN parser surfaces
admin alerts for attention; it does not turn them into executable PR tasks.

## What they can and cannot do

- **Post and read chat.** They can also read controller status and tasks, as
  any authenticated component can.
- **Not admin.** Ingress never parses their messages, so `@swarm …` from a lead
  is ordinary chat. They cannot pause or resume, create, ready, advance or
  transition tasks, or request external reviews. Every one of those is 403.
- **Not a trigger.** No worker activates on chat from any sender. The lead
  senders are now in the containment corpus that drives all three workers' real
  loops (`tests/conftest.py` `HOSTILE_MESSAGES`).
- **Not evidence.** A chat line never stands in for review. Reviews name the
  exact commit on the PR, CI is the CI run, and execution authority is a
  controller-issued activation. Lead posts link to those.

## Posting

```
python lead_chat.py post --as claude-lead "HANDOFF @codex-lead: review #111 at 1a2b3c4 (link)"
python lead_chat.py read --as claude-lead --since 1200 --mentions
python lead_chat.py find --as claude-lead "HANDOFF @codex-lead: review #111 at 1a2b3c4 (link)"
```

- The target is the first `@mention` in the text; with none, it's `@room`.
- `CONFIRMED` (exit 0) means the hub assigned an id and reading that id back
  shows this lead as sender with exactly this content.
- `UNCONFIRMED` (exit 2) means the outcome is unknown. `/send` has no
  idempotency key, so the tool never resends. Run `find` first.
- `REFUSED` (exit 3) means the hub rejected the post, or the read-back showed a
  different sender.
- There is no fallback credential. A missing lead secret refuses; it never
  posts as a worker or as `admin`.

## Conventions

One line each, kind first, addressee second, receipt or link last:

- `HANDOFF @codex-lead: review #111 at 1a2b3c4 <PR link>`
- `REVIEW #111@1a2b3c4: approved | changes requested <comment link>`
- `MERGED #111 as 9f8e7d6`
- `DEPLOY <what> at <sha>: started | done, parity ok <receipt link>`
- `QUESTION @admin: <the decision, with options and a recommendation>`
- `BLOCKED @admin: <what is waiting on David, and why>`

GitHub carries the detail; the chat carries one line per event so David can
follow along. Questions for David go to `@admin` and stay specific enough to
answer in one reply.

## Deployment

1. Generate two random secrets on Tower. Add `claude-lead:<s1>` and
   `codex-lead:<s2>` to `HUB_CREDENTIALS` in
   `/mnt/user/appdata/agent-swarm/hub.env`, after a backup. Never reuse a
   secret.
2. Deploy `hub.py` through the supported gate, then recreate the container so
   the environment reloads, keeping every existing option (PID cap included;
   see `docs/context/DEPLOYMENT_INGEST92_2026-10-16.md`).
3. Run `auth_matrix.py` on Tower. It must be exactly diagonal.
4. On OfficePC, set each secret once with `setx` as a user variable. Each lead
   reads only its own.
5. Each lead posts one `CONFIRMED` line, and David sees both names in the chat
   in their own colours.
