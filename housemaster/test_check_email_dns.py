"""B-12: scripts/check_email_dns.py with made-up DNS answers, good and bad."""
import importlib.util
import io
import sys
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_email_dns.py"
spec = importlib.util.spec_from_file_location("check_email_dns", SCRIPT)
dnscheck = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dnscheck)

KEY_2048 = "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA" + "A" * 350
KEY_1024 = "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC" + "A" * 150


def resolver(records):
    return lambda name: records.get(name, [])


GOOD = {
    "school.test": ["v=spf1 include:spf.brevo.com -all", "google-site-verification=abc"],
    "s1._domainkey.school.test": [f"v=DKIM1; k=rsa; p={KEY_2048}"],
    "_dmarc.school.test": ["v=DMARC1; p=quarantine; rua=mailto:dmarc@school.test"],
}


def run(records, selector="s1", provider="brevo"):
    out = io.StringIO()
    code, results = dnscheck.run("school.test", resolver(records), selector, provider, out=out)
    return code, {check: (status, detail) for check, status, detail in results}, out.getvalue()


class EmailDnsTests(SimpleTestCase):
    def test_a_good_setup_passes(self):
        code, results, output = run(GOOD)
        self.assertEqual(code, 0, output)
        self.assertTrue(all(status == dnscheck.PASS for status, _ in results.values()), results)

    def test_nothing_set_up(self):
        code, results, _ = run({})
        self.assertEqual(code, 1)
        self.assertEqual(results["SPF"][0], dnscheck.FAIL)
        self.assertEqual(results["DKIM"][0], dnscheck.FAIL)
        self.assertEqual(results["DMARC"][0], dnscheck.FAIL)

    def test_two_spf_records(self):
        records = {**GOOD, "school.test": ["v=spf1 include:spf.brevo.com -all", "v=spf1 include:_spf.google.com ~all"]}
        code, results, _ = run(records)
        self.assertEqual(code, 1)
        self.assertIn("2 SPF records", results["SPF"][1])

    def test_plus_all_and_neutral_all(self):
        _, results, _ = run({**GOOD, "school.test": ["v=spf1 include:spf.brevo.com +all"]})
        self.assertEqual(results["SPF ending"][0], dnscheck.FAIL)
        _, results, _ = run({**GOOD, "school.test": ["v=spf1 include:spf.brevo.com ?all"]})
        self.assertEqual(results["SPF ending"][0], dnscheck.WARN)
        _, results, _ = run({**GOOD, "school.test": ["v=spf1 include:spf.brevo.com"]})
        self.assertEqual(results["SPF ending"][0], dnscheck.WARN)

    def test_missing_include_for_the_provider(self):
        _, results, _ = run({**GOOD, "school.test": ["v=spf1 include:_spf.google.com -all"]})
        self.assertEqual(results["SPF provider"][0], dnscheck.FAIL)
        self.assertIn("include:spf.brevo.com", results["SPF provider"][1])

    def test_too_many_lookups(self):
        many = " ".join(f"include:x{i}.test" for i in range(11))
        _, results, _ = run({**GOOD, "school.test": [f"v=spf1 {many} -all"]}, provider=None)
        self.assertEqual(results["SPF lookups"][0], dnscheck.FAIL)

    def test_dmarc_none_and_no_reports(self):
        code, results, _ = run({**GOOD, "_dmarc.school.test": ["v=DMARC1; p=none"]})
        self.assertEqual(code, 0, "warnings only")
        self.assertEqual(results["DMARC policy"][0], dnscheck.WARN)
        self.assertEqual(results["DMARC reports"][0], dnscheck.WARN)

    def test_dmarc_bad_policy_and_duplicates(self):
        _, results, _ = run({**GOOD, "_dmarc.school.test": ["v=DMARC1; p=block"]})
        self.assertEqual(results["DMARC policy"][0], dnscheck.FAIL)
        _, results, _ = run({**GOOD, "_dmarc.school.test": ["v=DMARC1; p=reject", "v=DMARC1; p=none"]})
        self.assertEqual(results["DMARC"][0], dnscheck.FAIL)

    def test_dkim_empty_weak_and_skipped(self):
        _, results, _ = run({**GOOD, "s1._domainkey.school.test": ["v=DKIM1; k=rsa; p="]})
        self.assertEqual(results["DKIM"][0], dnscheck.FAIL)
        _, results, _ = run({**GOOD, "s1._domainkey.school.test": [f"v=DKIM1; k=rsa; p={KEY_1024}"]})
        self.assertEqual(results["DKIM"][0], dnscheck.WARN)
        _, results, _ = run(GOOD, selector=None)
        self.assertEqual(results["DKIM"][0], dnscheck.SKIP)

    def test_clear_message_without_dnspython(self):
        with patch.dict(sys.modules, {"dns": None, "dns.resolver": None}), self.assertRaises(SystemExit) as ctx:
            dnscheck.dnspython_resolver()
        self.assertIn("pip install dnspython", str(ctx.exception))

    def test_a_dns_timeout_is_reported_not_a_crash(self):
        def timing_out(name):
            raise dnscheck.LookupFailed(f"{name}: LifetimeTimeout")

        out = io.StringIO()
        code, results = dnscheck.run("school.test", timing_out, "s1", "brevo", out=out)
        self.assertEqual(code, 1)
        self.assertEqual([r[0] for r in results], ["SPF", "DKIM", "DMARC"])
        self.assertIn("couldn't look it up", out.getvalue())

