from syosetu_scraper import parse_args


class TestParseArgs:
    def test_minimal(self):
        args = parse_args(["n3170ed"])
        assert args.ncode == "n3170ed"
        assert args.proxy is None
        assert args.output_dir == "."
        assert args.concurrency == 4
        assert args.delay == 0
        assert args.keep_temp is False
        assert args.max_retries == 3
        assert args.timeout == 15
        assert args.list is False

    def test_proxy(self):
        args = parse_args(["n3170ed", "--proxy", "http://127.0.0.1:7897"])
        assert args.proxy == "http://127.0.0.1:7897"

    def test_all_options(self):
        args = parse_args([
            "https://ncode.syosetu.com/n3170ed/",
            "--proxy", "http://proxy:8080",
            "-o", "/tmp/epub",
            "-c", "2",
            "--delay", "1.5",
            "--keep-temp",
            "--retry", "5",
            "--timeout", "30",
            "--list",
        ])
        assert args.ncode == "https://ncode.syosetu.com/n3170ed/"
        assert args.proxy == "http://proxy:8080"
        assert args.output_dir == "/tmp/epub"
        assert args.concurrency == 2
        assert args.delay == 1.5
        assert args.keep_temp is True
        assert args.max_retries == 5
        assert args.timeout == 30
        assert args.list is True

    def test_short_options(self):
        args = parse_args(["n3170ed", "-o", "./ebooks", "-c", "8"])
        assert args.output_dir == "./ebooks"
        assert args.concurrency == 8

    def test_max_retries_alias(self):
        args = parse_args(["n3170ed", "--max-retries", "10"])
        assert args.max_retries == 10
