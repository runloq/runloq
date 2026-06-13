from setuptools import setup
from setuptools.command.build_py import build_py

# ---------------------------------------------------------------------------
# Modules that live at the repo root but must NOT be shipped in the wheel.
#
# conftest.py  - pytest bootstrap (now lives in tests/); ran sys.path surgery
#                at import time; irrelevant outside the repo.
# check_new.py - UserPromptSubmit hook helper for Claude Code; not a public
#                API and depends on a specific monorepo layout.
# setup.py     - build-time helper; must not become a prism.setup module in
#                site-packages.
#
# Using a custom build_py subclass because setuptools exclude-package-data
# only filters data files, not Python source modules collected by build_py.
# ---------------------------------------------------------------------------
_WHEEL_EXCLUDE: frozenset[str] = frozenset({"conftest", "check_new", "setup"})


class build_py_filtered(build_py):
    """Drop dev-only root modules from the installed wheel."""

    def find_package_modules(self, package, package_dir):
        modules = super().find_package_modules(package, package_dir)
        return [
            (pkg, mod, path)
            for pkg, mod, path in modules
            if not (pkg == "prism" and mod in _WHEEL_EXCLUDE)
        ]


setup(cmdclass={"build_py": build_py_filtered})
