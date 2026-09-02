from src.utils.email_normalize import normalize_email_for_dedup


class TestNormalizeEmailForDedup:
    def test_lowercases_and_strips_whitespace(self):
        assert normalize_email_for_dedup("  Test@Example.com  ") == "test@example.com"

    def test_strips_plus_tag_for_any_provider(self):
        assert normalize_email_for_dedup("user+promo@example.com") == "user@example.com"

    def test_strips_dots_only_for_gmail(self):
        assert normalize_email_for_dedup("john.doe@gmail.com") == "johndoe@gmail.com"
        assert normalize_email_for_dedup("john.doe@example.com") == "john.doe@example.com"

    def test_treats_googlemail_as_gmail(self):
        assert (
            normalize_email_for_dedup("john.doe+x@googlemail.com")
            == normalize_email_for_dedup("johndoe@gmail.com")
        )

    def test_combines_dot_and_plus_stripping_for_gmail(self):
        assert normalize_email_for_dedup("j.o.h.n+tag123@gmail.com") == "john@gmail.com"

    def test_no_at_sign_returned_unchanged_lowercased(self):
        assert normalize_email_for_dedup("not-an-email") == "not-an-email"

    def test_empty_input(self):
        assert normalize_email_for_dedup("") == ""
        assert normalize_email_for_dedup(None) == ""
