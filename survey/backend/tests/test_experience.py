"""Validate experience choices independently of either study database."""
from pathlib import Path
import sys
import unittest

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experience import ExperienceEntry, experience_options


class ExperienceTests(unittest.TestCase):
    def selection(self, **updates):
        return dict(version='experience_tags_v1', tool_ids=['piano_keyboard'], example_ids=['played_piece'], **updates)

    def test_tags_need_no_free_text_and_produce_readable_export_fields(self):
        entry = ExperienceEntry(experience_selection=self.selection())
        self.assertEqual(entry.tools, 'Piano / keyboard')
        self.assertEqual(entry.example, 'Practised or performed a song on an instrument')
        self.assertEqual(entry.model_dump()['experience_selection']['tool_ids'], ['piano_keyboard'])
        self.assertEqual(entry.experience_selection.example_other, '')

    def test_other_only_retains_actual_text_and_selection_metadata(self):
        entry = ExperienceEntry(experience_selection=dict(version='experience_tags_v1', tool_ids=[], example_ids=[],
            tools_other='  Harmonica  ', example_other=' I practised a melody on my harmonica. '))
        self.assertEqual(entry.tools, 'Harmonica')
        self.assertEqual(entry.example, 'I practised a melody on my harmonica.')
        self.assertEqual(entry.experience_selection.tool_ids, [])

    def test_empty_unknown_duplicate_and_unsupported_choices_are_rejected(self):
        valid = self.selection()
        for changes in ({'tool_ids': []}, {'example_ids': []}, {'tool_ids': ['made_up']},
                        {'example_ids': ['played_piece', 'played_piece']}, {'version': 'unversioned'},
                        {'tools_other': 'x'*251}, {'unexpected': 'field'}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                ExperienceEntry(experience_selection={**valid, **changes})

    def test_all_tags_and_optional_details_fit_without_truncation(self):
        options = experience_options()
        entry = ExperienceEntry(experience_selection=dict(version=options['version'],
            tool_ids=[item['id'] for item in options['tools']], example_ids=[item['id'] for item in options['examples']],
            tools_other='Additional tools', example_other='Additional experience'))
        self.assertTrue(entry.tools.endswith('Additional tools'))
        self.assertTrue(entry.example.endswith('Additional experience'))
        self.assertGreater(len(entry.tools), 250)
        self.assertEqual(ExperienceEntry.model_validate(entry.model_dump()).model_dump(), entry.model_dump())

    def test_legacy_text_still_validates_and_cannot_be_replaced_by_empty_selections(self):
        entry = ExperienceEntry(tools='Test synth', example='I created a synthesizer patch for a song.')
        self.assertIsNone(entry.experience_selection)
        for values in ({}, {'tools': 'Piano', 'example': 'short'}, {'tools': ' '*5, 'example': 'x'*25}):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                ExperienceEntry(**values)
