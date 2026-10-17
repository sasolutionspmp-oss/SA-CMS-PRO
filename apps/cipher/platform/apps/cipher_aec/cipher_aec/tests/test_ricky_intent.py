"""Literal source-topic preparation, not semantic retrieval or model authority."""

import unittest

from cipher_aec.ricky.engine import question_keywords


class RickyTaskIntentTests(unittest.TestCase):
    def test_only_known_leading_task_instructions_are_removed(self):
        questions = (
            "Please create a task to review the trial labor rate.",
            "Draft a Task to check the trial labor rate.",
            "Propose task to confirm the trial labor rate.",
            "Could you please draft a task to inspect the trial labor rate?",
            "Create a Task about the trial labor rate.",
            "Task regarding the trial labor rate.",
            "Task for the trial labor rate.",
        )
        for question in questions:
            with self.subTest(question=question):
                self.assertEqual("trial labor rate", question_keywords(question))

    def test_ordinary_literal_questions_remain_unchanged(self):
        self.assertEqual("review meeting", question_keywords("When is the review meeting?"))
        self.assertEqual("trial labor rate", question_keywords("What is trial labor rate?"))
        self.assertEqual("draft task specifications", question_keywords("Where are the draft task specifications?"))

    def test_command_words_inside_source_topic_are_preserved(self):
        self.assertEqual("trial draft task review notes", question_keywords("Where are trial draft task review notes?"))
        self.assertEqual("draft task procedure", question_keywords("Create a task to review the draft task procedure."))
        self.assertEqual("task creation guide", question_keywords("Please create a task to review the task creation guide."))

    def test_unrecognized_or_anchorless_requests_never_become_empty_queries(self):
        for question in ("Please create a task to review", "Draft a task to check the", "Task about the", "Task for", "Create a task to delete all records"):
            with self.subTest(question=question):
                query = question_keywords(question)
                self.assertTrue(query.strip())
                self.assertTrue(any(word in query.casefold() for word in ("task", "create", "draft")))

    def test_literals_remain_bounded_and_deduplicated(self):
        self.assertEqual("trial labor rate", question_keywords("Draft a task to review trial trial labor rate"))
        self.assertLessEqual(len(question_keywords("Propose a task to inspect " + "literal " * 200)), 500)


if __name__ == "__main__":
    unittest.main()
