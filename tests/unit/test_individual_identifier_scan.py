# EDU-C2-025 — Unit Tests: individual_identifier_scan (BL-01..BL-04)

import json

from src.services.individual_identifier_scan import (
    contains_individual_identifier,
    contains_individual_identifier_text,
)


class TestContainsIndividualIdentifier:
    def test_clean_aggregated_payload_passes(self):
        """BL-01: a normal aggregated payload is not flagged."""
        raw = json.dumps(
            {
                "reporting_period": "FY2026-Q2",
                "records": [
                    {
                        "training_domain": "harassment_prevention",
                        "business_unit": "Sales",
                        "role_category": "manager",
                        "completion_rate": 82.5,
                    }
                ],
            }
        )
        assert contains_individual_identifier(raw) is False

    def test_forbidden_key_in_record_is_flagged(self):
        """BL-02: a per-employee row (employee_name key) is rejected."""
        raw = json.dumps(
            {
                "reporting_period": "FY2026-Q2",
                "records": [{"employee_name": "Taro Yamada", "completion_rate": 100}],
            }
        )
        assert contains_individual_identifier(raw) is True

    def test_email_anywhere_in_payload_is_flagged(self):
        """BL-03: an email address embedded in any field value is caught."""
        raw = json.dumps(
            {
                "reporting_period": "FY2026-Q2",
                "records": [
                    {
                        "training_domain": "harassment_prevention",
                        "business_unit": "taro.yamada@example.com",
                        "role_category": "manager",
                        "completion_rate": 82.5,
                    }
                ],
            }
        )
        assert contains_individual_identifier(raw) is True

    def test_numeric_identifier_embedded_in_value_is_flagged(self):
        raw = json.dumps(
            {
                "reporting_period": "FY2026-Q2",
                "records": [
                    {
                        "training_domain": "harassment_prevention",
                        "business_unit": "employee-12345678",
                        "role_category": "manager",
                        "completion_rate": 82.5,
                    }
                ],
            }
        )
        assert contains_individual_identifier(raw) is True

    def test_malformed_json_does_not_crash(self):
        """BL-04: malformed JSON is not this scan's problem — returns False, no exception."""
        assert contains_individual_identifier("not json at all") is False

    def test_empty_input_is_clean(self):
        assert contains_individual_identifier("") is False


class TestContainsIndividualIdentifierText:
    def test_clean_markdown_passes(self):
        text = "## Executive Summary\nHarassment prevention is at 82.5% for Sales."
        assert contains_individual_identifier_text(text) is False

    def test_employee_id_cue_phrase_is_flagged(self):
        text = "Employee ID 00231 has not completed the training."
        assert contains_individual_identifier_text(text) is True

    def test_email_in_text_is_flagged(self):
        text = "Contact taro.yamada@example.com for details."
        assert contains_individual_identifier_text(text) is True
