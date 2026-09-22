"""Tests for extraction.py's entity extraction and spelling correction.

Regression coverage for a real bug: en_core_sci_sm (trained on clean
scientific abstracts) tagged the pronoun "I" and the verb "meant" as
entities on casual first-person conversational text — e.g. "I meant how
many I can have in total?" — polluting every downstream search (PubMed,
CrossRef, ClinicalTrials, OpenSearch) with junk terms. The old STOP_ENTS
list is a hand-maintained word list that can only ever catch words already
seen; this fix generalizes by requiring an entity to contain at least one
content-word token (NOUN/PROPN/ADJ/NUM) per scispaCy's own POS tagger.
"""
from extraction import extract_entities, correct_spelling_text


class TestExtractEntitiesDropsFunctionWordFalsePositives:
    def test_the_exact_reported_bug(self):
        result = extract_entities(
            "I meant how many I can have in total? Now I am on first line medication"
        )
        entities_lower = {e.lower() for e in result["entities"]}
        assert "i" not in entities_lower
        assert "meant" not in entities_lower
        # The real content is still there
        assert "first line" in result["entities"]

    def test_pronoun_alone_is_dropped(self):
        result = extract_entities("How many treatments lines do I have?")
        entities_lower = {e.lower() for e in result["entities"]}
        assert "i" not in entities_lower
        assert "treatments" in result["entities"]

    def test_bare_verb_entity_is_dropped(self):
        result = extract_entities("Does glioblastoma metastasize to the spine?")
        entities_lower = {e.lower() for e in result["entities"]}
        assert "metastasize" not in entities_lower
        assert "glioblastoma" in result["entities"]
        assert "spine" in result["entities"]


class TestExtractEntitiesKeepsRealMedicalTerms:
    def test_named_entity_with_proper_noun(self):
        result = extract_entities("What is the Warburg effect in glioblastoma?")
        assert "Warburg effect" in result["entities"]
        assert "glioblastoma" in result["entities"]

    def test_multi_word_noun_phrase(self):
        result = extract_entities("What happens if the tumor relapses after chemotherapy?")
        assert any("relapse" in e.lower() for e in result["entities"])
        assert "chemotherapy" in result["entities"]

    def test_stage_with_roman_numeral(self):
        result = extract_entities("I was diagnosed with stage IV pancreatic cancer")
        assert "stage IV" in result["entities"]
        assert "pancreatic cancer" in result["entities"]
        entities_lower = {e.lower() for e in result["entities"]}
        assert "i" not in entities_lower
        assert "diagnosed" not in entities_lower

    def test_entity_groups_shape_unchanged(self):
        result = extract_entities("What is glioblastoma?")
        assert result["entity_groups"]
        group = result["entity_groups"][0]
        assert set(group.keys()) == {"term", "synonyms", "category"}

    def test_empty_text_returns_empty(self):
        result = extract_entities("")
        assert result["entities"] == []
        assert result["entity_groups"] == []


class TestCorrectSpellingText:
    def test_empty_text(self):
        result = correct_spelling_text("")
        assert result["changes"] == []

    def test_corrects_a_misspelled_word(self):
        result = correct_spelling_text("This is definately true")
        assert any(c["from"].lower() == "definately" for c in result["changes"])

    def test_protects_recognized_medical_entities(self):
        # glioblastoma is a real scispaCy entity — must not be "corrected" away
        result = correct_spelling_text("What is glioblastoma?")
        assert "glioblastoma" in result["corrected"].lower()
