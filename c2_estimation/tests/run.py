"""Run C2 software checks with all disposable fixtures in one C2 scratch area.

The app-adjacent test files are fingerprinted by existing study databases. Leave
those files intact: replace only their tempfile binding for this test process.
"""
import argparse
from contextlib import contextmanager, ExitStack
from importlib import import_module
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from c2_estimation.tests.scratch import temporary_directory


class FixtureTempfile:
    def TemporaryDirectory(self, *, prefix="c2-app-test-", dir=None):
        return temporary_directory(prefix=prefix)

    def __getattr__(self, name):
        return getattr(tempfile, name)


@contextmanager
def isolated_app_fixtures():
    with ExitStack() as stack:
        for name in ("c2_estimation.live.test_live", "c2_estimation.human_study.test_study",
                     "c2_estimation.self_review.test_self_review"):
            stack.enter_context(patch.object(import_module(name), "tempfile", FixtureTempfile()))
        yield


def build_suite(scope="all"):
    if scope not in {"core", "apps", "all"}:
        raise ValueError("Unknown C2 software-check scope")
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    if scope in {"core", "all"}:
        suite.addTests(loader.discover(str(Path(__file__).resolve().parent)))
    if scope in {"apps", "all"}:
        suite.addTests(loader.loadTestsFromNames([
            "c2_estimation.live.test_live",
            "c2_estimation.human_study.test_study.StudyTests",
            "c2_estimation.self_review.test_self_review.SelfReviewTests",
        ]))
    return suite


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("core", "apps", "all"), default="all")
    args = parser.parse_args()
    with isolated_app_fixtures():
        result = unittest.TextTestRunner(verbosity=2).run(build_suite(args.scope))
    raise SystemExit(not result.wasSuccessful())


if __name__ == "__main__":
    main()
