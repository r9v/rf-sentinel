# CLAUDE.md

Coding preferences for this project.

## General

- Delete dead code rather than leaving it around (e.g. obsolete CLI modules, unused functions).
- Don't add comments unless the logic is genuinely non-obvious.
- IMPORTANT: When investigating a bug, first add logs to confirm the issue before jumping into a fix. Don't assume the root cause — verify it with evidence.

## File organisation

- Don't create a new file for something that's only used in one place. Keep it in the same file.
- Split modules when a single file mixes distinct concerns (e.g. WebSocket management, REST routes, and entry point all in one file is too much).
- Use thin `__init__.py` / index files as re-export surfaces — put the real logic in focused submodules.
- When splitting causes circular imports, extract shared types into a dedicated `types.py` (or similar) rather than restructuring everything else.

## React / TypeScript

- Extract repeated or complex JSX into named components in the **same file** — don't create a new file unless the component is used in more than one place.
- Extract complex render logic (long canvas draw functions, multi-state returns) into named helper functions in the same file.
- State should live as low as possible. If only one subtree uses a piece of state, own it there — don't prop-drill from a parent that doesn't need it.
- Unify near-identical abstractions (e.g. two broadcast functions that do the same thing → one).
- For long or conditional `className` strings, extract them as named constants at the top of the same file rather than using CSS files or extra libraries:
  ```tsx
  const card = "px-3 py-2 rounded-lg border border-gray-700/50 bg-gray-800/30";
  const cardSelected = "border-cyan-500/40 bg-cyan-500/5";
  ```

## Python

- Pure data-transform functions (e.g. `downsample_2d`) belong in `dsp/`, not in plotting or runner.

## Debugging

- This is IMPORTANT so repeating again: When investigating a bug, first add logs to confirm the issue before jumping into a fix. Don't assume the root cause — verify it with evidence.

## Git

- Never commit or push without explicit user confirmation.
- Commit messages: one short line, no bullet points, no details.
