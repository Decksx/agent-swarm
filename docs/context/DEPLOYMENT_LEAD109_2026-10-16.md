# Lead identities deployment — 2026-10-16

Claude owned this rollout. It was announced on issue #109 (comment 6221386160)
and completed there (comment 6221518139). The work was #109, implemented in PR #112.
Codex approved the exact head `fdb0ee0763286061057b575dac4b7cb8cdcd9a06` with
no remaining findings. CI was green, and it merged as
`2517f9ebd081fd49cf0804efa3f09aab56b086bf`. That merge's tree matches the merge
tree computed before merging.

## Steps and evidence

1. **Pause.** Engaged through the hub as `admin` with a recorded reason. The
   controller showed no live activations (121 DONE, 6 EXPIRED). The OfficePC
   workers kept running and were held by the pause.
2. **Backup** to `data/backups/lead109-20261016T174849Z/` on Tower (directory
   0700, files 0600): `container.json`, `hub.env` and `app.tar.gz`, plus
   SQLite backups of `chat.db` and `controller.db`. Both quick checks returned
   `ok`.
3. **Gate.** Ran `deploy_controller.sh` from clean main `2517f9e` with
   `C:\Python311\python.exe`, Git Bash and `PYTEST_ADDOPTS=-n 4`. No test
   selection or bypass was used.
   - Core: 2,378 passed, 10 local scheduler-permission skips.
   - Hub: 398 passed.
   - All 16 digests matched on the host.
   - Preflight: checkout, running and disk all at build `d61b1472f803`,
     schema 6.
4. **Credentials.** Added `claude-lead`, `codex-lead` and `relay` to
   `HUB_CREDENTIALS`, each a fresh `secrets.token_urlsafe(32)`, never printed
   or reused. `hub.env` remains 0600 root.
5. **Recreate** to reload the environment. The image digest, `medianet`, port
   8050, both bind mounts, `--privileged`, `label=disable`, the PID cap of
   2048, json-file logs (50m × 1), the Unraid labels, `unless-stopped` and the
   command were all kept. A scripted comparison against the backed-up
   `container.json` found one difference: the bind strings carried an explicit
   `:rw` before and none after, while the mounts themselves are identical and
   read-write. The only environment value that changed is `HUB_CREDENTIALS`.
6. **`auth_matrix.py`** on Tower returned `RESULT: isolated`: a diagonal over
   8 identities. Its 56 deliberate 401 probes (8 × 7) are the only 401s in the
   hub log for that window.
7. **OfficePC.** Set the user-level variables `CLAUDE_LEAD_HUB_SECRET`,
   `CODEX_LEAD_HUB_SECRET` and `RELAY_HUB_SECRET` from Tower's values and
   verified them without printing. `lead_chat.py` reads them through its
   registry fallback, so shells that were already open work too.
8. **Proof.**
   - `claude-lead` posted CONFIRMED #1495.
   - `codex-lead` authenticated on a read-only `read`. Codex then posted its
     own first line, CONFIRMED #1497, and read it back independently.
   - `relay` authenticated on `/control/status`.
9. **Resume.** Workers resumed claiming and polling. The supervisor's only
   gap was the planned restart window.

## Found and fixed

Nine older backups in `/mnt/user/appdata/agent-swarm` contained hub
credentials and were mode 666: `hub.env.pre-*`,
`agent-hub.inspect.backup.json` and `container.pre-*.json`. They are now 600.
**Exposure: permissions are repaired; historical disclosure is unknown.**

- The `appdata` share is not exported (`shareExport="-"`). No container,
  current or stopped, bind-mounts `/mnt/user`, `/mnt/user/appdata` or the
  `agent-swarm` root.
- That doesn't rule out readers (Codex, #115 review at `e9e42c3`):
  - Non-root host processes share the host mount namespace, among them
    dbus UID 81, dnsmasq UID 99, avahi UID 61, ntpd UID 44 and smbd UID 99.
    The path ancestors are traversable (`/mnt` 0755; `/mnt/user`,
    `appdata` and `agent-swarm` 0777), so those UIDs could read 0666 files.
  - Homarr binds `/var/run/docker.sock`. Read-only on the bind doesn't
    restrict the Docker API, so container-mediated host access can't be
    excluded.
  - A present-day inventory can't show who read the files during their
    exposure window.
- There is no evidence of a copy or a compromise. Equally, that doesn't
  show there were no readers.
- **Still-active credentials in those files** (checked on Tower, names
  only): `admin`, `claudecode`, `gemini`, `chatgpt` and `narrator`, each
  in 4 of the 9. The new `claude-lead`, `codex-lead` and `relay` secrets
  appear in none.

**Follow-up, owner Claude:** a coordinated rotation of those five. Generate
new values in `hub.env`, recreate the hub with preserved options, then stop
and restart the OfficePC supervisor and workers through the supported
controls. `swarm_ctl.sh` fetches their secrets from `hub.env` at start.
Finish with the `auth_matrix.py` diagonal and component parity. Rotating
`admin` also changes David's chat-page login, so it is coordinated with him.

## Open

- **Unpinned startup install.** The container command runs an unpinned
  `pip install fastapi uvicorn pydantic` on every start, so a recreate can
  pick up new versions. Pinning it is a small follow-up.
- **Relay.** Design is PR #114 (design v3, under review). The `relay`
  credential is installed but nothing uses it yet.
