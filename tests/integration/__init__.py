"""Marks ``tests/integration`` as a package; see ``tests/__init__.py``.

The marker matters here twice over: it makes this directory's
``conftest.py`` a module named ``tests.integration.conftest`` rather than a
bare ``conftest`` that collides with every other one, and it puts the module
under the ``tests.*`` mypy override configured in ``pyproject.toml``. The
local ``_db`` helper is imported as a sibling package member for the same
reason - one copy of the safety assertions, one name to import.
"""
