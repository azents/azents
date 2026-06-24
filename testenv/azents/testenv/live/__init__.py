"""testenv/azents live helpers.

Live helpers run real interactions against previously seeded objects and, when
configured, actual LLM providers. The seed layer prepares objects; the live layer
exercises them.

Example:
    from testenv.seed import auth, workspace, llm, agent
    from testenv.live import chat, matchers
    from testenv.live.types import Session

    user = auth.create_user()
    ws = workspace.create(user)
    llm.register_model("gpt-4o-mini")
    integration = llm.create_integration(user, ws, api_key=os.environ["OPENAI_API_KEY"])
    a = agent.create(user, ws, integration, "gpt-4o-mini")

    session: Session = chat.start_session(user, a)
    events = chat.collect(session, "Hello, testenv!")
    matchers.run_completed(events)

Details: `docs/azents/design/llm-pipeline.md`

Import concrete types and errors directly, such as
`from testenv.live.types import Session` and
`from testenv.live.errors import ChatError`. `__init__.py` intentionally does not
re-export them, matching the seed package boundary.
"""
