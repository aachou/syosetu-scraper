import pytest
from core.fetch import sanitize_filename


class TestSanitizeFilename:
    def test_keeps_japanese(self):
        assert sanitize_filename("願わくばこの手に幸福を") == "願わくばこの手に幸福を"

    def test_replaces_invalid_chars(self):
        assert sanitize_filename('file:<>"/\\|?*') == "file_________"

    def test_strips_whitespace(self):
        assert sanitize_filename("  タイトル  ") == "タイトル"

    def test_fallback_empty(self):
        assert sanitize_filename("") == "novel"

    def test_fallback_all_invalid(self):
        assert sanitize_filename("<>:\"|") == "_____"

    def test_mixed(self):
        assert sanitize_filename("夏目漱石『こころ』") == "夏目漱石『こころ』"
