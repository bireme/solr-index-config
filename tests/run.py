#!/usr/bin/env python3
"""Run the configuration tests. See README.md ("Testing") for usage."""
import argparse
import importlib
import os
import sys
import time
import unittest

sys.dont_write_bytecode = True  # keep the checkout free of __pycache__
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from lib import base, gitref, solr  # noqa: E402
from lib.config import CORES, REPO  # noqa: E402
from lib.known_issues import KNOWN  # noqa: E402

DEFAULT_JAR = os.path.join(REPO, "..", "iahx", "iahx-analyzer", "jar", "iahx-analyzer-20260119.jar")
DEFAULT_DECS = os.path.join(REPO, "..", "iahx", "iahx-analyzer", "resources", "decs", "main")
LIVE_CLASSES = ["Load", "Visibility", "Generic", "Specific"]


def needs_decs(core):
    """True when the schema uses BIREME's analysis classes (analyzer jar + DeCS index needed)."""
    return any(c.startswith("org.bireme") for t in base.config(core).types.values() for c in t["classes"])


def test_label(test):
    return "%s.%s" % (type(test).__name__, test._testMethodName)


def _describe(test):
    return "%-20s %s" % (test.core, test_label(test))


base.CoreTest.__str__ = _describe
base.CoreTest.shortDescription = lambda self: None


