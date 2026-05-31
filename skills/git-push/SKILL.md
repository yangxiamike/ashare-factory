---
name: git-push
description: Safely stage, commit, and push local Git changes to a configured remote. Use when the user asks to publish current project changes, initialize the first push, create a normal commit-and-push flow, or sync a local branch to GitHub or another remote repository.
---

# Git Push

Stage only the intended files, create a clear commit, and push the current branch without surprising the user.

## Workflow

1. Inspect repository state before changing anything.
2. Check whether the directory is already a Git repository.
3. Check current branch, remotes, and whether there are existing commits.
4. Review `git status --short` and note untracked or sensitive files.
5. If files like `.env`, secrets, tokens, or local credential files are about to be committed, stop and ask the user whether to ignore them.
6. Never use destructive Git commands unless the user explicitly requests them.

## Publish Flow

1. If `.git` does not exist, run `git init`.
2. If the user provided a remote URL and no matching remote exists, add `origin`.
3. Stage only the files that should be included.
4. If the user did not provide a commit message, use a short conventional message such as `chore: initial commit` or ask only when the choice materially matters.
5. Create the commit.
6. Push with upstream tracking when needed, for example `git push -u origin <branch>`.
7. If the remote rejects because it already has history, stop and explain whether the next safe step is pull/rebase, merge, or force push. Do not force push without explicit approval.

## Safety Rules

- Do not commit ignored secrets by accident.
- Do not assume `main`; inspect the current branch first.
- Do not rename branches unless the user asks.
- Do not amend, reset, rebase, or force push without explicit approval.
- If permissions or sandbox limits block Git writes or network push, request escalation with a short explanation.

## Response Shape

Report:

- what you found
- what you changed
- the commit hash and message
- the remote and branch pushed
- any remaining risk, such as untracked files that were left out
