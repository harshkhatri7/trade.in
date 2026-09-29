"""Marks ``tests/api`` as a package; see ``tests/__init__.py``.

The marker matters here twice over: it makes this directory's
``conftest.py`` a module named ``tests.api.conftest`` rather than a bare
``conftest`` that collides with every other one, and it puts the module
under the ``tests.*`` mypy override configured in ``pyproject.toml``.
"""
