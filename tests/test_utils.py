from __future__ import annotations

import unittest

from app.utils import (
    extract_url,
    html_code,
    html_escape,
    human_duration,
    looks_like_direct_audio_url,
    present_status,
    safe_filename,
    source_filename_from_url,
    source_title_from_url,
)


class UtilsTests(unittest.TestCase):
    def test_extract_url_finds_first_http_url(self) -> None:
        text = 'Скачай https://example.com/music/test.mp3 пожалуйста'
        self.assertEqual(extract_url(text), 'https://example.com/music/test.mp3')

    def test_direct_audio_detection_supports_extended_extensions(self) -> None:
        self.assertTrue(looks_like_direct_audio_url('https://example.com/audio/file.aiff'))
        self.assertFalse(looks_like_direct_audio_url('https://example.com/page.html'))

    def test_source_helpers_decode_url_encoded_names(self) -> None:
        url = 'https://example.com/%D0%A2%D0%B5%D1%81%D1%82%20%D1%82%D1%80%D0%B5%D0%BA.mp3'
        self.assertEqual(source_title_from_url(url), 'Тест трек')
        self.assertEqual(source_filename_from_url(url), 'Тест трек.mp3')

    def test_safe_filename_normalizes_unsafe_characters(self) -> None:
        self.assertEqual(safe_filename('bad:/name?.mp3'), 'bad_name_.mp3')

    def test_html_helpers_escape_dynamic_content(self) -> None:
        self.assertEqual(html_escape('<b>x</b>'), '&lt;b&gt;x&lt;/b&gt;')
        self.assertEqual(html_code('<track>'), '<code>&lt;track&gt;</code>')

    def test_human_duration_formats_compact_time(self) -> None:
        self.assertEqual(human_duration(65), '1:05')
        self.assertEqual(human_duration(3661), '1:01:01')
        self.assertIsNone(human_duration(None))

    def test_present_status_maps_known_values(self) -> None:
        self.assertEqual(present_status('queued'), 'в очереди')
        self.assertEqual(present_status('unknown'), 'unknown')


if __name__ == '__main__':
    unittest.main()
