"""Known problems in the configurations, tracked so the run stays green until they are fixed.

KNOWN[core]["<Class>.<test method>"] = reason
    The test is an expected failure. Once the configuration is fixed the test passes
    unexpectedly, the run turns red, and the entry must be removed.

KNOWN_LOG_WARNINGS[core][<substring of the log line>] = reason
    WARN lines Solr prints when loading the core that Load.test_no_errors_or_warnings_in_log
    tolerates. An entry that is no longer logged also turns the run red.

`portal` and `api-metrics` were not part of the Solr 5.5 -> 9.9 conversions of 2026-11-10.
The same items were fixed in fi-admin, best-practices and relatos-experiencia; see
.ai/logs/2026-11-10-fi-admin-solr-9-config-conversion.md, "Findings".
"""

_EXPORT = ("explicit Solr 5 /export handler shadows Solr 9's implicit one: "
           "/export answers as a plain search limited to rows=10")
_JMX = "<jmx/> is no longer supported in Solr 9 (ignored with a warning)"
_STREAMING = "enableRemoteStreaming in <requestParsers> is ignored by Solr 9 (system property instead)"

KNOWN = {
    "portal": {
        "Static.test_no_explicit_export_handler": _EXPORT,
        "Generic.test_export_returns_every_document": _EXPORT,
        "Static.test_no_jmx_element": _JMX,
        "Static.test_no_enable_remote_streaming_attribute": _STREAMING,
        "Static.test_no_lib_directives":
            '<lib dir="../lib"/> is ignored: <lib/> is disabled by default since Solr 9.8; '
            "the analyzer jar is picked up from <instanceDir>/lib",
    },
    "api-metrics": {
        "Static.test_no_explicit_export_handler": _EXPORT,
        "Generic.test_export_returns_every_document": _EXPORT,
        "Static.test_no_jmx_element": _JMX,
        "Static.test_no_enable_remote_streaming_attribute": _STREAMING,
        "Static.test_no_trie_fields":
            "Trie field types still load on Solr 9 with a deprecation warning; removed in Solr 10",
        "Static.test_no_word_delimiter_filter":
            "WordDelimiterFilterFactory is deprecated; WordDelimiterGraphFilterFactory replaces it",
        "Static.test_no_legacy_schema_elements":
            "<solrQueryParser> is ignored since Solr 7 (default operator comes from q.op)",
        "Static.test_no_num_version_buckets": "numVersionBuckets in <updateLog> is obsolete",
    },
}

KNOWN_LOG_WARNINGS = {
    "portal": {
        "<lib/> usage is disabled": "see Static.test_no_lib_directives",
        "<jmx> is no longer supported": _JMX,
        "Ignored deprecated enableRemoteStreaming": _STREAMING,
        "Ignored deprecated enableStreamBody": "enableStreamBody is ignored by Solr 9 (system property instead)",
        "The vector dimension 4096": "the `vector` field exceeds Lucene's default 1024 dimensions; "
                                     "Solr accepts it and warns",
    },
    "api-metrics": {
        "<jmx> is no longer supported": _JMX,
        "Ignored deprecated enableRemoteStreaming": _STREAMING,
        "deprecated plugin/analysis class [solr.Trie": "see Static.test_no_trie_fields",
        "deprecated plugin/analysis class [solr.WordDelimiterFilterFactory]":
            "see Static.test_no_word_delimiter_filter",
        "numVersionBuckets is obsolete": "see Static.test_no_num_version_buckets",
    },
}
