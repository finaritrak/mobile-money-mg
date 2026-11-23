from mobile_money_mg.__main__ import main


def test_demo_runs(capsys):
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "SUCCESS" in out and "FAILED" in out and "EXPIRED" in out


def test_demo_custom_numbers(capsys):
    assert main(["0391234567"]) == 0
    assert "unknown operator" in capsys.readouterr().out
