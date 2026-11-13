#!/usr/bin/env python3
"""Copy the documents of a Solr 5.5 core to its Solr 9.9 counterpart over HTTP.

See README.md ("Copying data from Solr 5.5") for usage and for what cannot be copied.
Standard library only.
"""
import argparse
import fnmatch
import json
import os
import sys
import time
import urllib.error

sys.dont_write_bytecode = True
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tests"))

from lib import config as cfgmod  # noqa: E402
from lib.solr import Core  # noqa: E402

# Unstored fields whose indexed terms index back to themselves, so their values can be
# read from the source index: StrField (the term is the value) and analyzers that keep the
# whole value as one normalised token.
_WHOLE_VALUE_TOKENIZERS = {"solr.KeywordTokenizerFactory"}
_TERM_RECOVERABLE = {"fi-admin": {"year_filter"}}  # dateiso: the term is the 4-digit year

# Unstored fields the application fills from other fields of the same document.
# {core: {field: {django_ct: [stored fields joined into the value]}}}. An empty list means
# the application sends nothing for that document type. Document types not listed cannot
# be rebuilt and are reported. From fi-admin's templates/search/indexes/*/*_text.txt.
_REBUILD = {
    "fi-admin": {
        "text": {
            "main.resource": ["title", "abstract"],
            "events.event": ["title"],
            "multimedia.media": ["title"],
            "oer.oer": ["title"],
            "biblioref.referenceanalytic": [],
            "biblioref.referencesource": [],
        },
    },
}
_TYPE_FIELD = "django_ct"


class Fatal(Exception):
    pass


def as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


class Rules:
    """What to do with each field, derived from the core's schema.xml."""

    def __init__(self, core):
        self.core = core
        self.cfg = cfgmod.load(core)
        if self.cfg.errors:
            raise Fatal("; ".join(self.cfg.errors))
        self.key = self.cfg.unique_key
        self.rebuild = _REBUILD.get(core, {})
        # Stored copyField destinations: their stored values already include the copies.
        self.stored_dests = {}
        for source, dest in self.cfg.copy_fields:
            if self.cfg.effective(dest, "stored", True):
                self.stored_dests.setdefault(dest, []).append(source)

    def _is_copy_dest(self, name):
        return any(fnmatch.fnmatchcase(name, dest) for _, dest in self.cfg.copy_fields)

    def direct_unstored(self, name):
        """True for a field that is not stored and is not filled by copyField alone."""
        if self.cfg.resolve_field(name) is None or self.cfg.effective(name, "stored", True):
            return False
        return not self._is_copy_dest(name)

    def term_recoverable(self, name):
        if name in _TERM_RECOVERABLE.get(self.core, ()):
            return True
        if self.cfg.type_class(name) == "solr.StrField":
            return True
        field = self.cfg.resolve_field(name)
        classes = self.cfg.types.get(field.get("type"), {"classes": []})["classes"]
        tokenizers = [c for c in classes if "Tokenizer" in c]
        return bool(tokenizers) and set(tokenizers) <= _WHOLE_VALUE_TOKENIZERS

    def multi_valued(self, name):
        return self.cfg.effective(name, "multiValued", False)

    def transform(self, doc, recovered, stats):
        """Turn a document read from the source into the document to send to the target."""
        out = {k: v for k, v in doc.items() if k != "_version_"}
        for dest, sources in self.stored_dests.items():
            if dest not in out:
                continue
            present = [s for s in sources if s in doc]
            if not present:
                continue
            if not self.multi_valued(dest):
                del out[dest]  # single value: it can only be the copy
                continue
            values = [v for v in as_list(out[dest])]
            for s in present:
                for v in as_list(doc[s]):
                    for i, existing in enumerate(values):
                        if str(existing) == str(v):
                            del values[i]
                            break
            if values:
                out[dest] = values
            else:
                del out[dest]
        for field, by_type in self.rebuild.items():
            ct = doc.get(_TYPE_FIELD)
            if ct not in by_type:
                stats.setdefault("not_rebuilt", {}).setdefault(field, {}).setdefault(ct, 0)
                stats["not_rebuilt"][field][ct] += 1
                continue
            parts = [str(v) for f in by_type[ct] for v in as_list(doc.get(f))]
            if parts:
                out[field] = "\n".join(parts)
        for field, values in recovered.get(doc[self.key], {}).items():
            out[field] = values if self.multi_valued(field) else values[0]
        return out


