"""Throwaway Solr container holding the cores under test, and a small HTTP client."""
import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

from .config import REPO

# Builds the core directories inside the container from the read-only mounts, then starts
# Solr. Nothing is written on the host.
_STARTUP = (
    'for c in /cores-src/*; do n=$(basename "$c"); '
    'mkdir -p "/var/solr/data/$n/data"; cp -r "$c/conf" "/var/solr/data/$n/conf"; '
    'if [ -d "$c/lib" ]; then cp -r "$c/lib" "/var/solr/data/$n/lib"; fi; '
    'echo "name=$n" > "/var/solr/data/$n/core.properties"; done; '
    # Solr 10 starts in SolrCloud mode unless told otherwise; these are standalone cores.
    'flag=""; if solr start --help 2>&1 | grep -q -- "--user-managed"; then flag="--user-managed"; fi; '
    "exec solr-foreground $flag"
)


class DockerError(Exception):
    pass


def docker_available():
    try:
        return subprocess.run(["docker", "info"], capture_output=True).returncode == 0
    except FileNotFoundError:
        return False


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class SolrContainer:
    def __init__(self, image, cores, decs_cores=(), jar=None, decs_index=None):
        self.image = image
        self.cores = list(cores)
        self.decs_cores = [c for c in decs_cores if c in self.cores]
        self.jar = jar
        self.decs_index = decs_index
        self.port = _free_port()
        self.name = "solr-config-tests-%d" % os.getpid()
        self.base = "http://127.0.0.1:%d/solr" % self.port
        self.init_failures = {}
        self.loaded = []
        self._log = None

    def start(self, timeout=180):
        cmd = ["docker", "run", "-d", "--name", self.name, "-p", "127.0.0.1:%d:8983" % self.port]
        for core in self.cores:
            cmd += ["-v", "%s:/cores-src/%s/conf:ro" % (os.path.join(REPO, core, "conf"), core)]
            if core in self.decs_cores:
                cmd += ["-v", "%s:/cores-src/%s/lib/iahx-analyzer.jar:ro" % (self.jar, core)]
        if self.decs_cores:
            cmd += ["-v", "%s:/opt/solr/server/resources/decs/main:ro" % self.decs_index]
        cmd += [self.image, "bash", "-c", _STARTUP]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise DockerError(r.stderr.strip())
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(self.base + "/admin/cores?action=STATUS&wt=json", timeout=5) as resp:
                    st = json.load(resp)
                self.init_failures = st.get("initFailures", {})
                self.loaded = sorted(st.get("status", {}))
                if set(self.loaded) | set(self.init_failures) >= set(self.cores):
                    return
            except (urllib.error.URLError, ConnectionError, socket.timeout, ValueError):
                if subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", self.name],
                                  capture_output=True, text=True).stdout.strip() != "true":
                    raise DockerError("Solr container exited during startup:\n" + self.logs()[-3000:])
            time.sleep(2)
        raise DockerError("Solr did not report all cores within %d s:\n%s" % (timeout, self.logs()[-3000:]))

    def logs(self, refresh=True):
        if refresh or self._log is None:
            r = subprocess.run(["docker", "logs", self.name], capture_output=True, text=True)
            self._log = r.stdout + r.stderr
        return self._log

    def exec(self, *cmd):
        r = subprocess.run(["docker", "exec", self.name] + list(cmd), capture_output=True, text=True)
        return r.returncode, r.stdout

    def remove(self):
        subprocess.run(["docker", "rm", "-f", self.name], capture_output=True)

    def core(self, name):
        return Core(self.base + "/" + name)


class Core:
    """HTTP client for one core. Responses are parsed JSON; HTTP errors are returned, not raised."""

    def __init__(self, base):
        self.base = base

    def _open(self, req):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def raw(self, path, **params):
        """(status, body bytes) of a GET. A list value repeats the parameter."""
        qs = urllib.parse.urlencode(params, doseq=True)
        return self._open(self.base + path + ("?" + qs if qs else ""))

    def get(self, path, **params):
        params.setdefault("wt", "json")
        status, body = self.raw(path, **params)
        try:
            return json.loads(body)
        except ValueError:
            return {"http_status": status, "body": body.decode("utf-8", "replace")}

    def select(self, q, handler="/select", **params):
        return self.get(handler, q=q, **params)

    def num_found(self, q, fq=None, handler="/select", **params):
        if fq:
            params["fq"] = fq
        r = self.select(q, handler=handler, rows=0, **params)
        return r.get("response", {}).get("numFound", "error: %s" % r.get("error", r))

    def ids(self, q, **params):
        params.setdefault("rows", 100)
        return [d["id"] for d in self.select(q, fl="id", **params)["response"]["docs"]]

    def _post(self, path, body, content_type):
        req = urllib.request.Request(self.base + path, data=body, headers={"Content-Type": content_type})
        status, out = self._open(req)
        try:
            return json.loads(out)
        except ValueError:
            return {"http_status": status, "body": out.decode("utf-8", "replace")}

    def update_json(self, docs, commit=False):
        return self._post("/update?wt=json" + ("&commit=true" if commit else ""),
                          json.dumps(docs).encode("utf-8"), "application/json")

    def update_xml(self, xml, commit=False):
        return self._post("/update?wt=json" + ("&commit=true" if commit else ""),
                          xml.encode("utf-8"), "text/xml; charset=utf-8")

    def commit(self):
        return self.update_xml("<commit/>")

    def delete_all(self):
        return self.update_xml("<delete><query>*:*</query></delete>", commit=True)

    def delete_id(self, doc_id, commit=True):
        return self.update_json({"delete": {"id": doc_id}}, commit=commit)

    @staticmethod
    def ok(response):
        return response.get("responseHeader", {}).get("status") == 0
