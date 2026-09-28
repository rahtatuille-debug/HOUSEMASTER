#!/usr/bin/env python3
"""
Read-only check of a domain's email authentication records (B-12).

    python scripts/check_email_dns.py yourschool-app.com --dkim-selector s1 --provider brevo

Looks up SPF, DKIM (when you give the selector) and DMARC in DNS and says,
in plain language, whether each is there and sensible, and the common
mistakes: more than one SPF record, "+all", no include for your email
provider, DMARC left at p=none, and no address for DMARC reports. It
changes nothing. Exit status 1 if anything failed.

Needs dnspython (in requirements-dev.txt): pip install dnspython

Where to find the DKIM selector: in your email provider's domain settings
(the "DKIM" or "domain authentication" page shows a record named
<selector>._domainkey.<your domain>; the selector is the part before
._domainkey). docs/MERGE_DAY_CHECKLIST.md has the steps.
"""
import argparse
import sys

PASS, WARN, FAIL, SKIP = "PASS", "WARN", "FAIL", "SKIP"


class LookupFailed(Exception):
    """DNS didn't answer (no network, timeout); different from "no such record"."""

# The SPF "include" each provider asks for. Check your provider's own
# setup page too; they change these now and then.
PROVIDER_INCLUDES = {
    "google": ["_spf.google.com"],
    "microsoft": ["spf.protection.outlook.com"],
    "sendgrid": ["sendgrid.net"],
    "mailgun": ["mailgun.org"],
    "ses": ["amazonses.com"],
    "postmark": ["spf.mtasv.net"],
    "brevo": ["spf.brevo.com", "spf.sendinblue.com"],
    "zoho": ["zoho.com", "zoho.eu"],
    "mailjet": ["spf.mailjet.com"],
}


def dnspython_resolver():
    try:
        import dns.resolver
    except ImportError:
        sys.exit("This check needs dnspython: pip install dnspython (it is in requirements-dev.txt).")

    import dns.exception

    def lookup_txt(name):
        try:
            answers = dns.resolver.resolve(name, "TXT", lifetime=10)
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            return []
        except dns.exception.DNSException as exc:
            raise LookupFailed(f"{name}: {exc.__class__.__name__}") from exc
        return [b"".join(record.strings).decode("utf-8", "replace") for record in answers]

    return lookup_txt


def check_spf(domain, lookup_txt, provider=None):
    records = [r for r in lookup_txt(domain) if r.lower().startswith("v=spf1")]
    if not records:
        return [("SPF", FAIL, f"no SPF record on {domain}: receivers can't tell which servers may send its mail")]
    if len(records) > 1:
        return [("SPF", FAIL, f"{len(records)} SPF records; there must be exactly one (merge them), "
                              "or receivers treat SPF as broken")]
    record = records[0]
    terms = record.split()[1:]
    results = [("SPF record", PASS, record)]
    all_terms = [t for t in terms if t.lower().lstrip("+-~?") == "all"]
    if not all_terms:
        results.append(("SPF ending", WARN, 'no "all" at the end, so mail from anywhere else is left undecided; '
                                            'end with "~all" or "-all"'))
    else:
        qualifier = all_terms[-1][0] if all_terms[-1][0] in "+-~?" else "+"
        results.append({
            "+": ("SPF ending", FAIL, '"+all" lets ANY server on the internet send as this domain; use "~all" or "-all"'),
            "?": ("SPF ending", WARN, '"?all" is neutral and protects nothing; use "~all" or "-all"'),
            "~": ("SPF ending", PASS, '"~all": other servers soft-fail'),
            "-": ("SPF ending", PASS, '"-all": other servers fail'),
        }[qualifier])
    lookups = [t for t in terms if t.lower().lstrip("+-~?").split(":")[0].split("=")[0]
               in ("include", "a", "mx", "ptr", "exists", "redirect")]
    if len(lookups) > 10:
        results.append(("SPF lookups", FAIL, f"{len(lookups)} DNS lookups at the top level alone; the limit is 10"))
    if provider:
        wanted = PROVIDER_INCLUDES.get(provider.lower())
        includes = [t.split(":", 1)[1].lower() for t in terms if t.lower().lstrip("+").startswith("include:")]
        if wanted is None:
            results.append(("SPF provider", WARN, f'unknown provider "{provider}"; check its include yourself'))
        elif any(w in includes for w in wanted):
            results.append(("SPF provider", PASS, f"includes {provider}"))
        else:
            results.append(("SPF provider", FAIL, f"no include for {provider} (expected include:{wanted[0]}); "
                                                  "its mail will fail SPF"))
    return results


