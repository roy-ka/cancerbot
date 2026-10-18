from src.utils.email_templates import TEMPLATES, render


class TestTemplatesShape:
    def test_ten_templates_present(self):
        assert set(TEMPLATES) == {
            "login_code",
            "account_deleted",
            "delete_account_request",
            "delete_account_scheduled",
            "delete_account_cancelled",
            "daily_admin_digest",
            "weekly_admin_digest",
            "email_change_request",
            "email_change_verification",
            "email_changed_notice",
        }

    def test_every_template_has_a_subject_and_html_body(self):
        for key, entry in TEMPLATES.items():
            assert entry["subject"].strip(), key
            assert "<html" in entry["html"].lower(), key


class TestRender:
    def test_substitutes_name_and_link(self):
        _, html = render("email_change_request", name="Ada", link="https://x/change-email?token=abc")
        assert "Ada" in html
        assert "https://x/change-email?token=abc" in html

    def test_login_code_is_in_the_body_but_not_the_subject(self):
        """email_brevo.py logs subjects, so a code there would be logged."""
        subject, html = render("login_code", name="Ada", code="123456", minutes=10)
        assert "123456" not in subject
        assert "123456" in html
        assert "10 minutes" in html

    def test_escapes_name_but_not_link(self):
        # `name` is the only field that ever carries raw user input (a
        # registrant's own first/last name); SendGrid's {{name}} Handlebars used
        # to auto-escape this, so it has to happen here now that we render HTML
        # ourselves. `link` must stay intact — it's a URL, not display text.
        subject, html = render(
            "email_change_request",
            name="<script>alert(1)</script>",
            link="https://x/change-email?token=a&b=c",
        )
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        assert "https://x/change-email?token=a&b=c" in html

    def test_date_substitution(self):
        _, html = render(
            "delete_account_scheduled", name="Ada", date="August 3, 2026", link="https://x/login"
        )
        assert "August 3, 2026" in html
    def test_missing_field_raises(self):
        import pytest
        with pytest.raises(KeyError):
            render("email_change_request", name="Ada")  # missing `link`

    def test_unknown_template_key_raises(self):
        import pytest
        with pytest.raises(KeyError):
            render("does_not_exist", name="Ada")

    def test_daily_admin_digest_renders(self):
        subject, html = render(
            "daily_admin_digest",
            date="September 6, 2026",
            new_users=3, new_conversations=10, messages_sent=42,
            fallback_triggered=1, bug_reports=1, feedback=2,
            axiom_section="<p>ok</p>",
        )
        assert "September 6, 2026" in subject
        assert "42" in html
        assert "<p>ok</p>" in html

    def test_email_change_request_renders(self):
        subject, html = render("email_change_request", name="Ada", link="https://x/change-email?token=a")
        assert "Ada" in html
        assert "https://x/change-email?token=a" in html

    def test_email_change_verification_renders(self):
        subject, html = render(
            "email_change_verification",
            name="Ada", old_email="old@example.com", link="https://x/confirm-email-change?token=a",
        )
        assert "old@example.com" in html
        assert "https://x/confirm-email-change?token=a" in html

    def test_email_changed_notice_renders(self):
        subject, html = render(
            "email_changed_notice",
            name="Ada", new_email="new@example.com", link="https://x/revert-email?token=a",
        )
        assert "new@example.com" in html
        assert "https://x/revert-email?token=a" in html

    def test_weekly_admin_digest_renders(self):
        subject, html = render(
            "weekly_admin_digest",
            date="September 6, 2026",
            new_users=3, new_conversations=10, messages_sent=42,
            fallback_triggered=1, total_users=100,
        )
        assert "September 6, 2026" in subject
        assert "100" in html
