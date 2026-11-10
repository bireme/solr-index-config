"""Compare the working-tree configuration of a core with the one at a git ref."""
import subprocess

from .config import CORES, REPO, Config


def _git(*args):
    return subprocess.run(["git", "-C", REPO] + list(args), capture_output=True, text=True)


def resolve_ref(requested=None):
    """The ref to compare with: the requested one, else origin/main, else main. None if none exists."""
    for ref in ([requested] if requested else ["origin/main", "main"]):
        if _git("rev-parse", "--verify", "--quiet", ref + "^{commit}").returncode == 0:
            return ref
    return None


def model_at(ref, core):
    """Config of `core` at `ref`, or None when the core does not exist there."""
    texts = []
    for name in ("schema.xml", "solrconfig.xml"):
        r = _git("show", "%s:%s/conf/%s" % (ref, core, name))
        if r.returncode != 0:
            return None
        texts.append(r.stdout)
    return Config(core, texts[0], texts[1])


def changed_cores(ref):
    """Cores whose conf/ differs from `ref` (tracked or untracked). All cores if tests/ changed."""
    names = set(_git("diff", "--name-only", ref, "--").stdout.split("\n"))
    names |= set(_git("ls-files", "--others", "--exclude-standard").stdout.split("\n"))
    names.discard("")
    if any(n.startswith("tests/") for n in names):
        return list(CORES)
    return [c for c in CORES if any(n.startswith(c + "/conf/") for n in names)]


def _attrs(a):
    return ", ".join("%s=%s" % kv for kv in sorted(a.items()) if kv[0] != "name")


def _diff_named(label, old, new, out, render=_attrs):
    for name in sorted(set(old) | set(new)):
        if name not in old:
            out.append("+ %s %s (%s)" % (label, name, render(new[name])))
        elif name not in new:
            out.append("- %s %s (%s)" % (label, name, render(old[name])))
        elif old[name] != new[name]:
            o, n = old[name], new[name]
            if isinstance(o, dict) and isinstance(n, dict):
                parts = []
                for k in sorted(set(o) | set(n)):
                    if o.get(k) != n.get(k):
                        parts.append("%s: %s -> %s" % (k, o.get(k, "(unset)"), n.get(k, "(unset)")))
                out.append("~ %s %s: %s" % (label, name, "; ".join(parts)))
            else:
                out.append("~ %s %s: %s -> %s" % (label, name, o, n))


def _diff_list(label, old, new, out):
    if old == new:
        return
    added = [x for x in new if x not in old]
    removed = [x for x in old if x not in new]
    if added or removed:
        out.append("~ %s: %s" % (label, " ".join(["+" + x for x in added] + ["-" + x for x in removed])))
    else:
        out.append("~ %s: order changed" % label)


def _type_view(t):
    d = dict(t["attrs"])
    d["analysis"] = " > ".join(c.replace("solr.", "") for c in t["classes"]) or "(none)"
    return d


def diff(old, new):
    """Readable list of differences between two Config objects (old = ref, new = working tree)."""
    out = []
    if old.schema_version != new.schema_version:
        out.append("~ schema version: %s -> %s" % (old.schema_version, new.schema_version))
    if old.unique_key != new.unique_key:
        out.append("~ uniqueKey: %s -> %s" % (old.unique_key, new.unique_key))
    _diff_named("fieldType", {k: _type_view(v) for k, v in old.types.items()},
                {k: _type_view(v) for k, v in new.types.items()}, out)
    _diff_named("field", old.fields, new.fields, out)
    _diff_named("dynamicField", old.dynamic_fields, new.dynamic_fields, out)
    _diff_list("copyField", ["%s->%s" % c for c in old.copy_fields],
               ["%s->%s" % c for c in new.copy_fields], out)
    if old.lucene_match_version != new.lucene_match_version:
        out.append("~ luceneMatchVersion: %s -> %s" % (old.lucene_match_version, new.lucene_match_version))
    for h in sorted(set(old.handlers) | set(new.handlers)):
        if h not in old.handlers:
            out.append("+ requestHandler %s" % h)
            continue
        if h not in new.handlers:
            out.append("- requestHandler %s" % h)
            continue
        for kind in ("defaults", "invariants", "appends"):
            o, n = old.handlers[h][kind], new.handlers[h][kind]
            for key in sorted(set(o) | set(n)):
                _diff_list("%s %s %s" % (h, kind, key), o.get(key, []), n.get(key, []), out)
    for label, o, n in (("autoCommit", old.auto_commit, new.auto_commit),
                        ("autoSoftCommit", old.auto_soft_commit, new.auto_soft_commit)):
        if o != n:
            out.append("~ %s: %s -> %s" % (label, _attrs(o) or "(unset)", _attrs(n) or "(unset)"))
    _diff_named("cache", {k: {"class": str(v)} for k, v in old.caches.items()},
                {k: {"class": str(v)} for k, v in new.caches.items()}, out)
    for label, o, n in (("<jmx/>", old.jmx, new.jmx),
                        ("enableRemoteStreaming attribute", old.remote_streaming_attr, new.remote_streaming_attr)):
        if o != n:
            out.append("%s %s" % ("+" if n else "-", label))
    if not out and (old.schema_text != new.schema_text or old.solrconfig_text != new.solrconfig_text):
        out.append("(files differ only in comments, whitespace or settings the tests do not model)")
    return out
