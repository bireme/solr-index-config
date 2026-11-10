"""Base test classes. Each core module subclasses them with `core = "<name>"`.

Run order per core (set by run.py): Static, Load, Visibility, Generic, Specific.
Every live class owns the index: it deletes everything and indexes its own documents.
"""
import json
import os
import time
import unittest
from xml.sax.saxutils import escape

from . import config as cfg_mod
from .known_issues import KNOWN_LOG_WARNINGS


class Context:
    """Shared run state, filled in by run.py."""
    solr = None            # SolrContainer, or None when no live tests run
    live_skip = {}         # core -> reason its live tests are skipped
    fast = False
    probe_t0 = None        # when the uncommitted probe documents were posted
    probed = set()


ctx = Context()
_configs = {}

FIXTURES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures")
PROBE_ID = "zz-uncommitted-probe"
VISIBILITY_WAIT = 20  # seconds; longer than the 15 s hard autoCommit of the cores that use it


def config(core):
    if core not in _configs:
        _configs[core] = cfg_mod.load(core)
    return _configs[core]


BIG = "x" * 40000  # longer than Lucene's 32766-byte limit for a single term / docValues value


def _expand(value):
    if value == "@BIG@":
        return BIG
    if isinstance(value, list):
        return [_expand(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    return value


def fixture(core, name="docs.json"):
    """Fixture documents of a core. The string "@BIG@" stands for a 40,000-character value."""
    with open(os.path.join(FIXTURES, core, name), encoding="utf-8") as f:
        return _expand(json.load(f))


class CoreTest(unittest.TestCase):
    core = None
    maxDiff = None

    @property
    def cfg(self):
        return config(self.core)


# --------------------------------------------------------------------------- static
class StaticChecks(CoreTest):
    """Checks on the files alone; no Solr needed."""

    def test_xml_well_formed(self):
        self.assertEqual(self.cfg.errors, [])

    def test_field_types_defined(self):
        missing = ["%s (type %s)" % (n, a.get("type"))
                   for n, a in list(self.cfg.fields.items()) + list(self.cfg.dynamic_fields.items())
                   if a.get("type") not in self.cfg.types]
        self.assertEqual(missing, [], "fields using an undefined fieldType")

    def test_copyfields_resolve(self):
        bad = []
        for source, dest in self.cfg.copy_fields:
            if "*" not in source and self.cfg.resolve_field(source) is None:
                bad.append("source %s" % source)
            if self.cfg.resolve_field(dest) is None:
                bad.append("dest %s" % dest)
        self.assertEqual(bad, [], "copyField names that match no field or dynamicField")

    def test_unique_key(self):
        key = self.cfg.unique_key
        self.assertIn(key, self.cfg.fields, "uniqueKey is not a declared field")
        self.assertTrue(self.cfg.effective(key, "indexed", True), "uniqueKey must be indexed")
        self.assertFalse(self.cfg.effective(key, "multiValued", False), "uniqueKey must be single-valued")

    def test_handler_fields_exist(self):
        bad = []
        for name, h in self.cfg.handlers.items():
            for key in ("df", "facet.field"):
                for value in h["defaults"].get(key, []):
                    if self.cfg.resolve_field(value) is None:
                        bad.append("%s %s=%s" % (name, key, value))
        self.assertEqual(bad, [], "handler defaults naming a field that does not exist")

    def test_select_has_default_field(self):
        self.assertIsNotNone(self.cfg.df("/select"), "/select has no df")

    # Items removed or ignored in Solr 9. One method each so they can be tracked individually.
    def _type_classes(self):
        out = []
        for name, t in self.cfg.types.items():
            out += [(name, c) for c in [t["attrs"].get("class")] + t["classes"] if c]
        return out

    def test_no_trie_fields(self):
        used = sorted({n for n, c in self._type_classes() if "Trie" in c})
        self.assertEqual(used, [], "Trie field types (deprecated; removed in Solr 10)")

    def test_no_word_delimiter_filter(self):
        used = sorted({n for n, c in self._type_classes() if c.endswith("WordDelimiterFilterFactory")})
        self.assertEqual(used, [], "WordDelimiterFilterFactory (use WordDelimiterGraphFilterFactory)")

    def test_no_legacy_schema_elements(self):
        self.assertEqual(self.cfg.legacy_schema_elements, [],
                         "defaultSearchField / solrQueryParser are not supported since Solr 7")

    def test_no_legacy_cache_classes(self):
        legacy = {k: v for k, v in self.cfg.caches.items() if v and "LRUCache" in v}
        self.assertEqual(legacy, {}, "LRUCache / FastLRUCache were removed in Solr 9")

    def test_no_jmx_element(self):
        self.assertFalse(self.cfg.jmx, "<jmx/> is no longer supported in Solr 9")

    def test_no_enable_remote_streaming_attribute(self):
        self.assertFalse(self.cfg.remote_streaming_attr,
                         "enableRemoteStreaming in <requestParsers> is ignored by Solr 9")

    def test_no_num_version_buckets(self):
        self.assertFalse(self.cfg.num_version_buckets, "numVersionBuckets in <updateLog> is obsolete in Solr 9")

    def test_no_lib_directives(self):
        self.assertEqual(self.cfg.libs, [], "<lib/> directives are disabled by default since Solr 9.8; "
                         "jars go in <instanceDir>/lib")

    def test_no_explicit_export_handler(self):
        self.assertFalse("/export" in self.cfg.handlers,
                         "an explicit /export handler shadows Solr 9's implicit one")


# ----------------------------------------------------------------------------- live
class LiveTest(CoreTest):
    """Base for tests that need the running container."""
    requires_loaded = True
    _unavailable = None

    @classmethod
    def setUpClass(cls):
        cls._unavailable = None
        if ctx.solr is None:
            cls._unavailable = "live tests not run"
        elif cls.core in ctx.live_skip:
            cls._unavailable = ctx.live_skip[cls.core]
        elif cls.requires_loaded and cls.core not in ctx.solr.loaded:
            cls._unavailable = "core did not load"
        if cls._unavailable is None:
            cls.solr = ctx.solr.core(cls.core)
            cls.prepare()

    @classmethod
    def prepare(cls):
        """Index what the class needs. Called once, only when the core is available."""

    def setUp(self):
        if self._unavailable:
            self.skipTest(self._unavailable)

    # helpers
    def nf(self, q, fq=None, **params):
        return self.solr.num_found(q, fq=fq, **params)

    def assertOk(self, response):
        self.assertEqual(response.get("responseHeader", {}).get("status"), 0, str(response)[:600])

    @classmethod
    def reindex(cls, docs):
        cls.solr.delete_all()
        r = cls.solr.update_json(docs, commit=True)
        if not cls.solr.ok(r):
            raise AssertionError("indexing fixture documents failed: %s" % str(r)[:800])


class LoadChecks(LiveTest):
    """The core loads on this Solr and its startup log is clean."""
    requires_loaded = False

    def test_core_loaded(self):
        failure = ctx.solr.init_failures.get(self.core)
        if failure is not None:
            errors = [l for l in ctx.solr.logs().splitlines() if " ERROR " in l or l.startswith("Caused by")]
            self.fail("core failed to load: %s\n%s" % (str(failure)[:800], "\n".join(l[:300] for l in errors[:12])))
        self.assertIn(self.core, ctx.solr.loaded)

    def test_no_errors_or_warnings_in_log(self):
        marker = "x:%s " % self.core
        lines = [l for l in ctx.solr.logs().splitlines()
                 if (" ERROR " in l or " WARN " in l) and (marker in l or "[%s]" % self.core in l)]
        known = KNOWN_LOG_WARNINGS.get(self.core, {})
        unexpected = [l for l in lines if not any(k in l for k in known)]
        self.assertEqual(len(unexpected), 0,
                         "ERROR/WARN lines for this core:\n" + "\n".join(l[:400] for l in unexpected[:15]))
        gone = [k for k in known if not any(k in l for l in lines)]
        self.assertEqual(gone, [], "known warnings no longer logged; remove them from known_issues.py")


class CommitVisibility(LiveTest):
    """With soft commits off and openSearcher=false, documents appear only on an explicit commit."""

    @classmethod
    def applicable(cls):
        c = config(cls.core)
        return c.soft_commit_off() and not c.hard_commit_opens_searcher()

    @classmethod
    def probe_doc(cls):
        return {config(cls.core).unique_key: PROBE_ID}

    def test_invisible_until_explicit_commit(self):
        if not self.applicable():
            self.skipTest("soft commit or openSearcher is on: documents appear without an explicit commit")
        if ctx.fast:
            self.skipTest("--fast")
        if self.core not in ctx.probed:
            self.skipTest("probe document was not posted")
        remaining = ctx.probe_t0 + VISIBILITY_WAIT - time.time()
        if remaining > 0:
            time.sleep(remaining)
        q = "%s:%s" % (self.cfg.unique_key, PROBE_ID)
        try:
            self.assertEqual(self.nf(q), 0, "document visible %d s after an update without commit" % VISIBILITY_WAIT)
            self.solr.commit()
            self.assertEqual(self.nf(q), 1, "document not visible after an explicit commit")
        finally:
            self.solr.delete_id(PROBE_ID)


class GenericLive(LiveTest):
    """Checks derived from the configuration itself, using 12 synthetic documents plus the fixture."""
    N = 12  # more than the default rows=10, so a degraded /export is detected
    ALPHA, BETA = "zzgenalpha", "zzgenbeta"

    @classmethod
    def df_source(cls):
        """A field whose content reaches the /select default field."""
        c = config(cls.core)
        df = c.df("/select")
        sources = [s for s in c.copy_sources(df) if "*" not in s]
        for s in sources:
            f = c.resolve_field(s)
            if f and f.get("type") == "text":
                return s
        return sources[0] if sources else df

    @classmethod
    def prepare(cls):
        c = config(cls.core)
        key, src = c.unique_key, cls.df_source()
        cls.fixture_docs = fixture(cls.core)
        cls.synthetic_ids = ["zz-generic-%02d" % i for i in range(1, cls.N + 1)]
        cls.solr.delete_all()
        cls.index_errors = []
        r = cls.solr.update_json(cls.fixture_docs)
        if not cls.solr.ok(r):
            cls.index_errors.append("fixture (JSON): %s" % str(r)[:600])
        half = cls.N // 2
        docs = [{key: i, src: cls.ALPHA + (" " + cls.BETA if n == 0 else "")}
                for n, i in enumerate(cls.synthetic_ids[:half])]
        r = cls.solr.update_json(docs)
        if not cls.solr.ok(r):
            cls.index_errors.append("synthetic (JSON): %s" % str(r)[:600])
        xml = "<add>%s</add>" % "".join(
            '<doc><field name="%s">%s</field><field name="%s">%s</field></doc>' % (key, i, escape(src), cls.ALPHA)
            for i in cls.synthetic_ids[half:])
        r = cls.solr.update_xml(xml)
        if not cls.solr.ok(r):
            cls.index_errors.append("synthetic (XML): %s" % str(r)[:600])
        cls.solr.commit()
        cls.total = len(cls.fixture_docs) + cls.N

    def test_documents_index_by_json_and_xml(self):
        self.assertEqual(self.index_errors, [])
        self.assertEqual(self.nf("*:*"), self.total)

    def test_default_field(self):
        self.assertEqual(self.nf(self.ALPHA), self.N,
                         "bare query should search df=%s (fed by %s)" % (self.cfg.df(), self.df_source()))

    def test_default_operator(self):
        expected = 1 if self.cfg.q_op() == "AND" else self.N
        self.assertEqual(self.nf("%s %s" % (self.ALPHA, self.BETA)), expected,
                         "two bare terms should be combined with %s" % self.cfg.q_op())

    def test_select_facets_present(self):
        wanted = self.cfg.facet_fields()
        if not wanted:
            self.skipTest("/select defines no facet.field")
        r = self.solr.select("*:*", rows=0)
        self.assertOk(r)
        got = r.get("facet_counts", {}).get("facet_fields", {})
        self.assertEqual(sorted(set(wanted) - set(got)), [], "facet fields missing from the /select response")

    def test_fl_star_hides_unstored_fields(self):
        r = self.solr.select("*:*", fl="*", rows=200)
        self.assertOk(r)
        # _version_ is conventionally stored=false and returned from docValues
        leaked = sorted({k for d in r["response"]["docs"] for k in d
                         if k != "_version_" and self.cfg.resolve_field(k) is not None
                         and not self.cfg.effective(k, "stored", True)})
        self.assertEqual(leaked, [], "stored=false fields returned by fl=*")

    def test_ping(self):
        self.assertEqual(self.solr.get("/admin/ping").get("status"), "OK")

    def test_terms(self):
        r = self.solr.get("/terms", **{"terms.fl": self.cfg.unique_key, "terms.limit": 5})
        self.assertOk(r)
        self.assertTrue(r.get("terms", {}).get(self.cfg.unique_key), "no terms returned")

    def test_export_returns_every_document(self):
        key = self.cfg.unique_key
        r = self.solr.get("/export", q="*:*", sort="%s asc" % key, fl=key)
        docs = r.get("response", {}).get("docs")
        self.assertIsNotNone(docs, "no export response: %s" % str(r)[:600])
        self.assertEqual(len(docs), self.total, "/export must return all documents, not a page")

    def test_search_handlers_answer(self):
        failed = []
        for name, h in sorted(self.cfg.handlers.items()):
            cls = (h["class"] or "").replace("solr.", "")
            if name == "/export" or name.startswith("/update") or name.startswith("/analysis"):
                continue
            if cls == "SearchHandler":
                params = {"terms.fl": self.cfg.unique_key} if name == "/terms" else {"q": "*:*", "rows": 0}
            elif cls == "MoreLikeThisHandler":
                params = {"q": "%s:%s" % (self.cfg.unique_key, self.synthetic_ids[0])}
            else:
                continue
            r = self.solr.get(name, **params)
            if not self.solr.ok(r):
                failed.append("%s: %s" % (name, str(r)[:300]))
        self.assertEqual(failed, [])

    def test_commit_settings_match_file(self):
        r = self.solr.get("/config/updateHandler")
        uh = r["config"]["updateHandler"]

        def num(d, k):
            return int(d.get(k, -1) or -1)
        expected = (num(self.cfg.auto_commit, "maxTime"), num(self.cfg.auto_commit, "maxDocs"),
                    self.cfg.hard_commit_opens_searcher(), num(self.cfg.auto_soft_commit, "maxTime"))
        got = (uh["autoCommit"]["maxTime"], uh["autoCommit"]["maxDocs"],
               uh["autoCommit"]["openSearcher"], uh["autoSoftCommit"]["maxTime"])
        self.assertEqual(got, expected, "(autoCommit maxTime, maxDocs, openSearcher, autoSoftCommit maxTime)")

    def test_lucene_match_version(self):
        got = self.solr.get("/config")["config"]["luceneMatchVersion"]
        want = self.cfg.lucene_match_version
        self.assertTrue(got == want or got.startswith(want + "."), "%s vs %s in the file" % (got, want))

    def test_transaction_log_written(self):
        if not self.cfg.update_log:
            self.skipTest("no <updateLog> configured")
        code, out = ctx.solr.exec("ls", "/var/solr/data/%s/data/tlog" % self.core)
        self.assertTrue(code == 0 and out.strip(), "no transaction log files")
