"""Tests for the relatos-experiencia core."""
from lib import base

CORE = "relatos-experiencia"


class Static(base.StaticChecks):
    core = CORE


class Load(base.LoadChecks):
    core = CORE


class Visibility(base.CommitVisibility):
    core = CORE


class Generic(base.GenericLive):
    core = CORE


XML_DOC = ('<add><doc><field name="id">3</field><field name="title">Documento xml teste</field>'
           '<field name="issue">questao</field><field name="status">concluido</field>'
           '<field name="country">Chile</field><field name="thematic_area">saude</field></doc></add>')


class Specific(base.LiveTest):
    """The checks of the 2026-11-10 conversion smoke test (docs 1-2 by JSON, doc 3 by XML).

    Core load, the explicit-commit visibility check and the generic handler checks of that
    script are covered by Load, Visibility and Generic.
    """
    core = CORE

    @classmethod
    def prepare(cls):
        cls.solr.delete_all()
        cls.json_response = cls.solr.update_json(base.fixture(CORE))
        cls.xml_response = cls.solr.update_xml(XML_DOC)
        cls.solr.commit()

    def doc1(self):
        return self.solr.select("id:1", fl="*")["response"]["docs"][0]

    # indexing
    def test_json_update(self):
        self.assertOk(self.json_response)

    def test_xml_update(self):
        self.assertOk(self.xml_response)

    def test_all_documents_visible_after_commit(self):
        self.assertEqual(self.nf("*:*"), 3)

    # default field tw = title + notes + description + fulltext + issue
    def test_tw_has_title(self):
        self.assertEqual(self.nf("experiencia"), 1)

    def test_tw_has_notes(self):
        self.assertEqual(self.nf("notaunica"), 1)

    def test_tw_has_description(self):
        self.assertEqual(self.nf("descunica"), 1)

    def test_tw_has_fulltext(self):
        self.assertEqual(self.nf("fulltextunica"), 1)

    def test_tw_has_issue(self):
        self.assertEqual(self.nf("issueunica"), 1)

    def test_tw_excludes_other_fields(self):
        self.assertEqual(self.nf("objetivounico"), 0)

    # default operator
    def test_and_both_terms_present(self):
        self.assertEqual(self.nf("projeto escolar"), 1)

    def test_and_one_term_missing(self):
        self.assertEqual(self.nf("projeto inexistente"), 0)

    def test_explicit_or(self):
        self.assertEqual(self.nf("escolar OR descunica"), 2)

    # /query keeps df=text from the Solr 5.5 config, so it needs an explicit field
    def test_query_handler_and_hit(self):
        self.assertEqual(self.nf("description:(projeto escolar)", handler="/query"), 1)

    def test_query_handler_and_miss(self):
        self.assertEqual(self.nf("description:(projeto inexistente)", handler="/query"), 0)

    def test_query_handler_df_is_text(self):
        r = self.solr.get("/query", q="x", echoParams="all")
        self.assertEqual(r["responseHeader"]["params"]["df"], "text")
        self.assertEqual(self.nf("projeto", handler="/query"), 0, "bare /query terms do not search tw")

    # text analysis
    def test_accent_insensitive(self):
        self.assertEqual(self.nf("saude"), 1)

    def test_hyphenated_term(self):
        self.assertEqual(self.nf("covid-19"), 1)

    def test_hyphenated_term_part(self):
        self.assertEqual(self.nf("covid"), 1)

    def test_phrase(self):
        self.assertEqual(self.nf('"saude publica"'), 1)

    # fields outside tw
    def test_declared_field_query(self):
        self.assertEqual(self.nf("objectives:objetivounico"), 1)

    def test_keywords_field_query(self):
        self.assertEqual(self.nf("keywords:vacina"), 1)

    def test_catch_all_dynamic_field(self):
        self.assertEqual(self.nf("campo_extra:valorextra"), 1)

    # filters
    def test_fq_status(self):
        self.assertEqual(self.nf("*:*", fq='status:"concluido"'), 2)

    def test_fq_country(self):
        self.assertEqual(self.nf("*:*", fq='country:"Brasil"'), 1)

    def test_fq_thematic_area(self):
        self.assertEqual(self.nf("*:*", fq='thematic_area:"saude"'), 2)

    def test_fq_combined(self):
        self.assertEqual(self.nf("*:*", fq='status:"concluido" AND country:"Chile"'), 1)

    # facets
    def test_four_facets(self):
        r = self.solr.select("*:*", rows=0)
        self.assertEqual(sorted(r["facet_counts"]["facet_fields"]),
                         ["collection", "country", "population_group", "thematic_area"])

    def test_facet_counts(self):
        r = self.solr.select("*:*", rows=0, **{"json.nl": "map"})
        self.assertEqual(r["facet_counts"]["facet_fields"]["thematic_area"], {"educacao": 2, "saude": 2})

    # stored values
    def test_fl_star_omits_tw(self):
        self.assertNotIn("tw", self.doc1())

    def test_date_string_returned(self):
        self.assertEqual(self.doc1()["start_date"], "2020-01-01")

    def test_long_value_in_stored_only_string(self):
        """other_date: string, indexed=false, docValues=false. Over Lucene's 32766-byte limit."""
        self.assertEqual(len(self.doc1()["other_date"]), len(base.BIG))

    def test_long_value_in_stored_only_text(self):
        self.assertEqual(len(self.doc1()["lessons_learned"]), len(base.BIG))

    def test_status_returned(self):
        self.assertEqual(self.doc1()["status"], "concluido")

    def test_sort_on_string_field(self):
        self.assertEqual(self.solr.ids("*:*", sort="country asc"), ["2", "1", "3"])

    # handlers
    def test_related(self):
        self.assertOk(self.solr.get("/related", q="id:1"))

    def test_terms(self):
        self.assertOk(self.solr.get("/terms", **{"terms.fl": "country"}))

    def test_export(self):
        r = self.solr.get("/export", q="*:*", sort="id asc", fl="id,country")
        self.assertEqual(len(r["response"]["docs"]), 3)

    def test_ping(self):
        self.assertEqual(self.solr.get("/admin/ping")["status"], "OK")

    # settings
    def test_commit_policy(self):
        uh = self.solr.get("/config/updateHandler")["config"]["updateHandler"]
        self.assertEqual([uh["autoCommit"]["maxTime"], uh["autoCommit"]["openSearcher"],
                          uh["autoSoftCommit"]["maxTime"]], [15000, False, -1])

    def test_lucene_match_version(self):
        self.assertEqual(self.solr.get("/config")["config"]["luceneMatchVersion"], "9.12.0")