class Result(unittest.TextTestResult):
    """Text result that also keeps a tally per core."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tally = {}
        self.skip_reasons = {}
        self.expected = []

    def _count(self, test, column):
        core = getattr(test, "core", None) or "(setup)"
        self.tally.setdefault(core, dict.fromkeys(
            ["passed", "failed", "skipped", "known issues", "fixed known issues"], 0))[column] += 1

    def addSuccess(self, test):
        super().addSuccess(test)
        self._count(test, "passed")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._count(test, "failed")

    def addError(self, test, err):
        super().addError(test, err)
        self._count(test, "failed")

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._count(test, "skipped")
        self.skip_reasons.setdefault((getattr(test, "core", "?"), reason), 0)
        self.skip_reasons[(getattr(test, "core", "?"), reason)] += 1

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self._count(test, "known issues")
        self.expected.append(test)

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self._count(test, "fixed known issues")


def build_suite(cores, live):
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    modules = {c: importlib.import_module("cores.test_" + c.replace("-", "_")) for c in cores}
    order = [(c, "Static") for c in cores]
    if live:
        order += [(c, name) for c in cores for name in LIVE_CLASSES]
    unknown = {c: set(KNOWN.get(c, {})) for c in cores}
    for core, name in order:
        cls = getattr(modules[core], name, None)
        if cls is None:
            continue
        for test in loader.loadTestsFromTestCase(cls):
            label = test_label(test)
            unknown[core].discard(label)
            if label in KNOWN.get(core, {}):
                test.__unittest_expecting_failure__ = True
            suite.addTest(test)
    if live:  # with --static-only, entries for live tests are simply not exercised
        for core, labels in unknown.items():
            for label in sorted(labels):
                sys.exit("known_issues.py: %s has no test named %s" % (core, label))
    return suite


def print_changes(cores, ref):
    """Print differences against the ref. Returns the number of cores that differ."""
    print("== Changes vs %s" % ref)
    differing = 0
    for core in cores:
        old = gitref.model_at(ref, core)
        if old is None:
            print("  %s: not present at %s (new core)" % (core, ref))
            differing += 1
            continue
        lines = gitref.diff(old, base.config(core))
        if lines:
            differing += 1
            print("  %s:" % core)
            for line in lines:
                print("    " + line)
        else:
            print("  %s: no differences" % core)
    print()
    return differing


def main():
    ap = argparse.ArgumentParser(description="Tests for the Solr core configurations in this repository.")
    ap.add_argument("cores", nargs="*", metavar="CORE", help="cores to test (default: all): " + ", ".join(CORES))
    ap.add_argument("--changed", action="store_true", help="only the cores whose conf/ differs from the git ref")
    ap.add_argument("--ref", help="git ref to compare with (default: origin/main, then main)")
    ap.add_argument("--strict", action="store_true", help="fail when a core differs from the git ref")
    ap.add_argument("--image", default=os.environ.get("SOLR_IMAGE", "solr:9.9"),
                    help="Solr Docker image (default: $SOLR_IMAGE or solr:9.9)")
    ap.add_argument("--static-only", action="store_true", help="only the checks that need no Docker")
    ap.add_argument("--fast", action="store_true", help="skip the 20 s explicit-commit visibility check")
    ap.add_argument("--keep", action="store_true", help="leave the Solr container running afterwards")
    ap.add_argument("-v", "--verbose", action="store_true", help="list every test")
    args = ap.parse_args()

    bad = [c for c in args.cores if c not in CORES]
    if bad:
        ap.error("unknown core(s): %s (known: %s)" % (", ".join(bad), ", ".join(CORES)))
    cores = [c for c in CORES if c in args.cores] if args.cores else list(CORES)

    ref = gitref.resolve_ref(args.ref)
    if ref is None and (args.ref or args.changed or args.strict):
        print("git ref %s not found" % (args.ref or "origin/main or main"), file=sys.stderr)
        return 2
    if args.changed:
        changed = gitref.changed_cores(ref)
        cores = [c for c in cores if c in changed]
        if not cores:
            print("No core configuration differs from %s; nothing to test." % ref)
            return 0

    differing = 0
    if ref:
        differing = print_changes(cores, ref)
    else:
        print("== No git ref to compare with (origin/main and main not found); comparison skipped\n")

    live = not args.static_only
    container = None
    base.ctx.fast = args.fast
    try:
        if live:
            if not solr.docker_available():
                print("Docker is not available; use --static-only to run the checks that need no Solr.",
                      file=sys.stderr)
                return 2
            jar = os.path.abspath(os.environ.get("IAHX_JAR", DEFAULT_JAR))
            decs = os.path.abspath(os.environ.get("DECS_INDEX", DEFAULT_DECS))
            missing = []
            if not os.path.isfile(jar):
                missing.append("analyzer jar not found at %s (set IAHX_JAR)" % jar)
            if not os.path.isdir(decs) or not os.listdir(decs):
                missing.append("DeCS index not found at %s (set DECS_INDEX)" % decs)
            decs_cores = [c for c in cores if needs_decs(c)]
            if missing:
                for c in decs_cores:
                    base.ctx.live_skip[c] = "; ".join(missing)
            live_cores = [c for c in cores if c not in base.ctx.live_skip]
            if live_cores:
                container = solr.SolrContainer(args.image, live_cores, decs_cores, jar, decs)
                print("== Starting %s with %s" % (args.image, ", ".join(live_cores)))
                container.start()
                base.ctx.solr = container
                if not args.fast:
                    mods = {c: importlib.import_module("cores.test_" + c.replace("-", "_")) for c in live_cores}
                    for c in live_cores:
                        vis = getattr(mods[c], "Visibility", None)
                        if vis and c in container.loaded and vis.applicable():
                            r = container.core(c).update_json([vis.probe_doc()])
                            if container.core(c).ok(r):
                                base.ctx.probed.add(c)
                    base.ctx.probe_t0 = time.time()
                print()
        suite = build_suite(cores, live)
        result = unittest.TextTestRunner(stream=sys.stdout, resultclass=Result,
                                         verbosity=2 if args.verbose else 1).run(suite)
    finally:
        if container is not None:
            if args.keep:
                print("\nContainer kept: %s  (%s)  remove with: docker rm -f %s"
                      % (container.name, container.base, container.name))
            else:
                container.remove()

    print("\n== Summary (%s)" % ("static checks only" if not live else args.image))
    columns = ["passed", "failed", "skipped", "known issues", "fixed known issues"]
    print("  %-20s %s" % ("core", "  ".join("%s" % c for c in columns)))
    for core in sorted(result.tally):
        print("  %-20s %s" % (core, "  ".join(str(result.tally[core][c]).rjust(len(c)) for c in columns)))
    if result.skip_reasons:
        print("\n  Skipped:")
        for (core, reason), n in sorted(result.skip_reasons.items()):
            print("    %s: %d test(s): %s" % (core, n, reason))
    if result.expected:
        print("\n  Known issues (expected failures, see tests/lib/known_issues.py):")
        for test in result.expected:
            print("    %s %s: %s" % (test.core, test_label(test), KNOWN[test.core][test_label(test)]))
    if result.unexpectedSuccesses:
        print("\n  Known issues that no longer fail; remove them from tests/lib/known_issues.py:")
        for test in result.unexpectedSuccesses:
            print("    %s %s" % (test.core, test_label(test)))
    failed = not result.wasSuccessful()
    if args.strict and differing:
        print("\n  --strict: %d core(s) differ from %s" % (differing, ref))
        failed = True
    print("\n%s" % ("FAILED" if failed else "OK"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
