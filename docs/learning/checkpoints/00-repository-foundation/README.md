# Checkpoint 00 — Repository and GitHub Foundation

| Field | Value |
|---|---|
| Status | Complete |
| Date | 2026-08-02 |
| Branch | `main` |
| Pull request | Not applicable; this was the initial repository publication |
| Implementation commit | [`1085458`](https://github.com/Ajbil/agentic-chatbot-fastapi/commit/1085458) |

## Objective

Turn a local tutorial folder into a safe, identifiable, reproducible Git repository owned by the correct GitHub account without interfering with company repositories on the same laptop.

## Why this checkpoint came first

Version control is the safety net for every later experiment. Refactoring AI code without a trustworthy baseline would make it difficult to inspect changes, revert mistakes, compare approaches, or demonstrate the project's evolution.

Publishing only after secret protection was verified was especially important because the repository was intended to be public.

## Starting condition

- The folder contained three Python modules, Pipenv metadata, and a real `.env` file.
- It had no Git metadata, README, `.gitignore`, or remote.
- The laptop contained multiple GitHub identities used for personal and company work.
- Global Git used `user.useConfigOnly=true` and conditional identity configuration for company directories.
- GitHub CLI knew about multiple accounts, but the saved credentials initially needed reauthentication.

## Plan

1. Inspect the existing Git and GitHub identity configuration.
2. Add repository documentation and safe ignore rules before staging anything.
3. Initialize the repository with `main` as its default branch.
4. Configure the personal author identity locally for this repository.
5. Verify that `.env` could not be staged.
6. Create the first commit.
7. Reauthenticate the intended GitHub account, create the public repository, and push `main`.

## Decisions and alternatives

### Use repository-local author identity

- **Decision:** Store `Ajbil` and `ajbilstudymail@gmail.com` in `.git/config` for this repository.
- **Reason:** Commit identity is contextual. A local setting prevents the personal identity from leaking into company repositories and vice versa.
- **Alternative:** Change the global `user.name` and `user.email` before working on each project.
- **Tradeoff:** Each new personal repository needs an explicit identity or a future personal-folder `includeIf` rule.
- **Revisit when:** Several repositories live below one stable personal root; then a conditional personal config can reduce repetition safely.

### Keep `user.useConfigOnly=true`

- **Decision:** Preserve the existing safeguard.
- **Reason:** Git refuses to guess an identity when no applicable configuration exists. An early, clear failure is safer than commits attributed to the wrong account.
- **Alternative:** Let Git infer an identity from the Windows username and hostname.
- **Tradeoff:** Initial setup requires one extra command per unmatched repository location.

### Protect secrets before the initial commit

- **Decision:** Add `.gitignore` and `.env.example` before staging the project.
- **Reason:** Once a real secret enters Git history, removing it from the latest version is not enough; the credential must be revoked and history may require rewriting.
- **Alternative:** Commit everything first and clean it up afterward.
- **Tradeoff:** None of consequence. Secret review should be a mandatory publication gate.

### Use `main` as the initial branch

- **Decision:** Initialize explicitly with `main` despite the machine's older global `init.defaultBranch=master` setting.
- **Reason:** It matches current GitHub defaults and avoids an unnecessary rename after publication.
- **Alternative:** Accept `master` and rename it later.
- **Tradeoff:** Existing automation expecting `master` would need adjustment, but no such automation existed here.

### Use HTTPS through GitHub CLI

- **Decision:** Authenticate `Ajbil` with GitHub CLI and use an HTTPS remote.
- **Reason:** GitHub CLI and Windows Credential Manager can select and store account credentials without manually managing SSH host aliases on a multi-account laptop.
- **Alternative:** Configure separate SSH keys and aliases for each GitHub identity.
- **Tradeoff:** HTTPS relies on the credential-manager and CLI account state; SSH aliases can be more explicit for heavy multi-account workflows.
- **Revisit when:** Authentication ambiguity recurs frequently or automated signing/SSH workflows become important.

### Publish publicly after verification

- **Decision:** Create `Ajbil/agentic-chatbot-fastapi` as a public repository.
- **Reason:** The user selected public visibility for learning and portfolio use after the secret and staged-file checks passed.
- **Alternative:** Start private and change visibility later.
- **Tradeoff:** Public history is immediately visible, so every push requires stronger secret and content review.

## Implementation outcome

- Added a project README, Python-focused `.gitignore`, and sanitized `.env.example`.
- Initialized Git on `main`.
- Configured the repository-local author identity.
- Created the initial commit and pushed it to `origin/main`.
- Published the repository at [Ajbil/agentic-chatbot-fastapi](https://github.com/Ajbil/agentic-chatbot-fastapi).

## Validation evidence

- `git rev-parse --is-inside-work-tree` returned `true`.
- `git branch --show-current` returned `main`.
- `git log` showed commit `1085458` with the intended author.
- `git status` reported a clean working tree.
- `git config --local` showed the personal name and email.
- `git check-ignore` proved `.env` was ignored while `.env.example` remained trackable.
- `origin` was configured for both fetch and push, and local `main` tracked `origin/main`.

## Senior-engineering lessons

### Identity and authentication are different

`user.name` and `user.email` become commit metadata. They do not grant permission to GitHub. Authentication proves which GitHub account is performing a network operation. Both must be correct, especially on shared or company-managed machines.

### Version control starts before feature work

The value of Git is not merely remote backup. Small, intentional commits preserve decision boundaries, enable review, and make experiments reversible.

### A public-repository boundary is a security boundary

The correct sequence is classify files, ignore secrets, inspect the staged snapshot, scan for likely credentials, and only then publish. A `.gitignore` protects untracked files; it does not remove a file that was already committed.

### Safety exceptions should be narrow

Git's unsafe-repository warning occurred because the project and `.git` metadata were created under different Windows identities. Marking the exact trusted repository as safe was appropriate. Using `safe.directory "*"` would have disabled the protection globally and was intentionally avoided.

## Applying this elsewhere

- Determine the intended repository owner and visibility before publishing.
- Inspect global, conditional, and local Git configuration on multi-account machines.
- Set identity at the narrowest practical scope.
- Add ignore rules before the first broad staging operation.
- Inspect staged filenames and scan for secrets before every first public push.
- Verify branch tracking and the remote URL after publication.

## Common mistakes

- Assuming commit email selects the GitHub account used for pushing.
- Repeatedly replacing global identity values when conditional or local configuration is safer.
- Adding `safe.directory "*"` to silence ownership warnings everywhere.
- Assuming deleting `.env` in a later commit removes exposed credentials from history.
- Running `git add .` before understanding which files exist and which contain secrets.

## Explain-back questions

1. What is the difference between Git commit identity and GitHub authentication?
2. Why is repository-local identity safer on a multi-account laptop?
3. Why must `.gitignore` be established before the first commit?
4. What should happen if an API key is accidentally committed?
5. Why is a narrow `safe.directory` entry preferable to `*`?

## Deferred work

- Feature branches and pull-request review begin with checkpoint 01.
- Automated GitHub checks will be considered after the local test foundation exists.
- Commit signing can be added later if verified provenance becomes a project requirement.
