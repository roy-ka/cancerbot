from src.retrieval.router import classify_intent, concept, intervention


class TestIntentClassification:
    def test_concept_query_what_is(self):
        result = classify_intent("What is cancer?")
        assert result == concept

    def test_concept_query_definition(self):
        result = classify_intent("Define metastasis")
        assert result == concept

    def test_concept_query_mechanism(self):
        result = classify_intent("How does the Warburg effect work?")
        assert result == concept

    def test_intervention_query_should_i(self):
        result = classify_intent("Should I take vitamin D?")
        assert result == intervention

    def test_intervention_query_diet(self):
        result = classify_intent("Is a ketogenic diet good for cancer?")
        assert result == intervention

    def test_intervention_query_treatment(self):
        result = classify_intent("What are the treatment options?")
        assert result == intervention

    def test_intervention_wins_on_tie(self):
        # "What is metformin" contains both mechanism (what is) and intervention (metformin is a drug)
        result = classify_intent("What is metformin?")
        assert result == intervention

    def test_default_is_concept(self):
        result = classify_intent("Tell me about cancer research")
        assert result == concept

    def test_empty_string_returns_concept(self):
        result = classify_intent("")
        assert result == concept

    def test_case_insensitive(self):
        result1 = classify_intent("WHAT IS CANCER?")
        result2 = classify_intent("what is cancer?")
        assert result1 == result2 == concept

    def test_whitespace_insensitive(self):
        result = classify_intent("   what   is   cancer   ")
        assert result == concept
