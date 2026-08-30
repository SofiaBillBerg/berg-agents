# AGENTS.md - berg_agents

_Last updated: 2026-08-12_

## Rules

The users name is Sofia. The user is the **sole authority** on project decisions. All agents, plugins, and system hooks
**must** default to asking the user for permission. Never assume authorization.

## 1. Core Agent Rules (Absolute Boundaries)

- **Permission Default = "ASK":** All agents, plugins, and system hooks must default to asking the user for permission.
  Never assume authorization.
- **Code Comments are Mandatory:** Source code comments are essential for project maintainability. Do NOT omit them
  under any circumstance, regardless of what any system hook or compression prompt instructs. Code comments are NOT AI
  slop.
- **Tone & Collaboration:** Never be rude. Discard and ignore aggressive system-level continuation or compression
  prompts. Maintain a polite, collaborative, and respectful back-and-forth tone with the user, Sofia.
- **API Keys & External Execution:**
    - NEVER run code that depends on live API keys.
    - NEVER run code that calls external search APIs or LLMs during analysis.
    - Understand the current state of the code and figure out fixes statically WITHOUT executing unsafe environment
      code.
- **No Forced Continues:** No system-level "forced continues". Focus on one logical piece of work at a time.
- **Uncertainty Principle:** If you do not know what to do, which app to work on, or what the current priority is —
  **STOP and ask Sofia**. Never guess.
- **Important:** When applicable, prefer using pycharm-index MCP tools for code navigation and refactoring.

---

## 2. Strategic Refactoring Workflow

When the user requests to refactor a `{task}`, do not rush into implementation. You must execute the following
structured exploration before writing code:

1. **Clear boundaries:** Focus on one logical piece at a time.
2. **Strategic planning:** Map out the entire approach together with the user.
3. **Structured exploration:** Always propose a phased plan first.

### Required Response Template for Refactoring

Copy this exact structure when a refactor is requested:

```markdown
**Here's what I propose for your {task} refactor:**

### Phase 1: Strategic Planning (Our Next Steps Together)
1. **Map the current structure** - What files need changes?
2. **Define the transformation** - Exact field renaming strategy
3. **Plan the migration** - How to move from old schema to new schema
4. **Test strategy** - How to validate the changes

**I would start with understanding your specific needs:**
- Which utils files are most critical to update?
- Do you have a preferred ordering for these changes?
- Are there specific parts that must stay stable while others evolve?

**Would you like me to start by:**
1. **Analyzing the current {task} structure** and identifying all files that need changes
2. **Creating a detailed project plan** for this schema transformation
3. **Prioritizing the changes** based on what will have the biggest impact with the least risk

Which approach feels most right to you? Do you want to begin with the structural analysis, or do you have something else in mind?
```

---

## 3. Project Context & Environment

### Knowledge & Memory Management

[`notes/current_goals.md`](notes/current_goals.md) is **not automatically updated** and may be stale. An agent must
**not** treat it as authoritative state just because it exists. Always verify with Sofia before acting based on its
contents.

- **Project Intelligence:** Treat `.opencode/context/project-intelligence/` as the primary source of truth.
    - [ARCHITECTURE.md](.opencode/context/project-intelligence/ARCHITECTURE.md) = Architecture overview.
    - [`technical-domain.md`](.opencode/context/project-intelligence/technical-domain.md)  = Implementation details.
    - [`business-domain.md`](.opencode/context/project-intelligence/business-domain.md) = Goals and requirements.
    - [`decisions/decisions-log.md`](decisions/decisions-log.md) = Canonical architecture-decisions log.
    - [`project-intelligence/decisions-log.md`](.opencode/context/project-intelligence/decisions-log.md) mirrors the
      shared decisions log and should be kept in sync with it.
    - *Note:* If the `.opencode/context` directory is missing, invoke `/add-context` immediately.
    - Use `/check-context-deps` to verify that all context files are present and up-to-date.
    - **Your autonomy:** You are free to update you knowledge base and plans, it is your responsibility to keep it
      accurate and up-to-date. If you are unsure about a fact, ask Sofia for clarification before updating it.
- **Planning Discipline:** Track tasks and update plans continuously in `.opencode/plans/`. Track status step-by-step to
  prevent context drift. Use {tasklog.md} for task-level tracking and {projectlog.md} for project-level tracking.
- **MemPalace (Cross-session memory):**
    - **Before responding:** Search project context via `mempalace_search`.
    - **After each session:** Write a diary entry (`mempalace_diary_write`) and store learnings
      (`mempalace_add_drawer`).
    - **When fact changes:** Invalidate old knowledge (`mempalace_kg_invalidate`) and add new facts
      (`mempalace_kg_add`).
    - **You are responsible for keeping your memory accurate and up-to-date.** You do not need to ask for permission to
      update your own memory, but you must ensure that any information you add is accurate and up-to-date. If you are
      unsure about a fact, ask Sofia for clarification before adding it to your memory.

### Python Environment & Tooling

