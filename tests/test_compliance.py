"""Digistore24 compliance checks (revision email of 2026-10-13), stdlib only.

Run: python3 -m unittest discover -s tests -v   (from the repo root)

Each test maps to one numbered DS24 required revision:
  1 only two products, nothing above $1,000      5 no free offer / discovery call
  2 separate domain, no agentsetup.io links       6 footer: Terms, Privacy (with unsubscribe), Contact
  3 no DS24 trust badge or promo scripts          7 displayed prices == prices.json
  4 no unrelated links                            8 refund page, no shipping language
Plus brand rules: zero em dashes, required pages present, buy placeholders wired.
"""
import html
import json
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIRED_PAGES = ["index.html", "thank-you.html", "terms.html", "privacy.html", "refund.html", "contact.html"]
HTML_FILES = sorted(ROOT.glob("*.html"))
PRICES = json.loads((ROOT / "prices.json").read_text())
CONTACT_EMAIL = "cooper@agentsetup.io"
ALLOWED_EXTERNAL_HOSTS = ("https://fonts.googleapis.com", "https://fonts.gstatic.com")


class _Collector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []      # (tag, attr, value)
        self.text = []
        self.footer_links = []
        self._skip = 0
        self._in_footer = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style"):
            self._skip += 1
        if tag == "footer":
            self._in_footer += 1
        for attr in ("href", "src", "action", "data-src", "srcset"):
            if a.get(attr):
                self.links.append((tag, attr, a[attr].strip()))
                if self._in_footer and tag == "a" and attr == "href":
                    self.footer_links.append(a[attr].strip())

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        if tag == "footer" and self._in_footer:
            self._in_footer -= 1

    def handle_data(self, data):
        if not self._skip:
            self.text.append(data)


def parse(path):
    raw = path.read_text(encoding="utf-8")
    c = _Collector()
    c.feed(raw)
    visible = re.sub(r"\s+", " ", " ".join(c.text))
    return raw, visible, c


PAGES = {p.name: parse(p) for p in HTML_FILES}


def all_strings(raw, visible):
    """Raw source (including comments, attributes, scripts) plus decoded visible text."""
    return raw + "\n" + html.unescape(raw) + "\n" + visible


class TestStructure(unittest.TestCase):
    def test_required_pages_exist(self):
        for name in REQUIRED_PAGES:
            self.assertTrue((ROOT / name).is_file(), f"missing page {name}")

    def test_no_unexpected_pages(self):
        self.assertEqual(sorted(p.name for p in HTML_FILES), sorted(REQUIRED_PAGES))


class Test1OnlyTwoProducts(unittest.TestCase):
    BANNED_TIERS = re.compile(r"\b(growth|pro|enterprise)\b\s*(plan|tier|package)?", re.I)

    def test_prices_json_has_exactly_two_products_le_1000(self):
        prods = PRICES["products"]
        self.assertEqual(set(prods), {"starter", "hourly"})
        self.assertEqual({p["ds24_product_id"] for p in prods.values()}, {721490, 721520})
        for p in prods.values():
            self.assertLessEqual(p["price"], 1000, p)

    def test_no_other_tier_names(self):
        for name, (raw, visible, _) in PAGES.items():
            for m in re.finditer(r"\b(Growth|Pro|Enterprise)\b", visible):
                self.fail(f"{name}: other tier name present: {m.group(0)!r}")

    def test_no_other_ds24_product_ids(self):
        for name, (raw, visible, _) in PAGES.items():
            ids = set(re.findall(r"\b72\d{4}\b", raw))
            self.assertTrue(ids <= {"721490", "721520"}, f"{name}: foreign product ids {ids}")

    def test_both_products_named_on_sales_page(self):
        visible = PAGES["index.html"][1]
        for p in PRICES["products"].values():
            self.assertIn(p["name"], visible)


