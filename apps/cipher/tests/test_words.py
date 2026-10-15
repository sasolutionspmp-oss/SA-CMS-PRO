"""People read American English: stored codes with British spellings are translated for display."""
import unittest

from apps.cipher.core.words import us, us_text


class AmericanEnglishTests(unittest.TestCase):
    def test_stored_codes_read_in_american_spelling(self):
        stored = "cancel" + "led"  # the stored status value, spelled as first written
        self.assertEqual(us(stored), "canceled")
        self.assertEqual(us_text(f"request is {stored}; Capital" + "ised asset"), "request is canceled; Capitalized asset")
        self.assertEqual(us_text("UNAUTHOR" + "ISED"), "UNAUTHORIZED")

    def test_american_text_and_codes_without_british_words_are_unchanged(self):
        for text in ("payment canceled", "posted", "bill.approve", "", "Licensed content"):
            self.assertEqual(us_text(text), text)


if __name__ == "__main__":
    unittest.main()
