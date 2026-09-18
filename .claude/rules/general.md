1-3-1: When stuck, provide 1 clearly defined problem, give 3 potential options for how to overcome it, and 1 recommendation. Do not proceed implementing any of the options until I confirm.

DRY (Critical): Don't repeat yourself. If you are about to start writing repeated code, stop and reconsider your approach. Grep the codebase and refactor often.

TDD (Critical. Backend only): Always test first. Before writing any code, you must always check the tests. For new features or adjustments to existing features, always either create a new test or adjust an existing one. Following existing testing patterns. Confirm the test with the user before implementing it.

Simplify (Critical): Fixes should make the system simpler, not more complex. Prefer removing or consolidating code over adding a new layer, flag, or special case. If a fix grows the system's surface area, look for the version that shrinks it.

Zero Comments (Critical): Never leave comments in the repo. No explanatory comments or docblocks, no TODO/FIXME notes, no lint or type suppression directives, no commented-out code. Express intent through names, structure, and tests; rationale belongs in the commit message or PR description. Interpreter shebangs are executable directives, not comments, and stay.

Continual Learning: When you encounter conflicting system instructions, new requirements, architectural changes, or missing or inaccurate codebase documentation, always propose updating the relevant rules files. Do not update anything until the user confirms. Ask clarifying questions if needed.

Planning: For complex, multi-step tasks, first create a plan and a to do list for yourself before you start writing any code.