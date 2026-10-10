import pytest

from careerforge.text import (
    clean_bullet,
    clean_text,
    date_key,
    display_date,
    normalize_email,
    normalize_partial_date,
    normalize_phone,
    normalize_url,
    parse_date_range,
)


class TestCleanText:
    def test_collapses_whitespace_and_strips(self):
        assert clean_text("  a \t b\n c  ") == "a b c"

    def test_none_is_empty(self):
        assert clean_text(None) == ""

    def test_removes_invisible_and_bidi_controls(self):
        assert clean_text("Pri​ya‮ Nair\x00") == "Priya Nair"

    def test_multiline_keeps_paragraphs(self):
        assert clean_text("a  b\n\n\n\nc", multiline=True) == "a b\n\nc"

    def test_does_not_html_escape(self):
        assert clean_text("R&D <b>") == "R&D <b>"

    @pytest.mark.parametrize(
        "raw,want",
        [
            ("• Built X", "Built X"),
            ("- Built X", "Built X"),
            ("– Built X", "Built X"),
            ("-5% cost", "-5% cost"),
            ("Built full-stack", "Built full-stack"),
        ],
    )
    def test_clean_bullet(self, raw, want):
        assert clean_bullet(raw) == want


class TestContact:
    def test_email_ok_and_domain_lowercased(self):
        assert normalize_email(" Priya.Nair@Example.COM ") == "Priya.Nair@example.com"

    def test_email_mailto_prefix(self):
        assert normalize_email("mailto:a@b.co") == "a@b.co"

    @pytest.mark.parametrize("bad", ["nope", "a@b", "a b@c.com", "@x.com", "a@@x.com"])
    def test_email_rejects(self, bad):
        with pytest.raises(ValueError):
            normalize_email(bad)

    def test_phone_ok(self):
        assert normalize_phone("+91 98765 43210") == "+91 98765 43210"

    @pytest.mark.parametrize("bad", ["abc", "123", "+1 555 0100 ext 5", "1" * 20])
    def test_phone_rejects(self, bad):
        with pytest.raises(ValueError):
            normalize_phone(bad)


class TestUrl:
    def test_bare_domain_gets_https(self):
        assert normalize_url("linkedin.com/in/priya") == "https://linkedin.com/in/priya"

    def test_lowercases_host_drops_fragment(self):
        assert normalize_url("HTTPS://GitHub.com/Priya#x") == "https://github.com/Priya"

    @pytest.mark.parametrize(
        "bad",
        [
            "javascript:alert(1)",
            "data:text/html,x",
            "ftp://x.com",
            "https://u:p@x.com",
            "https://x.com/a b",
            'https://x.com/"onmouseover=',
            "https://localhost",
            "https://x.com:99999999",
        ],
    )
    def test_rejects_unsafe(self, bad):
        with pytest.raises(ValueError):
            normalize_url(bad)

    def test_host_suffix_enforced(self):
        assert normalize_url("https://www.linkedin.com/in/x", ("linkedin.com",))
        with pytest.raises(ValueError):
            normalize_url("https://evil-linkedin.com/in/x", ("linkedin.com",))
        with pytest.raises(ValueError):
            normalize_url("https://linkedin.com.evil.io/in/x", ("linkedin.com",))

    def test_empty_ok(self):
        assert normalize_url("  ") == ""


class TestDates:
    @pytest.mark.parametrize(
        "raw,want",
        [
            ("Mar 2021", "2021-03"),
            ("March 2021", "2021-03"),
            ("sept 2020", "2020-09"),
            ("03/2021", "2021-03"),
            ("2021-3", "2021-03"),
            ("2021", "2021"),
            ("", ""),
        ],
    )
    def test_normalize(self, raw, want):
        assert normalize_partial_date(raw) == want

    @pytest.mark.parametrize("bad", ["Foo 2021", "13/2021", "1800", "2101", "yesterday", "2021-13"])
    def test_normalize_rejects(self, bad):
        with pytest.raises(ValueError):
            normalize_partial_date(bad)

    def test_display(self):
        assert display_date("2021-03") == "Mar 2021" and display_date("2021") == "2021"

    def test_key_ordering_year_only(self):
        assert date_key("2021") < date_key("2021-06") < date_key("2022")
        assert date_key("2021", end=True) > date_key("2021-06")

    @pytest.mark.parametrize(
        "raw,want",
        [
            ("Jan 2020 – Present", ("2020-01", "", True)),
            ("2019-2023", ("2019", "2023", False)),
            ("2019 - 2023", ("2019", "2023", False)),
            ("Mar 2021 - Feb 2022", ("2021-03", "2022-02", False)),
            ("(2018 to 2020)", ("2018", "2020", False)),
            ("2021-03 – 2022-05", ("2021-03", "2022-05", False)),
            ("2019", ("2019", "", False)),
            ("Present", ("", "", True)),
            ("", ("", "", False)),
        ],
    )
    def test_parse_range(self, raw, want):
        assert parse_date_range(raw) == want

    def test_parse_range_rejects_garbage(self):
        with pytest.raises(ValueError):
            parse_date_range("sometime back then")
