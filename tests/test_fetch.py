import asyncio
import pytest
from unittest.mock import AsyncMock, Mock, patch

from core.fetch import get_soup, get_novel_metadata, fetch_single_chapter, _clean_html


SAMPLE_CHAPTER_LIST_HTML = """
<html>
<head><title>テスト小説 - なろう</title></head>
<body>
<h1 class="p-novel__title">テスト小説</h1>
<div class="p-novel__author">テスト作者</div>
<div class="p-eplist">
<div class="p-eplist__chapter-title">第一章</div>
<dl class="p-eplist__sublist"><a href="/n0000xx/1/">第一話 始まり</a></dl>
<dl class="p-eplist__sublist"><a href="/n0000xx/2/">第二話 展開</a></dl>
<div class="p-eplist__chapter-title">第二章</div>
<dl class="p-eplist__sublist"><a href="/n0000xx/3/">第三話 クライマックス</a></dl>
</div>
</body>
</html>
"""

SAMPLE_CHAPTER_HTML = """
<html>
<body>
<div class="p-novel__text">
<p>これはテスト本文です。</p>
<p>改行された\n別の行。</p>
</div>
</body>
</html>
"""


@pytest.fixture
def semaphore():
    return asyncio.Semaphore(1)


@pytest.fixture
def mock_session():
    session = Mock()
    session.get = Mock()
    return session


def _mock_response(text: str, status: int = 200):
    resp = AsyncMock()
    resp.raise_for_status = Mock()
    resp.text = AsyncMock(return_value=text)
    if status >= 400:
        from aiohttp import ClientResponseError
        resp.raise_for_status.side_effect = ClientResponseError(None, None, status=status)
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


class TestGetSoup:
    @pytest.mark.asyncio
    async def test_success(self, mock_session, semaphore):
        cm = _mock_response("<html><body>OK</body></html>")
        mock_session.get.return_value = cm

        result = await get_soup("http://example.com", mock_session, semaphore)
        assert result is not None
        assert result.text.strip() == "OK"

    @pytest.mark.asyncio
    async def test_retry_then_succeed(self, mock_session, semaphore):
        from aiohttp import ClientError
        fail_cm = _mock_response("", 500)
        fail_cm.__aenter__ = AsyncMock(side_effect=ClientError("fail"))
        ok_cm = _mock_response("<html><body>OK</body></html>")

        mock_session.get.side_effect = [fail_cm, fail_cm, ok_cm]

        result = await get_soup("http://example.com", mock_session, semaphore)
        assert result.text.strip() == "OK"
        assert mock_session.get.call_count == 3

    @pytest.mark.asyncio
    async def test_all_retries_fail(self, mock_session, semaphore):
        from aiohttp import ClientError
        fail_cm = _mock_response("", 500)
        fail_cm.__aenter__ = AsyncMock(side_effect=ClientError("always fail"))
        mock_session.get.return_value = fail_cm

        with pytest.raises(Exception):
            await get_soup("http://example.com", mock_session, semaphore, max_attempts=2)
        assert mock_session.get.call_count == 2


class TestGetNovelMetadata:
    @pytest.mark.asyncio
    async def test_parse_metadata(self, mock_session, semaphore):
        cm = _mock_response(SAMPLE_CHAPTER_LIST_HTML)
        mock_session.get.return_value = cm

        title, author, volumes = await get_novel_metadata(
            "https://ncode.syosetu.com/n0000xx/", mock_session, semaphore
        )

        assert title == "テスト小説"
        assert author == "テスト作者"
        assert len(volumes) == 2
        assert volumes[0][0] == "第一章"
        assert len(volumes[0][1]) == 2
        assert volumes[0][1][0]["title"] == "第一話 始まり"
        assert volumes[1][0] == "第二章"
        assert len(volumes[1][1]) == 1

    @pytest.mark.asyncio
    async def test_no_chapter_list(self, mock_session, semaphore):
        html = """
        <html><body>
        <h1 class="p-novel__title">単ページ</h1>
        <div class="p-novel__author">作者A</div>
        </body></html>
        """
        cm = _mock_response(html)
        mock_session.get.return_value = cm

        title, author, volumes = await get_novel_metadata(
            "https://ncode.syosetu.com/n0000xx/", mock_session, semaphore
        )

        assert title == "単ページ"
        assert len(volumes) == 1
        assert volumes[0][0] is None
        assert volumes[0][1][0]["index"] == 0


class TestFetchSingleChapter:
    @pytest.mark.asyncio
    async def test_fetch_success(self, mock_session, semaphore):
        cm = _mock_response(SAMPLE_CHAPTER_HTML)
        mock_session.get.return_value = cm

        result = await fetch_single_chapter(
            {"index": 0, "title": "第一話", "url": "https://ncode.syosetu.com/n0000xx/1/"},
            mock_session, semaphore,
        )

        assert result["index"] == 0
        assert result["title"] == "第一話"
        assert result["error"] is None
        assert "テスト本文" in result["html"]

    @pytest.mark.asyncio
    async def test_fetch_fails_gracefully(self, mock_session, semaphore):
        cm = _mock_response("", 500)
        cm.__aenter__ = AsyncMock(side_effect=Exception("not found"))
        mock_session.get.return_value = cm

        result = await fetch_single_chapter(
            {"index": 5, "title": "欠番", "url": "https://ncode.syosetu.com/n0000xx/5/"},
            mock_session, semaphore, max_attempts=2,
        )

        assert result["index"] == 5
        assert result["html"] == ""
        assert "not found" in result["error"]


class TestCleanHtml:
    def test_basic_paragraphs(self):
        html = "<p>一つ目の段落</p><p>二つ目の段落</p>"
        result = _clean_html(html)
        assert 'class="paragraph"' in result
        assert "一つ目の段落" in result
        assert "二つ目の段落" in result

    def test_line_splitting(self):
        html = "<p>行1\n行2</p>"
        result = _clean_html(html)
        lines = [l for l in result.split("</p>") if "行" in l]
        assert len(lines) == 2

    def test_removes_empty_lines(self):
        html = "<p>  </p><p>本文</p>"
        result = _clean_html(html)
        # "  " (empty) should be removed, only "本文" remains
        assert "本文" in result
        # Check that there's only one paragraph with content
        assert result.count("paragraph") == 1