def check(response, what):
    if not Core.ok(response):
        detail = response.get("error", {}).get("msg") if isinstance(response.get("error"), dict) else None
        raise Fatal("%s failed: %s" % (what, detail or json.dumps(response)[:500]))
    return response


def num_found(core, fqs):
    r = check(core.get("/select", q="*:*", rows=0, fq=fqs, facet="false", defType="lucene"), "count")
    return r["response"]["numFound"]


def facet_counts(core, field, fqs):
    r = check(core.get("/select", q="*:*", rows=0, fq=fqs, defType="lucene", facet="true",
                       **{"facet.field": field, "facet.limit": -1, "facet.mincount": 1,
                          "facet.sort": "index", "json.nl": "flat"}), "facet on " + field)
    flat = r["facet_counts"]["facet_fields"][field]
    return dict(zip(flat[0::2], flat[1::2]))


def cursor(core, key, rows, fqs, fl):
    """Yield every matching document, in pages, using a cursor."""
    mark = "*"
    while True:
        r = check(core.get("/select", q="*:*", fq=fqs, fl=fl, rows=rows, sort=key + " asc",
                           cursorMark=mark, facet="false", defType="lucene"), "read")
        docs = r["response"]["docs"]
        if docs:
            yield docs
        nxt = r.get("nextCursorMark")
        if not docs or nxt is None or nxt == mark:
            return
        mark = nxt


def preflight(source, rules):
    """Classify the unstored fields that actually exist in the source index."""
    r = check(source.get("/admin/luke", numTerms=0), "/admin/luke on the source")
    in_index = sorted(r.get("fields", {}))
    report = {"recover": [], "rebuild": [], "lost": []}
    for name in in_index:
        if not rules.direct_unstored(name):
            continue
        if name in rules.rebuild:
            report["rebuild"].append(name)
        elif rules.term_recoverable(name):
            report["recover"].append(name)
        else:
            report["lost"].append(name)
    return report


def print_preflight(report, rules):
    print("Unstored fields found in the source index (copyField-only fields are rebuilt by Solr):")
    if not any(report.values()):
        print("  none: every value comes back from stored fields")
    for name in report["recover"]:
        print("  %-28s recovered from its indexed terms" % name)
    for name in report["rebuild"]:
        print("  %-28s rebuilt from stored fields for: %s" % (
            name, ", ".join(sorted(rules.rebuild[name]))))
    for name in report["lost"]:
        print("  %-28s CANNOT BE COPIED (tokenized, not stored)" % name)
    if rules.stored_dests:
        print("Stored copyField destinations, copies removed before sending: %s"
              % ", ".join(sorted(rules.stored_dests)))


def recover_terms(source, rules, fields, fqs, rows):
    """{id: {field: [values]}} for unstored fields, read back from the indexed terms."""
    recovered = {}
    for field in fields:
        values = facet_counts(source, field, fqs)
        print("  %s: %d distinct values" % (field, len(values)), flush=True)
        for value in values:
            fq = fqs + ["{!term f=%s}%s" % (field, value)]
            for docs in cursor(source, rules.key, max(rows, 2000), fq, rules.key):
                for d in docs:
                    recovered.setdefault(d[rules.key], {}).setdefault(field, []).append(value)
    return recovered


def send(target, docs, key, failures):
    r = target.update_json(docs)
    if Core.ok(r):
        return len(docs)
    sent = 0
    for doc in docs:
        r = target.update_json([doc])
        if Core.ok(r):
            sent += 1
        else:
            msg = r.get("error", {}).get("msg") if isinstance(r.get("error"), dict) else json.dumps(r)[:300]
            failures.append({"id": doc.get(key), "error": msg})
    return sent


