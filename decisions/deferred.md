# What is deliberately not done yet

A thing left undone with no trigger is a thing forgotten. Each row names what
would make it worth doing, so the question comes back on its own rather than
depending on someone remembering it. Nothing enforces a trigger; the list is
read whenever a decision record is written and when a phase ends.

| Not done | The trigger | Why not now |
|---|---|---|
| A fixed coverage threshold in CI | Two months of measured coverage to set it below | The ratchet already refuses a pull request that lowers coverage; a fixed number picked before there is data is a guess with a gate on it |
| A code of conduct and issue templates | A second contributor, or the first outside issue | Boilerplate answering questions nobody has asked |
| A release workflow and publishing | The first release someone outside will install | A published name is claimed and a published version cannot be reused |
| `CODEOWNERS` | A second person who reviews | It would name one person as the owner of everything |
| `pre-commit` as a requirement rather than an option | A second contributor | The gates run in CI, and a hook one person installs is a hook one person maintains |
| A check that refuses code making a temporary file it never removes (new-plugin-v8.md, "A run cleans up after itself") | The shared check package voice-checks is on claude-voice's main with its temporary-file check (claude-voice #382) | The voice plugins are moving their copies of shared checks into voice-checks; a copy written here now would be one more to remove |
| A setup guide (`docs/setup.md`) with the owner's own steps marked, the README's step list made from it, and the test that keeps the two in step (new-plugin-v8.md, "Docs: the same three parts") | voice-checks carries the docs script and its test | ams-mcp, messages-mcp and map-mcp each have their own copy already; a fourth adds to the drift the shared package is removing |
