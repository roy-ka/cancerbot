from src.utils.email_templates import TEMPLATES, render


class TestTemplatesShape:
    def test_seven_templates_present(self):
        assert set(TEMPLATES) == {
            "verification",
            "password_reset",
            "account_deleted",
            "delete_account_request",
            "delete_account_scheduled",
            "delete_account_cancelled",
            "fallback_alert",
        }

    def test_every_template_has_a_subject_and_html_body(self):
        for key, entry in TEMPLATES.items():
            assert entry["subject"].strip(), key
            assert "<html" in entry["html"].lower(), key


class TestRender:
    def test_substitutes_name_and_link(self):
        subject, html = render("verification", name="Ada", link="https://x/verify?token=abc")
        assert "Ada" in html
        assert "https://x/verify?token=abc" in html
        assert subject == "Welcome to CancerBot — let's get started 🎗️"

    def test_escapes_name_but_not_link(self):
        # `name` is the only field that ever carries raw user input (a
        # registrant's own first/last name); SendGrid's {{name}} Handlebars used
        # to auto-escape this, so it has to happen here now that we render HTML
        # ourselves. `link` must stay intact — it's a URL, not display text.
        subject, html = render(
            "password_reset",
            name="<script>alert(1)</script>",
            link="https://x/reset?token=a&b=c",
        )
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        assert "https://x/reset?token=a&b=c" in html

    def test_date_substitution(self):
        _, html = render(
            "delete_account_scheduled", name="Ada", date="August 3, 2026", link="https://x/login"
        )
        assert "August 3, 2026" in html

    def test_model_substitution_in_subject_and_body(self):
        subject, html = render("fallback_alert", model="gpt-4o")
        assert "gpt-4o" in subject
        assert "gpt-4o" in html

    def test_missing_field_raises(self):
        import pytest
        with pytest.raises(KeyError):
            render("verification", name="Ada")  # missing `link`

    def test_unknown_template_key_raises(self):
        import pytest
        with pytest.raises(KeyError):
            render("does_not_exist", name="Ada")
