# Credential redaction before publication

GitHub push protection rejected the original context branch because an old
Docker command in `archive/Group AI Chat/Multi-Agent AI Dev Room Setup.md`
contained a Google Cloud credential. The rejected branch was not published.

This publishable reference copy redacts that credential and adjacent long
command literals in the affected historical command. It retains the remaining
project history. The original attachment and extracted package remain in the
local import workspace; they must not be pushed or used as runtime configuration.

`SHA256SUMS.original.txt` retains the original package manifest for comparison
with the local original. `SHA256SUMS.txt` now verifies the 51 files of the
redacted package, including the original manifest. Historical byte counts and
statements about the original package describe the import before redaction.

The older handoff's assertion that no credentials were transferred was incorrect
for the raw historical chat. The credential value is intentionally omitted here.
Publication does not establish whether the old credential remains valid or revoke
it. Review the affected Google credential separately if it is still in use.
