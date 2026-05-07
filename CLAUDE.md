
<!-- From https://github.com/forrestchang/andrej-karpathy-skills/blob/main/CLAUDE.md -->


# Informer bot


## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. All Code Changes via Subagents in Worktrees

**The main session must not edit any project files. All implementation goes
through isolated subagents. When work can be split into independent parts,
spawn multiple subagents in parallel.**

- Always pass `isolation: "worktree"` when spawning subagents that will write
  or edit files.
- Read-only agents (Explore, planning, research) don't need worktree isolation.
- The main session reads, plans, delegates to subagents, and merges their
  results — it never authors changes directly.
- Treat the project source as read-only from the main session: no Edit/Write,
  no `sed -i`, no `>` redirects that mutate tracked files. Running tests,
  reading, and git operations that bring subagent branches in (`git merge`,
  cherry-pick) are fine.
- The primary working tree stays on `main`. Never `git checkout` (or
  `git switch`) it to a feature branch — feature branches always live in
  fresh worktrees created via `git worktree add -b feat/<name> <path> main`.
  This keeps `main` always available to other agents reading the canonical
  tree.

### Merge workflow (after subagents finish)

Subagents produce a worktree + branch. To bring their work onto `main`:

1. **Create a feature branch from `main`** in its own worktree
   (`git worktree add -b feat/<short-name> <path> main`, never
   `git checkout -b` in the primary tree). Never merge subagent branches
   straight into `main`.
2. **Commit each worktree's work** on its own branch inside the worktree
   (`git -C <worktree> add -A && git -C <worktree> commit -m "..."`). Use
   conventional-commit style messages and add a `Co-Authored-By` trailer.
3. **Merge each subagent branch into the feature branch** sequentially
   (`git merge --no-ff <subagent-branch>`). Disjoint file sets shouldn't
   conflict; investigate any conflict rather than papering over it.
4. **Verify on the feature branch**: run the full test suite and any other
   sanity checks before declaring success.
5. **Wait for the user's explicit approval** before merging the feature
   branch into `main`. Don't merge to `main` autonomously.
6. **Clean up after merging to `main`**: remove each subagent worktree
   with `git worktree remove <path>` and delete each merged branch with
   `git branch -d <branch-name>`. Use `-D` only if the branch is verifiably
   merged but git refuses (e.g. it was rebased rather than fast-forwarded).
   Skip cleanup only if the user explicitly says "leave it" or "don't touch".

## 5. Keep Docs Current

**After making changes, update the relevant doc if appropriate.**

If your changes affect anything documented — stack, layout, behaviour rules,
required env vars, setup/run instructions, TODOs — update the relevant file
in the same change. Quick map of where things live:

- `CLAUDE.md` — guidance rules for Claude (this file).
- `README.md` / `README_RU.md` — top-level intro and links.
- `docs/` — user-facing documentation (setup, Docker, hosting, etc.).
- `docs/internals/` — project context for development (see links below).

If nothing documented is affected, leave the docs alone.

## 6. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

---

# Project context for development

Project context is split across topic-focused files in `docs/internals/`. Read
the ones relevant to your current task; don't load everything blindly.

- [architecture.md](docs/internals/architecture.md) — what this is, roles, stack.
- [layout.md](docs/internals/layout.md) — repo layout & TDD order.
- [env-vars.md](docs/internals/env-vars.md) — required env vars (`data/.env`).
- [miniapp.md](docs/internals/miniapp.md) — Mini App server, endpoints, Caddy.
- [behaviour.md](docs/internals/behaviour.md) — channel list, triggers, catch-up, summary, DM format, access gate, localization, bot UX, refresh, session security.
- [storage.md](docs/internals/storage.md) — SQLite schema.
- [dedup.md](docs/internals/dedup.md) — deduplication pipeline.
- [auto-delete.md](docs/internals/auto-delete.md) — per-user auto-delete + sweeper.
- [processor-bot.md](docs/processor-bot.md) — sidecar bot for private GPU hosts (bus group, protocol, fallback).
- [todos.md](docs/internals/todos.md) — open TODOs.
