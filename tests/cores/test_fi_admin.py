"""Tests for the fi-admin core."""
from lib import base

CORE = "fi-admin"


class Static(base.StaticChecks):
    core = CORE


class Load(base.LoadChecks):
    core = CORE


class Visibility(base.CommitVisibility):
    core = CORE


class Generic(base.GenericLive):
    core = CORE


# Spaced text, because english_title is copied to tw: one 40,000-character token would be
# rejected there as an immense term, which is not what this checks.
LONG = ("palavra " * 5000).strip()
STORED_ONLY_STRINGS = ["link", "english_title", "reference_source", "time_period_textual", "contact_email"]
MASKS = ["main.resource.1", "multimedia.media.1"]   # documents with descriptor ^d8569 (Masks)


class Specific(base.LiveTest):
    """Checks from the 2026-11-10 conversion and its review. One document per django_ct family.

    DeCS expectations use descriptor ^d8569 (Masks / Máscaras / Mascarillas / Masques,
    category E07.325.877.500) and the plain term Malaria, as found in the DeCS index.
    """
    core = CORE

    @classmethod
    def prepare(cls):
        cls.docs = base.fixture(CORE)
        cls.reindex(cls.docs)

    def ids(self, q, **params):
        return sorted(self.solr.ids(q, **params))

    def test_document_count(self):
        self.assertEqual(self.nf("*:*"), 12)

    # default field and operator
    def test_default_field_and_operator(self):
        self.assertEqual(self.ids("malaria vivax"), ["main.resource.1"])
        self.assertEqual(self.nf("malaria zebra"), 0)

    def test_accents_and_hyphens(self):
        both = ["main.resource.1", "title.title.1"]
        self.assertEqual(self.ids("saude publica"), both)
        self.assertEqual(self.ids("saúde-pública"), both)
        self.assertEqual(self.ids("covid-19"), ["main.resource.2"])

    def test_query_handler_and(self):
        self.assertEqual(self.nf("title:(saude publica)", handler="/query"), 2)
        self.assertEqual(self.nf("title:(saude zebra)", handler="/query"), 0)

    # filters as FI-Admin sends them
    def test_fq_status_and_django_ct(self):
        self.assertEqual(self.ids("*:*", fq="(status:1 AND django_ct:main.resource)"), ["main.resource.1"])
        self.assertEqual(self.ids("*:*", fq="status:0"), ["main.resource.2"])

    def test_fq_django_ct_wildcard(self):
        self.assertEqual(self.ids("*:*", fq="django_ct:title.title*"), ["title.title.1", "title.titlevariance.1"])

    # facets
    def test_thirty_one_facets(self):
        r = self.solr.select("*:*", rows=0, **{"json.nl": "map"})
        facets = r["facet_counts"]["facet_fields"]
        self.assertEqual(len(facets), 31)
        self.assertEqual(facets["status"], {"1": 11, "0": 1})

    def test_per_field_facet_limit(self):
        r = self.solr.select("*:*", rows=0, **{"json.nl": "map", "f.type.facet.limit": 2})
        self.assertEqual(len(r["facet_counts"]["facet_fields"]["type"]), 2)

    def test_facets_on_text_fields(self):
        """publication_year and descriptor_filter are TextFields: faceting works by uninversion."""
        r = self.solr.select("*:*", rows=0, **{"json.nl": "map",
                                               "facet.field": ["publication_year", "descriptor_filter"]})
        facets = r["facet_counts"]["facet_fields"]
        self.assertEqual(facets["publication_year"], {"2019": 1, "2020": 1, "2021": 1, "2023": 1})
        self.assertEqual(facets["descriptor_filter"], {"^d8569": 3}, "bare descriptor codes, qualifier dropped")

    # sorting and dates
    def test_sort_title_ignores_case_and_accents(self):
        ids = ["events.event.1", "events.event.2", "title.titlevariance.1", "main.resource.2", "main.resource.1"]
        got = self.solr.ids("id:(%s)" % " ".join(ids), sort="title_sort asc", **{"q.op": "OR"})
        # abacate, Árvore, banana, Congresso, zebra
        self.assertEqual(got, ["title.titlevariance.1", "main.resource.1", "events.event.2",
                               "events.event.1", "main.resource.2"])

    def test_sort_on_status(self):
        self.assertEqual(self.solr.ids("*:*", sort="status asc", rows=1), ["main.resource.2"])

    def test_sort_on_date(self):
        self.assertEqual(self.solr.ids("django_ct:events.event", sort="start_date desc"),
                         ["events.event.1", "events.event.2"])

    def test_date_range(self):
        self.assertEqual(self.ids("start_date:[2022-01-01T00:00:00Z TO 2023-12-31T23:59:59Z]"), ["events.event.1"])

    def test_year_copied_from_date(self):
        self.assertEqual(self.ids("publication_year:2023"), ["events.event.1"])

    # DeCS expansion (needs the analyzer jar and the DeCS index)
    def test_decs_translation_in_default_field(self):
        """tw expands precoded descriptors (^dNNNN) into their terms in every language."""
        self.assertEqual(self.ids("mascarillas"), MASKS)
        self.assertEqual(self.ids("masques"), MASKS)

    def test_decs_translation_in_descriptor(self):
        self.assertEqual(self.ids("descriptor:masks"), MASKS)

    def test_decs_category_code(self):
        self.assertEqual(self.ids('descriptor:"e07.325.877.500"'), MASKS)
        self.assertEqual(self.ids("E07.325.877.500"), MASKS)

    def test_decs_qualifier(self):
        self.assertEqual(self.ids('descriptor:"mascaras/di"'), ["multimedia.media.1"])
        self.assertEqual(self.ids('mj:"masks/diagnosis"'), ["biblioref.reference.1"])

    def test_decs_synonym_of_plain_term(self):
        """mh holds the plain term Malaria: synonyms match in mh, but tw expands only precoded terms."""
        self.assertEqual(self.ids("mh:paludismo"), ["biblioref.reference.1"])
        self.assertEqual(self.ids('mh:"plasmodium infections"'), ["biblioref.reference.1"])
        self.assertEqual(self.nf("paludismo"), 0)

    def test_descriptor_filter_code(self):
        self.assertEqual(self.ids('descriptor_filter:"^d8569"'), sorted(MASKS + ["biblioref.reference.1"]))

    # dynamic and unstored fields
    def test_dynamic_fields(self):
        self.assertEqual(self.ids("collection_x:abc"), ["main.resource.1"])
        self.assertEqual(self.ids("campo_novo:dinamico"), ["main.resource.1"])

    def test_copy_targets_searchable(self):
        self.assertEqual(self.ids('short_title:"Rev Saude Publica"'), ["title.title.1"])
        self.assertEqual(self.ids("media_type_filter:video"), ["multimedia.media.1"])
        self.assertEqual(self.ids('media_collection_filter:"Coleção Saúde"'), ["multimedia.media.1"])

    def test_thesaurus_fields(self):
        self.assertEqual(self.ids('ths_exact_term:"máscaras"'), ["thesaurus.identifierdesc.1"])
        self.assertEqual(self.ids("ths_decs_code:008569"), ["thesaurus.identifierdesc.1"])

    def test_fl_star_hides_unstored_fields(self):
        docs = {d["id"]: d for d in self.solr.select("*:*", fl="*", rows=50)["response"]["docs"]}
        self.assertEqual(docs["main.resource.1"]["campo_novo"], ["valor dinamico"])
        for doc_id, hidden in (("main.resource.1", ["collection_x", "tw", "title_sort", "descriptor_filter"]),
                               ("multimedia.media.1", ["media_type_filter", "media_collection_filter"]),
                               ("title.title.1", ["short_title"]),
                               ("thesaurus.identifierdesc.1", ["ths_exact_term", "ths_termall"])):
            for field in hidden:
                self.assertNotIn(field, docs[doc_id], "%s returned for %s" % (field, doc_id))

    def test_long_values_in_stored_only_strings(self):
        """indexed=false strings set docValues=false, so values over 32766 bytes are accepted."""
        self.assertGreater(len(LONG), 32766)
        doc = {"id": "zz-long", "django_ct": "main.resource", "status": 1}
        doc.update({f: ([LONG] if f == "link" else LONG) for f in STORED_ONLY_STRINGS})
        try:
            self.assertOk(self.solr.update_json([doc], commit=True))
            got = self.solr.select("id:zz-long", fl=",".join(STORED_ONLY_STRINGS))["response"]["docs"][0]
            for f in STORED_ONLY_STRINGS:
                value = got[f][0] if isinstance(got[f], list) else got[f]
                self.assertEqual(len(value), len(LONG), f)
        finally:
            self.solr.delete_id("zz-long")

    # handlers
    def test_related(self):
        self.assertOk(self.solr.get("/related", q="id:main.resource.1"))

    def test_terms_on_default_field(self):
        r = self.solr.get("/terms", **{"terms.fl": "tw", "terms.prefix": "masc"})
        self.assertOk(r)
        self.assertIn("mascarillas", r["terms"]["tw"])

    def test_export_with_docvalues_fields(self):
        r = self.solr.get("/export", q="*:*", sort="id asc", fl="id,django_ct,status")
        self.assertEqual(len(r["response"]["docs"]), 12)
