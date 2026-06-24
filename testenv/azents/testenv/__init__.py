"""testenv — azents fixture/prerequisite support package.

Main entry points:

- :mod:`testenv.cli` — ``testenv bootstrap`` / ``testenv fixture`` /
  ``testenv prerequisite`` commands
- :mod:`testenv.fixture_runner` — fixture provider execution path
- :mod:`testenv.fixture_manifest` — fixture state manifest model
- :mod:`testenv.prerequisite_prepare` — external prerequisite snapshot creation
- :mod:`testenv.setup_runner` — fixture provider internal setup substrate
- :mod:`testenv.checks` / :mod:`testenv.devserverlib` / :mod:`testenv.seed` /
  :mod:`testenv.live` — support libraries used by those roots
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
