# Synthetic test fixtures only; values here are invented and are not student records.
import unittest

from studenttracker_scope import (
    parse_year_expression,
    validate_graduate_cohort_years,
    validate_request_cohort_years,
)


class StudentTrackerScopeTests(unittest.TestCase):
    def test_request_batches_allow_single_and_nonconsecutive_classes(self):
        self.assertEqual(
            validate_request_cohort_years((2022, 2023, 2024, 2025)),
            (2022, 2023, 2024, 2025),
        )
        self.assertEqual(validate_request_cohort_years((2025,)), (2025,))
        self.assertEqual(validate_request_cohort_years((2023, 2025)), (2023, 2025))
        with self.assertRaisesRegex(ValueError, "at least 1"):
            validate_request_cohort_years(())

    def test_graduate_submission_requires_exactly_one_class(self):
        self.assertEqual(validate_graduate_cohort_years((2025,)), (2025,))
        with self.assertRaisesRegex(ValueError, "exactly one"):
            validate_graduate_cohort_years((2024, 2025))

    def test_year_expression_rejects_duplicates_and_gaps(self):
        self.assertEqual(parse_year_expression("2022-2025"), (2022, 2023, 2024, 2025))
        with self.assertRaisesRegex(ValueError, "repeat"):
            parse_year_expression("2024,2024")
        with self.assertRaisesRegex(ValueError, "consecutive"):
            parse_year_expression("2023,2025")


if __name__ == "__main__":
    unittest.main()
