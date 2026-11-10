"""Tests for the best-practices core."""
from lib import base

CORE = "best-practices"


class Static(base.StaticChecks):
    core = CORE


class Load(base.LoadChecks):
    core = CORE


class Visibility(base.CommitVisibility):
    core = CORE


class Generic(base.GenericLive):
    core = CORE


class Specific(base.LiveTest):
    """Checks from the 2026-11-10 conversion and its review, on the three fixture documents."""
    core = CORE

    @classmethod
    def prepare(cls):
        cls.docs = base.fixture(CORE)
        cls.reindex(cls.docs)

    def doc(self, doc_id):
        return self.solr.select('id:"%s"' % doc_id, fl="*")["response"]["docs"][0]

    def test_document_count(self):
        self.assertEqual(self.nf("*:*"), 3)

    # default field tw = title + introduction
    def test_tw_has_title_and_introduction(self):
        self.assertEqual(sorted(self.solr.ids("vacinacao")), ["bp.1", "bp.3"])
        self.assertEqual(self.solr.ids("saneamento"), ["bp.2"])

    def test_tw_excludes_other_fields(self):
        self.assertEqual(self.nf("mortalidade"), 0)
        self.assertEqual(self.nf("objectives:mortalidade"), 1)
        self.assertEqual(self.nf("keywords:imunizacao"), 1)

    def test_default_operator_and(self):
        self.assertEqual(self.solr.ids("vacinacao escolar"), ["bp.3"])
        self.assertEqual(self.nf("vacinacao rural"), 0)

    def test_boolean_operators(self):
        self.assertEqual(self.nf("vacinacao OR rural"), 3)
        self.assertEqual(self.solr.ids("vacinacao NOT escolar"), ["bp.1"])
        self.assertEqual(self.solr.ids("vacinacao -infantil"), ["bp.3"])

    # /query keeps df=text from the Solr 5.5 config
    def test_query_handler(self):
        self.assertEqual(self.nf("vacinacao", handler="/query"), 0, "bare /query terms do not search tw")
        self.assertEqual(self.nf("title:(vacinacao escolar)", handler="/query"), 1)
        self.assertEqual(self.nf("title:(vacinacao rural)", handler="/query"), 0)

    # text analysis
    def test_accents(self):
        self.assertEqual(self.solr.ids("agua"), ["bp.2"])
        self.assertEqual(sorted(self.solr.ids("saude")), ["bp.1", "bp.3"])

    def test_hyphenated_terms(self):
        self.assertEqual(self.solr.ids("saude-publica"), ["bp.1"])
        self.assertEqual(self.solr.ids("covid-19"), ["bp.1"])

    def test_phrase(self):
        self.assertEqual(self.solr.ids('"agua potavel"'), ["bp.2"])
        self.assertEqual(self.nf('"potavel agua"'), 0)

    def test_wildcard_and_prefix(self):
        self.assertEqual(sorted(self.solr.ids("vacin*")), ["bp.1", "bp.3"])
        self.assertEqual(self.solr.ids("ab?cate"), ["bp.3"])

    def test_edismax_with_qf(self):
        self.assertEqual(self.solr.ids("imunizacao", defType="edismax", qf="keywords title"), ["bp.1"])

    def test_paging(self):
        self.assertEqual(self.solr.ids("*:*", sort="id asc", rows=2, start=2), ["bp.3"])

    def test_highlighting(self):
        r = self.solr.select("saneamento", hl="true", **{"hl.fl": "introduction"})
        self.assertIn("<em>", r["highlighting"]["bp.2"]["introduction"][0])

    # facets and filters
    def test_eleven_facets_with_counts(self):
        r = self.solr.select("*:*", rows=0, **{"json.nl": "map"})
        facets = r["facet_counts"]["facet_fields"]
        self.assertEqual(sorted(facets), sorted(
            ["country", "subregion", "target", "type", "intervention", "population_group",
             "institution", "stakeholder", "outcomes", "call", "is_private"]))
        self.assertEqual(facets["country"], {"Brasil": 2, "Argentina": 1, "Peru": 1})
        self.assertEqual(facets["is_private"], {"false": 2, "true": 1})

    def test_per_field_facet_limit(self):
        r = self.solr.select("*:*", rows=0, **{"json.nl": "map", "f.country.facet.limit": 1})
        self.assertEqual(r["facet_counts"]["facet_fields"]["country"], {"Brasil": 2})

    def test_tagged_and_excluded_facet(self):
        r = self.solr.select("*:*", rows=0, fq='{!tag=c}country:"Peru"',
                             **{"json.nl": "map", "facet.field": "{!ex=c}country"})
        self.assertEqual(r["response"]["numFound"], 1)
        self.assertEqual(r["facet_counts"]["facet_fields"]["country"]["Brasil"], 2)

    def test_fq_on_facet_fields(self):
        self.assertEqual(self.nf("*:*", fq='country:"Brasil"'), 2)
        self.assertEqual(self.nf("*:*", fq='is_private:"false"'), 2)
        self.assertEqual(self.nf("*:*", fq='country:"Brasil" AND type:"bp" AND call:"2022"'), 1)

    # stored values
    def test_long_value_in_stored_only_text(self):
        expected = len(self.docs[0]["outcome_information"])
        self.assertGreater(expected, 32766)
        self.assertEqual(len(self.doc("bp.1")["outcome_information"]), expected)

    def test_status_is_returned_but_not_searchable(self):
        """status is int, indexed=false, docValues=false: as in the Solr 5.5 schema."""
        self.assertEqual(self.doc("bp.1")["status"], 1)
        self.assertEqual(self.nf("*:*", fq="status:1"), 0)

    def test_fl_star(self):
        d = self.doc("bp.1")
        self.assertNotIn("tw", d)
        self.assertEqual(d["start_date"], "2020-01-01")
        self.assertEqual(d["country"], ["Brasil", "Argentina"])

    def test_catch_all_dynamic_field(self):
        self.assertEqual(self.solr.ids("campo_extra:dinamico"), ["bp.1"])

    def test_sort_on_string_field(self):
        self.assertEqual(self.solr.ids("*:*", sort="call desc,id asc"), ["bp.2", "bp.3", "bp.1"])

    # updates
    def test_delete_by_id(self):
        try:
            self.assertOk(self.solr.delete_id("bp.3"))
            self.assertEqual(self.nf("*:*"), 2)
        finally:
            self.solr.update_json([self.docs[2]], commit=True)
        self.assertEqual(self.nf("*:*"), 3)

    # handlers and response writers
    def test_related(self):
        self.assertOk(self.solr.get("/related", q='id:"bp.1"'))

    def test_response_writers(self):
        for wt, start in (("xml", b"<?xml"), ("php", b"array("), ("phps", b"a:")):
            status, body = self.solr.raw("/select", q="*:*", rows=1, wt=wt)
            self.assertEqual(status, 200, wt)
            self.assertTrue(body.lstrip().startswith(start), "wt=%s starts with %r" % (wt, body[:20]))
