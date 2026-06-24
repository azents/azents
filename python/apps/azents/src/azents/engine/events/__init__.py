"""Event unification package.

Handles type classification, parsers (write), and formatters (read).

Bidirectional SDK-origin and Azents-origin conversion on top of the events table.

- :mod:`classify` — classify an SDK item dict into (EventType, raw_data)
- :mod:`parsers` — convert raw SDK-origin values to data by type (snapshot on write)
- :mod:`formatters` — convert Azents-origin data to SDK input items by type (on read)
- :mod:`engine_events` — ephemeral event types yielded by the engine
"""