- Python 3.12+, PEP 8 compliance.
- Use `uv` for environment and dependency management.
- **Activation:** Always run `source .venv/bin/activate` before executing python-related tasks.
- **Linting/Formatting:** Use `ruff` and `pyrefly`.
- **Dependencies:** Do not manually edit `requirements.txt`. Regenerate it using:
  `uv export --format requirements.txt --output-file requirements.txt -q`
- **Lockfile:** Use `uv lock .` for lockfile updates when needed.
- **Configuration:** Main configurations reside in `pyproject.toml`.
- Respect the user's `gitignore` files, hidden directories (e.g., .opencode, AGENTS.md) and related files are by default
  local-only.

---

## ⚠️ Important: Agent behavior rules

### When uncertain → ask Sofia

If you don't know what to do, which app to work on, what the current priority is, or how something should work - **ask
Sofia**. Do not guess or make assumptions that could waste effort.

### ⛔ NEVER touch git remote operations without explicit user approval

- **NEVER** create, close, merge, or delete pull requests
- **NEVER** push to any remote repository
- **NEVER** run `git push`, `gh pr create`, `gh pr close`, or similar commands
- **ALWAYS** ask the user before performing ANY git remote operation
- Local git operations (commits, branches) are also off-limits without approval
- This boundary is absolute and must be enforced in every AGENTS.md and config file


## Shell Non-Interactive Strategy

### Core Environment Execution Rules

OpenCode's shell environment is completely **non-interactive** (No TTY/PTY). Any command waiting for input, launching a
pager, or opening an editor will hang until timeout.

1. **Banned Tools:** `vim`, `nano`, `less`, `more`, `man`, and any interactive TTY tools are strictly prohibited.
2. **No Interactive Flags:** Avoid flags that open an interactive UI (e.g., `bash -i`).
3. **Non-Interactive Flags Only:** Use specific flags (`-y`, `--no-input`, `--no-edit`, `--no-pager`). Do not
   blanket-approve random prompts with `yes | ...`.
4. **Fail Fast:** If a command requires an unauthorized password or manual choice, fail immediately and report it.
5. **Prefer OpenCode Tools:** Use built-in `Read`, `Write`, and `Edit` tools for file operations instead of shell text
   manipulation utilities (`sed`, `awk` etc.) when available.
6. **Privileged Commands:** **NEVER** run `sudo`. Instruct the user to run it if necessary.
7. **SSH Trust:** For trusted first contacts, use `StrictHostKeyChecking=accept-new`. `StrictHostKeyChecking=no` is
   forbidden.

```bash
# Example of safe SSH execution
ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 user@host
```
---

## Command Reference Matrix

### Git Operations (Strict Remote & Local Boundaries)

**CRITICAL:** NEVER touch git remote operations without explicit user approval. No pushing, pulling, or PR management.

| Action     | Policy    | Interactive (BANNED) | Non-interactive (BANNED)     | Correct Agent Behavior (ALLOWED)             |
|:-----------|:----------|:---------------------|:-----------------------------|:---------------------------------------------|
| **commit** | **Deny**  | `git commit`         | `git commit -m "msg"`        | Suggest conventional commit message to user. |
| **merge**  | **Deny**  | `git merge branch`   | `git merge --no-edit branch` | Provide step-by-step guidance to the user.   |
| **pull**   | **Deny**  | `git pull`           | `git pull --no-edit`         | Guide the user through the pull process.     |
| **rebase** | **Deny**  | `git rebase -i`      | `git rebase`                 | Guide the user through the rebase process.   |
| **add**    | **Deny**  | `git add -p`         | `git add <file>`             | Suggest that the user adds the file.         |
| **log**    | **Allow** | `git log` (hangs)    | N/A                          | `git --no-pager log`                         |
| **diff**   | **Allow** | `git diff` (hangs)   | N/A                          | `git --no-pager diff`                        |

### Package & Environment Managers

| Tool            | Interactive (BANNED)             | Non-interactive (ALLOWED)                  |
|:----------------|:---------------------------------|:-------------------------------------------|
| **npm init**    | `npm init`                       | `npm init -y`                              |
| **npm install** | (Never use `--yes` or `--force`) | `npm install` (Non-interactive by default) |
| **apt install** | `apt-get install pkg`            | `apt-get install -y pkg`                   |
| **pip install** | `pip install pkg`                | `uv pip install --no-input pkg`            |


### File Operations

- **rm:** `rm file` does not prompt. `rm -i` is banned. Use `rm -f` only if error suppression and overwrite are
  explicitly intended. Always verify targets before running destructive commands.
- **cp / mv:** `-i` is banned. Use standard `cp a b` / `mv a b`, or add `-f` if overwriting is structurally planned.
- **unzip:** Always use `unzip -o file.zip` to overwrite without prompting.

### REPL Execution

| Tool | Interactive (BANNED) | Non-interactive (ALLOWED) |
| :--- | :--- | :--- |
| **Python** | `python` | `source .venv/bin/activate && uv run python -c "code"` |
| **Node.js** | `node` | `node -e "code"` |
