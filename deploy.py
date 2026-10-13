"""Deploy the Digistore24 site to Netlify and point agentsetup.agency at it.

Netlify token: login keychain service INSTALLAGENT_NETLIFY_TOKEN (Cooper's personal Netlify).
Namecheap DNS: via ~/.claude/skills/BuyDomain/nc_domains.py call() (svt-vault, unlock first).
Never prints a credential. Safe to re-run: reuses the site by name.
"""
import io, json, os, ssl, subprocess, sys, urllib.request, zipfile, importlib.util
from pathlib import Path

SITE_NAME = "agentsetup-agency"
DOMAIN = "agentsetup.agency"
ROOT = Path(__file__).resolve().parent
CA = next((c for c in ("/etc/ssl/cert.pem", "/opt/homebrew/etc/ca-certificates/cert.pem") if os.path.exists(c)), None)
CTX = ssl.create_default_context(cafile=CA)
PAGES = ["index.html", "thank-you.html", "terms.html", "privacy.html", "refund.html", "contact.html", "styles.css"]


def token():
    t = subprocess.run(["security", "find-generic-password", "-s", "INSTALLAGENT_NETLIFY_TOKEN", "-w"],
                       capture_output=True, text=True).stdout.strip()
    if not t:
        sys.exit("netlify token missing")
    return t


def api(method, path, body=None, ctype="application/json"):
    data = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode()
    req = urllib.request.Request("https://api.netlify.com/api/v1" + path, data=data, method=method,
                                 headers={"Authorization": "Bearer " + token(), "Content-Type": ctype})
    with urllib.request.urlopen(req, timeout=60, context=CTX) as r:
        raw = r.read()
        return json.loads(raw) if raw else {}


def get_site():
    for s in api("GET", "/sites?per_page=100"):
        if s.get("name") == SITE_NAME:
            return s
    return api("POST", "/sites", {"name": SITE_NAME})


def deploy(site):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in PAGES:
            z.write(ROOT / p, p)
    d = api("POST", f"/sites/{site['id']}/deploys", buf.getvalue(), "application/zip")
    return d


def set_domain(site):
    return api("PATCH", f"/sites/{site['id']}", {"custom_domain": DOMAIN, "domain_aliases": ["www." + DOMAIN]})


def set_dns(site):
    s = importlib.util.spec_from_file_location("nc", os.path.expanduser("~/.claude/skills/BuyDomain/nc_domains.py"))
    nc = importlib.util.module_from_spec(s)
    s.loader.exec_module(nc)
    # setHosts replaces the whole record set; the domain held only Namecheap parking records (read 2026-10-13).
    params = {"Command": "namecheap.domains.dns.setHosts", "SLD": "agentsetup", "TLD": "agency",
              "HostName1": "@", "RecordType1": "A", "Address1": "75.2.60.5", "TTL1": "1800",
              "HostName2": "www", "RecordType2": "CNAME", "Address2": site["name"] + ".netlify.app", "TTL2": "1800"}
    r = nc.call(params, "")
    ok = [e.get("IsSuccess") for e in r.iter() if e.tag.endswith("DomainDNSSetHostsResult")]
    errs = [e.text for e in r.iter() if e.tag.endswith("Error")]
    return ok, errs


if __name__ == "__main__":
    site = get_site()
    print("site:", site["name"], site.get("ssl_url") or site.get("url"))
    d = deploy(site)
    print("deploy:", d.get("id"), d.get("state"))
    s2 = set_domain(site)
    print("custom_domain:", s2.get("custom_domain"), "aliases:", s2.get("domain_aliases"))
    print("dns setHosts:", set_dns(site))