class Test2NoMainDomainLinks(unittest.TestCase):
    def test_no_agentsetup_io_except_contact_email(self):
        for name, (raw, visible, _) in PAGES.items():
            stripped = all_strings(raw, visible).replace(CONTACT_EMAIL, "")
            self.assertNotRegex(stripped.lower(), r"agentsetup\.io", f"{name}: agentsetup.io reference")

    def test_no_hardcoded_own_domain_or_canonical(self):
        for name, (raw, _, _) in PAGES.items():
            self.assertNotRegex(raw, r'rel="canonical"', f"{name}: canonical tag hardcodes a domain")
            self.assertNotRegex(raw, r'property="og:url"', name)


class Test3NoDigistoreBadgesOrScripts(unittest.TestCase):
    BANNED = [
        r"trust(ed)?[\s_-]*badge", r"digistore24-scripts", r"digistore\.js", r"digistorePromocode",
        r"ds24.*badge", r"badge.*ds24", r"digistore24\.com/(trusted|badge)", r"\bds24\b.*\.(png|svg|js)",
    ]

    def test_no_badge_or_promo_strings(self):
        for name, (raw, visible, _) in PAGES.items():
            blob = all_strings(raw, visible)
            for pat in self.BANNED:
                self.assertIsNone(re.search(pat, blob, re.I), f"{name}: banned DS24 badge/script pattern {pat}")

    def test_no_scripts_at_all(self):
        for name, (raw, _, _) in PAGES.items():
            self.assertNotIn("<script", raw.lower(), f"{name}: contains a script tag")

    def test_no_digistore_in_any_link_or_src(self):
        for name, (_, _, c) in PAGES.items():
            for tag, attr, val in c.links:
                self.assertNotRegex(val.lower(), r"digistore|ds24", f"{name}: {tag}[{attr}]={val}")


class Test4NoUnrelatedLinks(unittest.TestCase):
    def test_every_link_is_internal_mailto_or_fonts(self):
        local = {p.name for p in HTML_FILES} | {"styles.css"}
        for name, (_, _, c) in PAGES.items():
            for tag, attr, val in c.links:
                if val.startswith("#"):
                    continue
                if val == f"mailto:{CONTACT_EMAIL}":
                    continue
                if val.startswith(ALLOWED_EXTERNAL_HOSTS) and tag == "link":
                    continue
                target = val.split("#", 1)[0]
                self.assertIn(target, local, f"{name}: link outside the site: {tag}[{attr}]={val}")

    def test_no_blog_social_or_booking_words_in_links(self):
        bad = re.compile(r"blog|facebook|instagram|linkedin|twitter|x\.com|youtube|tiktok|cal\.com|calendly|stripe", re.I)
        for name, (_, _, c) in PAGES.items():
            for _, _, val in c.links:
                self.assertIsNone(bad.search(val), f"{name}: unrelated link {val}")


class Test5NoFreeOffer(unittest.TestCase):
    BANNED = [r"\bfree\b", r"discovery\s+call", r"\bdiscovery\b", r"\bcomplimentary\b", r"\bno[\s-]cost\b",
              r"\bat no charge\b", r"\bfree[\s-]of[\s-]charge\b", r"\bgratis\b", r"\btrial\b", r"\bbonus\b"]

    def test_no_free_language(self):
        for name, (raw, visible, _) in PAGES.items():
            blob = all_strings(raw, visible)
            for pat in self.BANNED:
                m = re.search(pat, blob, re.I)
                self.assertIsNone(m, f"{name}: banned free-offer phrase {m.group(0) if m else ''!r}")


class Test6Footer(unittest.TestCase):
    REQUIRED = {"terms.html": "Terms and Conditions", "privacy.html": "Privacy Policy", "contact.html": "Contact Us"}

    def test_footer_links_on_every_page(self):
        for name, (raw, _, c) in PAGES.items():
            self.assertIn("<footer", raw, f"{name}: no footer")
            for href in self.REQUIRED:
                self.assertIn(href, c.footer_links, f"{name}: footer missing {href}")
            footer_html = raw[raw.index("<footer"):]
            for href, label in self.REQUIRED.items():
                self.assertRegex(footer_html, rf'href="{re.escape(href)}">{re.escape(label)}<', f"{name}: footer label {label}")

    def test_privacy_has_unsubscribe_opt_out(self):
        visible = PAGES["privacy.html"][1].lower()
        for word in ("newsletter", "unsubscribe", "opt out"):
            self.assertIn(word, visible, f"privacy.html missing {word!r}")

    def test_contact_page_has_email(self):
        self.assertIn(f"mailto:{CONTACT_EMAIL}", PAGES["contact.html"][0])