def check_dkim(domain, lookup_txt, selector=None):
    if not selector:
        return [("DKIM", SKIP, "no --dkim-selector given (find it in your email provider's domain settings)")]
    name = f"{selector}._domainkey.{domain}"
    records = [r for r in lookup_txt(name) if "p=" in r]
    if not records:
        return [("DKIM", FAIL, f"no DKIM key at {name}; check the selector and that the record was added")]
    tags = dict(part.strip().split("=", 1) for part in records[0].split(";") if "=" in part)
    key = tags.get("p", "").strip()
    if not key:
        return [("DKIM", FAIL, f"the key at {name} is empty (revoked)")]
    if len(key) < 300:
        return [("DKIM", WARN, f"key found at {name}, but it looks like a 1024-bit key; ask the provider for 2048-bit")]
    return [("DKIM", PASS, f"key found at {name}")]


def check_dmarc(domain, lookup_txt):
    name = f"_dmarc.{domain}"
    records = [r for r in lookup_txt(name) if r.lower().startswith("v=dmarc1")]
    if not records:
        return [("DMARC", FAIL, f"no DMARC record at {name}: nothing tells receivers what to do with forged mail")]
    if len(records) > 1:
        return [("DMARC", FAIL, f"{len(records)} DMARC records at {name}; there must be exactly one")]
    tags = {k.strip().lower(): v.strip() for k, v in
            (part.split("=", 1) for part in records[0].split(";") if "=" in part)}
    policy = tags.get("p", "").lower()
    results = [("DMARC record", PASS, records[0])]
    if policy == "none":
        results.append(("DMARC policy", WARN, "p=none only monitors; move to p=quarantine, then p=reject, once "
                                              "the reports show your real mail passing"))
    elif policy in ("quarantine", "reject"):
        results.append(("DMARC policy", PASS, f"p={policy}"))
    else:
        results.append(("DMARC policy", FAIL, f'p="{policy}" isn\'t a valid policy (none, quarantine or reject)'))
    if "rua" not in tags:
        results.append(("DMARC reports", WARN, "no rua= address, so you'll never see who is sending as you"))
    else:
        results.append(("DMARC reports", PASS, f"rua={tags['rua']}"))
    if tags.get("pct", "100") != "100":
        results.append(("DMARC coverage", WARN, f"pct={tags['pct']}: the policy applies to only part of the mail"))
    return results


def run(domain, lookup_txt, selector=None, provider=None, out=sys.stdout):
    results = []
    for label, check in (("SPF", lambda: check_spf(domain, lookup_txt, provider)),
                         ("DKIM", lambda: check_dkim(domain, lookup_txt, selector)),
                         ("DMARC", lambda: check_dmarc(domain, lookup_txt))):
        try:
            results += check()
        except LookupFailed as exc:
            results.append((label, FAIL, f"couldn't look it up ({exc}); check your internet connection and try again"))
    width = max(len(r[0]) for r in results)
    print(f"Email authentication for {domain}\n", file=out)
    for check, status, detail in results:
        print(f"{check:<{width}}  {status:<4}  {detail}", file=out)
    failed = sum(1 for r in results if r[1] == FAIL)
    warned = sum(1 for r in results if r[1] == WARN)
    print(f"\n{failed} failed, {warned} warnings.", file=out)
    return (1 if failed else 0), results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("domain", help="the domain in DEFAULT_FROM_EMAIL, e.g. yourschool-app.com")
    parser.add_argument("--dkim-selector", help="the DKIM selector from your email provider")
    parser.add_argument("--provider", help=f"your email provider ({', '.join(sorted(PROVIDER_INCLUDES))})")
    args = parser.parse_args(argv)
    code, _ = run(args.domain.strip().rstrip(".").lower(), dnspython_resolver(), args.dkim_selector, args.provider)
    return code


if __name__ == "__main__":
    sys.exit(main())
