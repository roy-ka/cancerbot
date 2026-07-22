"""Tests for the general cancer-category map in nlp_service/synonyms.py.

synonyms.py has no external dependencies, so it's imported directly here
rather than going through the NLP microservice's own (separate) environment.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "nlp_service"))

import synonyms  # noqa: E402


class TestGetCategory:
    def test_brain_cancer_subtypes_share_category(self):
        assert synonyms.get_category("GBM") == "brain cancer"
        assert synonyms.get_category("glioblastoma") == "brain cancer"
        assert synonyms.get_category("glioma") == "brain cancer"
        assert synonyms.get_category("oligodendroglioma") == "brain cancer"

    def test_case_insensitive(self):
        assert synonyms.get_category("gbm") == "brain cancer"
        assert synonyms.get_category("Glioblastoma Multiforme") == "brain cancer"

    def test_already_general_term_maps_to_itself(self):
        assert synonyms.get_category("breast cancer") == "breast cancer"
        assert synonyms.get_category("lung cancer") == "lung cancer"

    def test_leukemia_and_lymphoma_subtypes_map_to_blood_cancer(self):
        for term in ("AML", "acute myeloid leukemia", "CLL", "hodgkin lymphoma", "DLBCL", "multiple myeloma"):
            assert synonyms.get_category(term) == "blood cancer"

    def test_non_cancer_entity_has_no_category(self):
        assert synonyms.get_category("Mebendazole") is None
        assert synonyms.get_category("EGFR") is None
        assert synonyms.get_category("chemotherapy") is None

    def test_unknown_term_has_no_category(self):
        assert synonyms.get_category("not a real cancer term") is None

    def test_retinoblastoma_maps_to_eye_cancer(self):
        assert synonyms.get_category("retinoblastoma") == "eye cancer"