class Test7PricesMatch(unittest.TestCase):
    PRICE_RE = re.compile(r"(?:\$|US\$|USD\s?)\s?(\d[\d,]*(?:\.\d{2})?)")

    def displayed(self):
        found = {}
        for name, (raw, visible, _) in PAGES.items():
            for m in self.PRICE_RE.finditer(html.unescape(raw) + " " + visible):
                found.setdefault(float(m.group(1).replace(",", "")), set()).add(name)
        return found

    def test_only_recorded_prices_displayed(self):
        recorded = {float(p["price"]) for p in PRICES["products"].values()}
        shown = set(self.displayed())
        self.assertTrue(shown, "no prices displayed")
        self.assertEqual(shown - recorded, set(), f"unrecorded prices displayed: {shown - recorded}")

    def test_all_prices_le_1000(self):
        for amount, pages in self.displayed().items():
            self.assertLessEqual(amount, 1000, f"${amount} on {pages}")

    def test_at_most_two_distinct_prices(self):
        self.assertLessEqual(len(self.displayed()), 2)

    def test_each_product_card_shows_its_price(self):
        raw = PAGES["index.html"][0]
        for key, p in PRICES["products"].items():
            m = re.search(rf'<article class="product[^"]*" id="{key}">(.*?)</article>', raw, re.S)
            self.assertIsNotNone(m, f"no product card #{key}")
            card = m.group(1)
            self.assertIn(p["name"], card)
            self.assertRegex(card, rf'<div class="price">\${p["price"]:,}\b', f"{key} card price mismatch")
            self.assertIn(f'href="{p["buy_anchor"]}"', card, f"{key} buy placeholder missing")

    def test_buy_buttons_are_placeholders_with_ds24_note(self):
        raw = PAGES["index.html"][0]
        for p in PRICES["products"].values():
            self.assertIn(f'href="{p["buy_anchor"]}"', raw)
            self.assertRegex(raw, rf"<!--[^>]*DS24 order-form URL[^>]*{p['ds24_product_id']}[^>]*-->")


class Test8RefundAndNoShipping(unittest.TestCase):
    SHIP = re.compile(r"\bship(s|ped|ping|ment|ments)?\b|\bdispatch(ed)?\b|\bpostage\b|\bcourier\b", re.I)

    def test_no_shipping_language(self):
        for name, (raw, visible, _) in PAGES.items():
            blob = all_strings(raw, visible)
            m = self.SHIP.search(blob)
            self.assertIsNone(m, f"{name}: shipping language {m.group(0) if m else ''!r}")

    def test_no_ship_substring_in_visible_text(self):
        # Stricter: avoid even "ownership"/"relationship" so a naive reviewer grep stays clean.
        for name, (_, visible, _) in PAGES.items():
            self.assertNotIn("ship", visible.lower(), f"{name}: 'ship' substring in visible text")

    def test_refund_page_clear(self):
        visible = PAGES["refund.html"][1].lower()
        for phrase in ("60 days", "full refund", "how to request a refund", "original payment method"):
            self.assertIn(phrase, visible)

    def test_refund_linked_from_sales_page_and_footer(self):
        for name, (_, _, c) in PAGES.items():
            self.assertIn("refund.html", c.footer_links, f"{name}: footer missing refund.html")


class TestCopyRules(unittest.TestCase):
    def test_zero_em_dashes(self):
        for name, (raw, _, _) in PAGES.items():
            for bad in ("—", "&mdash;", "&#8212;", "&#x2014;"):
                self.assertNotIn(bad, raw, f"{name}: em dash {bad!r}")
        self.assertNotIn("—", (ROOT / "styles.css").read_text())

    def test_no_testimonial_or_review_markup(self):
        for name, (raw, visible, _) in PAGES.items():
            self.assertNotRegex(visible, r"(?i)testimonial|★|5 stars|rated \d", name)
            self.assertNotIn("<blockquote", raw.lower(), name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
