import tempfile
from pathlib import Path
from unittest.mock import patch

from pumpfun_trading.cli.main import _build_parser, main, run_ops_cli


def test_build_ops_parser():
    parser = _build_parser()
    args = parser.parse_args(["ops", "status", "--target", ".", "--json"])
    assert args.command == "ops"
    assert args.ops_command == "status"
    assert args.json is True

    args_prune = parser.parse_args(
        ["ops", "prune", "--target", "/tmp", "--days", "15", "--compress"]
    )
    assert args_prune.command == "ops"
    assert args_prune.ops_command == "prune"
    assert args_prune.days == 15
    assert args_prune.compress is True


def test_run_ops_cli_status_and_prune():
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        (td / "test.log").write_text("hello log", encoding="utf-8")
        (td / "test.log.1").write_text("old log", encoding="utf-8")

        parser = _build_parser()

        # Status text table
        args_status = parser.parse_args(["ops", "status", "--target", str(td)])
        run_ops_cli(args_status)

        # Status JSON
        args_status_json = parser.parse_args(
            ["ops", "status", "--target", str(td), "--json"]
        )
        run_ops_cli(args_status_json)

        # Prune and compress
        args_prune = parser.parse_args(
            ["ops", "prune", "--target", str(td), "--days", "0", "--compress"]
        )
        run_ops_cli(args_prune)

        # Main entrypoint dispatch
        with patch("sys.argv", ["pumpfun", "ops", "status", "--target", str(td)]):
            main()
