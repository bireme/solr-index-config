"""Parse a core's schema.xml and solrconfig.xml into a plain model.

Only what the tests need is modelled. Standard library only.
"""
import fnmatch
import os
import re
import xml.etree.ElementTree as ET

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CORES = ["api-metrics", "best-practices", "fi-admin", "portal", "relatos-experiencia"]

_PROP = re.compile(r"\$\{[^:}]+:([^}]*)\}")


def _subst(value):
    """Resolve ${property:default} to its default, as Solr does with no property set."""
    return _PROP.sub(lambda m: m.group(1), value) if value else value


def _bool(value, default):
    return default if value is None else value.strip().lower() == "true"


class Config:
    def __init__(self, core, schema_text, solrconfig_text):
        self.core = core
        self.schema_text = schema_text
        self.solrconfig_text = solrconfig_text
        self.errors = []          # XML parse errors, if any
        self.types = {}           # name -> {"attrs": {...}, "classes": [...]}
        self.fields = {}          # name -> attrs
        self.dynamic_fields = {}  # pattern -> attrs
        self.copy_fields = []     # [(source, dest)]
        self.unique_key = None
        self.schema_version = None
        self.legacy_schema_elements = []
        self.lucene_match_version = None
        self.handlers = {}        # name -> {"class": ..., "defaults": {k: [v]}, "invariants": {...}}
        self.init_params = []     # [(paths, {k: [v]})]
        self.auto_commit = {}
        self.auto_soft_commit = {}
        self.caches = {}          # tag or name -> class (None when not given)
        self.jmx = False
        self.remote_streaming_attr = False
        self.libs = []
        self.update_log = False
        self.num_version_buckets = False
        self._parse_schema()
        self._parse_solrconfig()

    # ------------------------------------------------------------------ schema
    def _parse_schema(self):
        try:
            root = ET.fromstring(self.schema_text)
        except ET.ParseError as e:
            self.errors.append("schema.xml: %s" % e)
            return
        self.schema_version = root.get("version")
        for el in root.iter():
            tag = el.tag
            if tag in ("fieldType", "fieldtype"):
                classes = [c.get("class") for c in el.iter() if c is not el and c.get("class")]
                self.types[el.get("name")] = {"attrs": dict(el.attrib), "classes": classes}
            elif tag == "field":
                self.fields[el.get("name")] = dict(el.attrib)
            elif tag == "dynamicField":
                self.dynamic_fields[el.get("name")] = dict(el.attrib)
            elif tag == "copyField":
                self.copy_fields.append((el.get("source"), el.get("dest")))
            elif tag == "uniqueKey":
                self.unique_key = (el.text or "").strip()
            elif tag in ("defaultSearchField", "solrQueryParser"):
                self.legacy_schema_elements.append(tag)

    def resolve_field(self, name):
        """Attributes of the field or of the dynamicField that would match (None if neither)."""
        if name in self.fields:
            return self.fields[name]
        best = None
        for pattern, attrs in self.dynamic_fields.items():
            if fnmatch.fnmatchcase(name, pattern):
                if best is None or len(pattern) > len(best[0]):
                    best = (pattern, attrs)
        return best[1] if best else None

    def effective(self, name, attr, default):
        """Boolean attribute of a field, falling back to its type, then to `default`."""
        f = self.resolve_field(name)
        if f is None:
            return default
        if attr in f:
            return _bool(f[attr], default)
        t = self.types.get(f.get("type"), {"attrs": {}})["attrs"]
        return _bool(t.get(attr), default)

    def type_class(self, name):
        f = self.resolve_field(name)
        if not f:
            return None
        return self.types.get(f.get("type"), {"attrs": {}})["attrs"].get("class")

    def has_doc_values(self, name):
        return self.effective(name, "docValues", False)

    def copy_sources(self, dest):
        return [s for s, d in self.copy_fields if d == dest]

    # -------------------------------------------------------------- solrconfig
    @staticmethod
    def _named_list(el):
        out = {}
        if el is None:
            return out
        for child in el:
            if child.get("name"):
                out.setdefault(child.get("name"), []).append(_subst((child.text or "").strip()))
        return out

    def _parse_solrconfig(self):
        try:
            root = ET.fromstring(self.solrconfig_text)
        except ET.ParseError as e:
            self.errors.append("solrconfig.xml: %s" % e)
            return
        self.lucene_match_version = _subst((root.findtext("luceneMatchVersion") or "").strip())
        for h in root.iter("requestHandler"):
            entry = {"class": h.get("class")}
            for kind in ("defaults", "invariants", "appends"):
                entry[kind] = {}
            for lst in h.findall("lst"):
                if lst.get("name") in entry:
                    entry[lst.get("name")] = self._named_list(lst)
            self.handlers[h.get("name")] = entry
        for ip in root.iter("initParams"):
            for lst in ip.findall("lst"):
                if lst.get("name") == "defaults":
                    self.init_params.append((ip.get("path", "").split(","), self._named_list(lst)))
        uh = root.find("updateHandler")
        if uh is not None:
            ul = uh.find("updateLog")
            self.update_log = ul is not None
            self.num_version_buckets = ul is not None and any(
                c.get("name") == "numVersionBuckets" for c in ul)
            for tag, target in (("autoCommit", self.auto_commit), ("autoSoftCommit", self.auto_soft_commit)):
                el = uh.find(tag)
                if el is not None:
                    for child in el:
                        target[child.tag] = _subst((child.text or "").strip())
        q = root.find("query")
        if q is not None:
            for el in q:
                if el.tag.endswith("Cache") or el.tag == "cache":
                    self.caches[el.get("name") or el.tag] = el.get("class")
        self.jmx = root.find("jmx") is not None
        rp = root.find("requestDispatcher/requestParsers")
        self.remote_streaming_attr = rp is not None and rp.get("enableRemoteStreaming") is not None
        self.libs = [dict(l.attrib) for l in root.iter("lib")]

    def handler_default(self, handler, key):
        """Values of a default param: the handler's own defaults, else matching initParams."""
        h = self.handlers.get(handler)
        if h and key in h["defaults"]:
            return h["defaults"][key]
        for paths, defaults in self.init_params:
            if handler in paths and key in defaults:
                return defaults[key]
        return []

    def df(self, handler="/select"):
        v = self.handler_default(handler, "df")
        return v[0] if v else None

    def q_op(self, handler="/select"):
        v = self.handler_default(handler, "q.op")
        return v[0].upper() if v else "OR"

    def facet_fields(self, handler="/select"):
        return self.handler_default(handler, "facet.field")

    def soft_commit_off(self):
        return int(self.auto_soft_commit.get("maxTime", "-1") or -1) <= 0

    def hard_commit_opens_searcher(self):
        return _bool(self.auto_commit.get("openSearcher"), True)


def conf_paths(core):
    d = os.path.join(REPO, core, "conf")
    return os.path.join(d, "schema.xml"), os.path.join(d, "solrconfig.xml")


def load(core):
    schema, solrconfig = conf_paths(core)
    with open(schema, encoding="utf-8") as f:
        s = f.read()
    with open(solrconfig, encoding="utf-8") as f:
        c = f.read()
    return Config(core, s, c)
