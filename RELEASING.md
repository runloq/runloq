# Releasing runloq

runloq publishes to PyPI via **Trusted Publishing (OIDC)** — no API tokens are ever
stored in the repo or in GitHub secrets. The CI workflow
[`.github/workflows/publish.yml`](.github/workflows/publish.yml) authenticates to
PyPI using GitHub's OIDC identity, so a release is just a tag push.

## First-time launch checklist (once, right after the repo's Initial commit)

After pushing the initial commit to `runloq/runloq`:

1. **Cut the first release** — follow "One-time setup" + "Cutting a release" below to
   ship `0.1.0` to PyPI (add the PyPI pending publisher, then push the `v0.1.0` tag).
2. **Branch protection on `main`** — Settings → Branches → add a rule for `main`:
   require a pull request before merging, require status checks (the test workflow) to
   pass, and disallow direct pushes to `main`. From then on all changes land via PR.
3. **Enable the docs site** (optional) — Settings → Pages → deploy from the
   `.github/workflows/docs.yml` build if you want the Astro docs published.

## One-time setup (maintainer, per repository)

Do this once after the public repo exists. It is the only manual step; after it,
every release is `git tag … && git push --tags`.

### 1. Create the GitHub "pypi" environment

In the GitHub repo: **Settings → Environments → New environment** → name it
`pypi` (the workflow's `build-and-publish` job declares `environment: pypi`).
Optionally add required reviewers so a human approves each publish.

### 2. Add the PyPI pending publisher (production)

On PyPI: **Account → Publishing → Add a new pending publisher**
(<https://pypi.org/manage/account/publishing/>). For a project that does not
exist yet, use a *pending* publisher with these exact values:

| Field             | Value              |
|-------------------|--------------------|
| PyPI Project Name | `runloq`           |
| Owner             | `<github-owner>`   |
| Repository name   | `runloq`           |
| Workflow name     | `publish.yml`      |
| Environment name  | `pypi`             |

The owner / repository must match the real GitHub location of the public repo.

### 3. (Optional) Add the TestPyPI pending publisher

The workflow runs a dry-run publish to TestPyPI before the real one. For that
step to succeed, add the same pending publisher on
<https://test.pypi.org/manage/account/publishing/> (identical fields). If you
prefer to skip the dry-run, delete the **"Publish to TestPyPI (dry run)"** step
from `publish.yml` instead.

## Cutting a release

1. Make sure `main` is green and the working tree is clean.
2. Bump the version in [`pyproject.toml`](pyproject.toml) (`[project].version`)
   and add a section to [`CHANGELOG.md`](CHANGELOG.md) (newest first).
3. Commit, then tag with a `v`-prefixed semver and push the tag:

   ```bash
   git commit -am "release: 0.1.0"
   git tag v0.1.0
   git push origin main --tags
   ```

4. The `v*.*.*` tag triggers `publish.yml`:
   - runs the test matrix (Python 3.11 / 3.12),
   - builds the dashboard SPA (`npm ci && npm run build`) so the wheel bundles it,
   - builds the wheel and **verifies the SPA assets are inside it**,
   - dry-run publishes to TestPyPI,
   - publishes to PyPI via OIDC trusted publishing.

No token is required at any step — GitHub mints a short-lived OIDC credential
that PyPI trusts because of the pending publisher configured above.

## Notes

- **SPA prebuild is automatic in CI.** You only need a manual
  `cd dashboard/web && npm install && npm run build` when building a wheel
  *locally* (`python -m build`) — `dashboard/web/dist/` is gitignored and must
  exist at wheel-build time.
- The dist name is `runloq`; the importable package stays `prism`. Entry points:
  `runloq`, `runloq-serve`, `runloq-mcp`.
- First release to PyPI: do **not** publish until the public repo and both
  pending publishers are in place. Until then, install from source (see README).
