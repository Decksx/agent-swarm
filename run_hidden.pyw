"""Run a scheduled command with a hidden console inherited by its children.

Use pythonw.exe so the launcher itself never opens a console. A hidden console
for Bash keeps its Python and PowerShell children hidden too, including when
the supervisor needs to restart workers.
"""

import os
from pathlib import Path
import subprocess
import sys
import traceback


def main():
    root = Path(__file__).resolve().parent
    control = Path(os.environ.get("SWARM_CONTROL_DIR", root / "control"))
    control.mkdir(parents=True, exist_ok=True)
    with (control / "scheduled_ensure.log").open("a", encoding="utf-8") as log:
        if len(sys.argv) < 2:
            log.write("run_hidden.pyw: missing command\n")
            return 2
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        try:
            return subprocess.call(
                sys.argv[1:], cwd=root, stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT, startupinfo=startup,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
        except OSError:
            traceback.print_exc(file=log)
            return 1


if __name__ == "__main__":
    sys.exit(main())
