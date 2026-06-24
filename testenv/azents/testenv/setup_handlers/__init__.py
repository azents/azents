"""Setup handler execution boundary.

Each setup is implemented as a Python script referenced by setup frontmatter,
for example ``handler: testenv/setup_handlers/<id>.py``. The runner executes it
with ``uv run python <handler.py>``.

File names convert setup ids from kebab-case to snake_case, for example
``test-user-workspace`` → ``test_user_workspace.py``.

Handler contract:

- Read ``$STATE_FILE`` from the environment, load it with
  :func:`testenv.state.state_from_env`, and save updates with ``State.save()``.
- Return BLOCKED by writing a reason and exiting with ``sys.exit(2)``.
- PASS/FAIL should reflect whether the setup created real state successfully.
"""
