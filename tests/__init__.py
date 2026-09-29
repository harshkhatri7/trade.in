"""Marks ``tests`` as a package.

Two reasons, both about naming rather than about imports:

* ``pyproject.toml`` configures mypy with ``module = "tests.*"`` so that test
  code is exempt from ``disallow_untyped_defs``. That override only applies
  when the modules are actually called ``tests.<dir>.<file>``, which requires
  a marker at every directory on the way up - without them mypy reports the
  section as unused and applies strict mode to tests instead.
* ``conftest.py`` files in two directories are otherwise both called
  ``conftest``, which mypy treats as a fatal conflict rather than checking
  only one of them.

pytest derives each test module's package from the nearest directory without
this file (the repository root), so the root gets put on ``sys.path`` and
collection, fixtures and the ``pythonpath`` entries in ``pyproject.toml`` all
carry on working unchanged.
"""
