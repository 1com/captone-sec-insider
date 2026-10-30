"""`sentinel schedule`: the daily update as a Windows scheduled task (specs/001-daily-data-refresh,
research R13), and the memory cap a scheduled run puts itself under.

The task runs `wsl.exe -d <distro> --cd <repo> -- <uv> run sentinel update --scheduled` on weekdays
at `update.schedule_time`. A start missed while the computer was off runs as soon as it is back on
(the update catches up every missed day); a start while a run is still going is skipped. It runs
while the user is logged on, as WSL needs. The definition is written as XML in UTF-16, as Task
Scheduler expects, and imported with `schtasks.exe`.

Started by the task, `sentinel update --scheduled` runs itself again inside a systemd scope capped
at `update.memory_max`, like every heavy job on this machine; when the user's systemd cannot make
the scope, it runs uncapped and says so in its log.
"""

import os
import shutil
import subprocess
from collections.abc import Callable
from datetime import date
from xml.sax.saxutils import escape

from sentinel.config import ConfigError, Paths, sources

CAPPED = "SENTINEL_MEMORY_CAPPED"  # set inside the capped scope, so the run does not cap twice
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")
# the fields `show` reports, by their English and German names in `schtasks /Query /V /FO LIST`
SHOWN = {"Status": "Status", "Next Run Time": "Next Run Time", "Last Run Time": "Last Run Time",
         "Last Result": "Last Result", "Nächste Laufzeit": "Next Run Time",
         "Letzte Laufzeit": "Last Run Time", "Letztes Ergebnis": "Last Result"}  # fmt: skip


def _tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise ConfigError(f"{name} not found: Windows Task Scheduler is not reachable from WSL"
                          if name.endswith(".exe") else f"{name} not found on PATH")  # fmt: skip
    return path


def action(p: Paths) -> tuple[str, str]:
    """(program, arguments) the task runs."""
    distro, uv = sources(p)["update"]["distro"], _tool("uv")
    return ("C:\\Windows\\System32\\wsl.exe",
            f"-d {distro} --cd {p.root} -- {uv} run sentinel update --scheduled")  # fmt: skip


def task_xml(p: Paths, at: str, today: date | None = None) -> str:
    """The task definition: weekdays at `at` (HH:MM, local time)."""
    program, arguments = action(p)
    days = "".join(f"<{d} />" for d in WEEKDAYS)
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>EDGAR-SENTINEL: the daily data update (sentinel update --scheduled)</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{today or date.today()}T{at}:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByWeek>
        <DaysOfWeek>{days}</DaysOfWeek>
        <WeeksInterval>1</WeeksInterval>
      </ScheduleByWeek>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <ExecutionTimeLimit>PT8H</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(program)}</Command>
      <Arguments>{escape(arguments)}</Arguments>
    </Exec>
  </Actions>
</Task>
"""


def _check_time(at: str) -> str:
    hour, _, minute = at.partition(":")
    if not (hour.isdigit() and minute.isdigit() and int(hour) < 24 and int(minute) < 60
            and len(minute) == 2):  # fmt: skip
        raise ValueError(f"not a time (HH:MM): {at!r}")
    return f"{int(hour):02d}:{minute}"


def _schtasks(*args: str) -> subprocess.CompletedProcess:
    """Run `schtasks.exe`; its output is in the console code page (cp850 on German Windows)."""
    return subprocess.run([_tool("schtasks.exe"), *args], capture_output=True, text=True,
                          encoding="cp850", errors="replace")  # fmt: skip


def install(p: Paths, at: str | None = None) -> str:
    """Write the task definition to `data/logs/schedule-task.xml` and register it; returns the
    time it runs at."""
    at = _check_time(at or str(sources(p)["update"]["schedule_time"]))
    path = p.logs / "schedule-task.xml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(task_xml(p, at), encoding="utf-16")
    windows = subprocess.run(["wslpath", "-w", str(path)], capture_output=True, text=True,
                             check=True).stdout.strip()  # fmt: skip
    done = _schtasks("/Create", "/TN", sources(p)["update"]["task_name"], "/XML", windows, "/F")
    if done.returncode != 0:
        raise RuntimeError(f"schtasks /Create failed: {(done.stderr or done.stdout).strip()}")
    return at


def remove(p: Paths) -> bool:
    """Delete the task; False when it was not installed."""
    return _schtasks("/Delete", "/TN", sources(p)["update"]["task_name"], "/F").returncode == 0


def show(p: Paths) -> dict[str, str] | None:
    """The task's state, next and last run, and last result; None when it is not installed."""
    done = _schtasks("/Query", "/TN", sources(p)["update"]["task_name"], "/V", "/FO", "LIST")
    if done.returncode != 0:
        return None
    out = {}
    for line in done.stdout.splitlines():
        name, sep, value = line.partition(":")
        key = SHOWN.get(name.strip())
        if sep and key and key not in out:
            out[key] = value.strip()
    return out


def rerun_capped(p: Paths, argv: list[str], echo: Callable[[str], None]) -> int | None:
    """Run this command again inside a systemd scope capped at `update.memory_max`; its exit code,
    or None (with a warning) when the scope cannot be made and the caller should run uncapped."""
    if os.environ.get(CAPPED):
        return None
    cap = sources(p)["update"]["memory_max"]
    scope = ["systemd-run", "--user", "--scope", "--quiet", "-p", f"MemoryMax={cap}"]
    try:
        probe = subprocess.run([*scope, "true"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        probe = subprocess.CompletedProcess(scope, 1, "", str(e))
    if probe.returncode != 0:
        echo(f"warning: no memory cap ({(probe.stderr or 'systemd-run failed').strip()}); "
             "running uncapped")  # fmt: skip
        return None
    return subprocess.run([*scope, *argv], env={**os.environ, CAPPED: "1"}).returncode
