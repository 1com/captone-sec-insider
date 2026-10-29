"""The weekday schedule (US5): the Windows task's definition, and `install`, `remove`, `show` and
the memory cap through stand-ins for `schtasks.exe`, `wslpath` and `systemd-run`."""

import subprocess
import xml.etree.ElementTree as ET
from datetime import date

import pytest

from sentinel.config import ConfigError
from sentinel.update import schedule

NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
TASK = "EDGAR-SENTINEL\\daily update"
QUERY = """
Folder: \\EDGAR-SENTINEL
HostName:                             PC
TaskName:                             \\EDGAR-SENTINEL\\daily update
Next Run Time:                        30/10/2026 23:00:00
Status:                               Ready
Last Run Time:                        29/10/2026 23:00:01
Last Result:                          0
"""


@pytest.fixture
def windows(monkeypatch):
    """Every command run, answered by `answers[program]` (default: success, no output)."""
    calls, answers = [], {}

    def run(args, **kwargs):
        calls.append([str(a) for a in args])
        code, out = answers.get(args[0].rsplit("/", 1)[-1], (0, ""))
        return subprocess.CompletedProcess(args, code, out, "")

    monkeypatch.setattr(schedule.subprocess, "run", run)
    monkeypatch.setattr(schedule.shutil, "which",
                        lambda name: {"uv": "/home/u/.local/bin/uv",
                                      "schtasks.exe": "/mnt/c/windows/system32/schtasks.exe"
                                      }.get(name))  # fmt: skip
    return calls, answers


def test_the_task_runs_the_update_on_weekday_evenings_and_catches_up_missed_starts(
    tmp_data, windows
):
    root = ET.fromstring(schedule.task_xml(tmp_data, "23:00", date(2026, 10, 29)).split("?>", 1)[1])
    trigger = root.find("t:Triggers/t:CalendarTrigger", NS)
    assert trigger.find("t:StartBoundary", NS).text == "2026-10-29T23:00:00"
    days = [d.tag.split("}")[1] for d in trigger.find("t:ScheduleByWeek/t:DaysOfWeek", NS)]
    assert days == ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    settings = root.find("t:Settings", NS)
    assert settings.find("t:StartWhenAvailable", NS).text == "true"
    assert settings.find("t:MultipleInstancesPolicy", NS).text == "IgnoreNew"
    exec_ = root.find("t:Actions/t:Exec", NS)
    assert exec_.find("t:Command", NS).text == "C:\\Windows\\System32\\wsl.exe"
    assert exec_.find("t:Arguments", NS).text == (
        f"-d Ubuntu --cd {tmp_data.root} -- /home/u/.local/bin/uv run sentinel update --scheduled"
    )


def test_install_remove_and_show_go_through_schtasks(tmp_data, windows):
    calls, answers = windows
    answers["wslpath"] = (0, "\\\\wsl.localhost\\Ubuntu\\x\\schedule-task.xml\n")
    assert schedule.install(tmp_data, "22:30") == "22:30"
    assert calls[-1][1:] == ["/Create", "/TN", TASK, "/XML",
                             "\\\\wsl.localhost\\Ubuntu\\x\\schedule-task.xml", "/F"]  # fmt: skip
    written = (tmp_data.logs / "schedule-task.xml").read_bytes()
    assert written[:2] in (b"\xff\xfe", b"\xfe\xff")  # UTF-16 with its byte order mark
    assert "T22:30:00" in written.decode("utf-16")
    answers["schtasks.exe"] = (0, QUERY)
    assert schedule.show(tmp_data) == {"Next Run Time": "30/10/2026 23:00:00", "Status": "Ready",
                                       "Last Run Time": "29/10/2026 23:00:01",
                                       "Last Result": "0"}  # fmt: skip
    assert calls[-1][1:] == ["/Query", "/TN", TASK, "/V", "/FO", "LIST"]
    assert schedule.remove(tmp_data) is True
    assert calls[-1][1:] == ["/Delete", "/TN", TASK, "/F"]
    answers["schtasks.exe"] = (1, "")
    assert schedule.show(tmp_data) is None  # not installed
    with pytest.raises(ValueError, match="HH:MM"):
        schedule.install(tmp_data, "25:00")


def test_without_schtasks_the_schedule_is_a_config_error(tmp_data, monkeypatch):
    monkeypatch.setattr(schedule.shutil, "which", lambda name: None)
    with pytest.raises(ConfigError, match="Task Scheduler"):
        schedule.show(tmp_data)


def test_a_scheduled_run_caps_its_memory_or_says_it_cannot(tmp_data, windows, monkeypatch):
    calls, answers = windows
    monkeypatch.delenv(schedule.CAPPED, raising=False)
    said = []
    assert schedule.rerun_capped(tmp_data, ["sentinel", "update", "--scheduled"], said.append) == 0
    scope = ["systemd-run", "--user", "--scope", "--quiet", "-p", "MemoryMax=5G"]
    assert calls == [[*scope, "true"], [*scope, "sentinel", "update", "--scheduled"]]
    answers["systemd-run"] = (1, "")
    assert schedule.rerun_capped(tmp_data, ["sentinel"], said.append) is None
    assert said and said[0].startswith("warning: no memory cap")
    monkeypatch.setenv(schedule.CAPPED, "1")  # already inside the scope
    calls.clear()
    assert schedule.rerun_capped(tmp_data, ["sentinel"], said.append) is None and calls == []
