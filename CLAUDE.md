# Project context for Claude Code

## What this is
A learning and portfolio project: a usage-based revenue recognition model on synthetic data. The full requirements are in `SPEC.md`. Read it before doing anything.

## Who I am
Jonah, a CPA and controller. I know the accounting well. I'm new to Claude Code, Git, and Python projects, so explain any command or concept I might not know in one plain sentence.

## Rules
- **The accounting comes from SPEC.md, section 3.** Never invent or change an accounting treatment. If the code needs a policy decision the spec doesn't cover, stop and ask me.
- In the code, cite the spec section next to each accounting rule (for example, `# SPEC 3.3: revenue = credit consumed x 0.80`).
- **Synthetic data only.** Never add real company, customer, or employer data.
- Don't copy text from the PwC guide into the repo. Cite section numbers only.
- Use Python 3 with pandas and pytest. Keep the code small and readable over clever. A reviewer who is an accountant, not an engineer, should be able to follow it.
- Use a fixed random seed so the outputs are reproducible.
- Store money as `Decimal` or integer cents, never floats. Round only at the invoice-line level.
- Build in the order in SPEC.md section 8, MVP steps first. Propose a plan for each step before writing code, and wait for my OK.
- After each step, run the tests, show me the results, and commit with a clear message.
- `MEMO.md` is mine to write. You can review it, but don't write it.

## Commands
- Run tests: `pytest`
- Generate data and outputs: `python run.py` (to be created in step 1)