def verify(source, target, rules, fields, fqs, queries):
    """Compare counts between source and target. Returns the number of differences."""
    print("\nVerification (source vs target)")
    diffs = 0
    s, t = num_found(source, fqs), num_found(target, fqs)
    print("  %-34s %10s %10s  %s" % ("documents", s, t, "ok" if s == t else "DIFFERENT"))
    diffs += s != t
    names = list(dict.fromkeys(
        ([_TYPE_FIELD] if rules.cfg.resolve_field(_TYPE_FIELD) and _TYPE_FIELD in rules.cfg.fields else [])
        + rules.cfg.facet_fields() + list(fields)))
    for name in names:
        a, b = facet_counts(source, name, fqs), facet_counts(target, name, fqs)
        analyzed = rules.cfg.type_class(name) == "solr.TextField" and not rules.term_recoverable(name)
        if a == b:
            print("  %-34s %10d %10d  ok" % ("facet " + name, len(a), len(b)))
            continue
        changed = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
        note = "different (analyzed field: the analysis chain changed)" if analyzed else "DIFFERENT"
        diffs += not analyzed
        print("  %-34s %10d %10d  %s" % ("facet " + name, len(a), len(b), note))
        for k in changed[:5]:
            print("      %r: %s -> %s" % (k, a.get(k, 0), b.get(k, 0)))
        if len(changed) > 5:
            print("      ... %d more" % (len(changed) - 5))
    for q in queries:
        counts = []
        for core in (source, target):
            r = core.get("/select", q=q, rows=0, fq=fqs, facet="false")
            counts.append(r.get("response", {}).get("numFound", "error"))
        same = counts[0] == counts[1]
        diffs += not same
        print("  %-34s %10s %10s  %s" % ("query " + q[:28], counts[0], counts[1], "ok" if same else "DIFFERENT"))
    return diffs


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("core", choices=["fi-admin", "best-practices", "relatos-experiencia"],
                    help="core whose schema.xml in this repository describes both indexes")
    ap.add_argument("--source", required=True, help="Solr 5.5 core URL, e.g. http://old:8983/solr/fi-admin")
    ap.add_argument("--target", required=True, help="Solr 9.9 core URL")
    ap.add_argument("--rows", type=int, default=500, help="documents per batch (default 500)")
    ap.add_argument("--fq", action="append", default=[], help="copy only matching documents (repeatable)")
    ap.add_argument("--query", action="append", default=[],
                    help="query whose result count is compared in the verification (repeatable)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report on the source and transform one batch; write nothing")
    ap.add_argument("--verify-only", action="store_true", help="only compare source and target")
    ap.add_argument("--accept-loss", action="store_true",
                    help="copy even if a field cannot be copied or rebuilt")
    ap.add_argument("--failed-file", help="where to write rejected documents' ids "
                                          "(default copy-<core>-failed.jsonl)")
    args = ap.parse_args()

    source, target = Core(args.source.rstrip("/")), Core(args.target.rstrip("/"))
    if source.base == target.base:
        raise Fatal("source and target are the same URL")
    rules = Rules(args.core)
    report = preflight(source, rules)
    recover = report["recover"]

    if args.verify_only:
        return 1 if verify(source, target, rules, recover, args.fq, args.query) else 0

    total = num_found(source, args.fq)
    print("Source: %s (%d documents to copy)" % (source.base, total))
    if not args.dry_run:
        print("Target: %s (%d documents now)" % (target.base, num_found(target, [])))
    print_preflight(report, rules)
    if report["lost"] and not (args.accept_loss or args.dry_run):
        raise Fatal("the fields marked CANNOT BE COPIED hold data; reindex from the application, "
                    "or pass --accept-loss to copy without them")

    recovered = {}
    if recover and not args.dry_run:
        print("Reading unstored values from the indexed terms:")
        recovered = recover_terms(source, rules, recover, args.fq, args.rows)

    stats, failures, read, sent, started = {}, [], 0, 0, time.time()
    for docs in cursor(source, rules.key, args.rows, args.fq, "*"):
        batch = [rules.transform(d, recovered, stats) for d in docs]
        read += len(docs)
        if args.dry_run:
            print("\nDry run: first document as it would be sent:")
            print(json.dumps(batch[0], ensure_ascii=False, indent=1)[:3000])
            break
        sent += send(target, batch, rules.key, failures)
        print("\r  copied %d / %d" % (read, total), end="", flush=True)
    if args.dry_run:
        print("\nNothing was written (%d documents transformed)." % read)
        return 0
    print()
    check(target.commit(), "commit on the target")
    print("Sent %d of %d documents in %.0f s." % (sent, read, time.time() - started))

    for field, by_type in stats.get("not_rebuilt", {}).items():
        print("'%s' was not rebuilt for these document types (reindex them from the application):" % field)
        for ct, n in sorted(by_type.items(), key=lambda kv: str(kv[0])):
            print("  %-34s %d documents" % (ct, n))
    if failures:
        path = args.failed_file or "copy-%s-failed.jsonl" % args.core
        with open(path, "w", encoding="utf-8") as f:
            for item in failures:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        print("%d documents were rejected by the target; see %s" % (len(failures), path))
    diffs = verify(source, target, rules, recover, args.fq, args.query)
    return 1 if failures or diffs else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Fatal as e:
        print("error: %s" % e, file=sys.stderr)
        sys.exit(2)
    except (urllib.error.URLError, OSError) as e:
        print("error: cannot reach Solr: %s" % e, file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        sys.exit(130)
