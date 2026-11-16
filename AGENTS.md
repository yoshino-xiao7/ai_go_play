# Repository working agreement

Read README.md, CONTRIBUTING.md and docs/GOVERNANCE.md before making changes.

- Keep exactly three upstream branches: main, dev, and integration. Maintainers and agents commit to dev and submit dev → integration PRs. Community contributors work in their own forks and target integration.
- Preserve user changes, private assets, production data and active jobs.
- All development/community PRs target integration. Never push directly to main or integration.
- main only accepts owner-opened integration → main release PRs from this repository.
- Never merge main, choose a release version, create a release tag or publish on the owner's behalf without an explicit instruction for that exact action/version.
- The owner confirms the exact head SHA. New commits require new confirmation.
- Use isolated ports, configuration and data for tests; wait for existing GPU work.
- Keep docs and tests consistent. Do not claim unrun checks passed or prepared rules are enforced.
- Keep credentials, signed URLs, databases, weights, .qa and .manju out of Git.
- Preserve upstream license originals. Identity, functionality and redistribution rights are distinct.
- Follow docs/RELEASING.md and release/release-approval.json; never change pending evidence to approved merely to pass a gate.

Validate relevant pytest tests, frontend builds for UI, node --test tests/governance.test.cjs for governance, python scripts/check_docs.py for docs, and python scripts/check_release.py for version metadata.
