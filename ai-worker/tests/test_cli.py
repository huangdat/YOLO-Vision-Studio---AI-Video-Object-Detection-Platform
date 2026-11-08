import pytest

from app import cli


def test_help_does_not_require_or_import_ai_packages(capsys):
    with pytest.raises(SystemExit) as result:
        cli.main(["--help"])
    assert result.value.code == 0
    assert "detect" in capsys.readouterr().out


@pytest.mark.parametrize("classes", ["1,nope", "-1,2", "2,2", ""])
def test_cli_rejects_invalid_class_lists(classes):
    with pytest.raises(SystemExit) as result:
        cli.main(["detect", "--source", "input.mp4", "--source-type", "local", "--classes", classes])
    assert result.value.code == 2


def test_cli_reports_invalid_configuration_without_echoing_sensitive_input(capsys):
    code = cli.main(["detect", "--source", "input.mp4", "--source-type", "local", "--confidence", "2"])
    assert code == 2
    assert "Invalid detection configuration" in capsys.readouterr().err
