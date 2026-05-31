from typer.testing import CliRunner

from ashare_data.cli import app


runner = CliRunner()


def test_ingest_index_weight_cli_passes_arguments(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_ingest_index_weight(settings, start_date: str, end_date: str, index_codes, force: bool):
        captured["start_date"] = start_date
        captured["end_date"] = end_date
        captured["index_codes"] = index_codes
        captured["force"] = force

        class Result:
            index_codes = ["000300.SH", "000905.SH"]
            trade_dates = ["20260525", "20260526"]
            row_count = 4
            skipped = 0
            failed = 0

        return Result()

    monkeypatch.setattr("ashare_data.cli.ingest_index_weight", fake_ingest_index_weight)

    result = runner.invoke(
        app,
        [
            "ingest-index-weight",
            "--start-date",
            "20260525",
            "--end-date",
            "20260526",
            "--index-code",
            "000300.SH",
            "--index-code",
            "000905.SH",
            "--force",
        ],
    )

    assert result.exit_code == 0
    assert "Ingested index codes: 000300.SH, 000905.SH" in result.stdout
    assert captured == {
        "start_date": "20260525",
        "end_date": "20260526",
        "index_codes": ["000300.SH", "000905.SH"],
        "force": True,
    }
