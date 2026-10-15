"""Start the private owner display before API/worker browser operations."""
import os
# fixed local display tools; no shell or owner-controlled executable.
import subprocess  # nosec B404
import time
from pathlib import Path


def display_ready():
    try:
        # literal executable and arguments, no shell.
        return subprocess.run(  # nosec B603
            ["/usr/bin/xdotool", "getdisplaygeometry"], capture_output=True, timeout=2,
        ).returncode == 0
    except subprocess.TimeoutExpired:
        return False


def is_display_process(pid):
    try:
        args = Path(f"/proc/{pid}/cmdline").read_bytes().decode().split("\0")
        return Path(args[0]).name == "Xvfb" and ":99" in args
    except (OSError, ValueError, IndexError):
        return False


# X11 requires these exact protocol paths. Callers check the recorded server PID before unlinking.
# X11 protocol location, not temporary data storage.
DISPLAY_LOCK = Path("/tmp/.X99-lock")  # nosec B108
# private X11 socket protocol location.
DISPLAY_SOCKET = Path("/tmp/.X11-unix/X99")  # nosec B108


def remove_stale_display_files(lock=DISPLAY_LOCK, socket=DISPLAY_SOCKET):
    try:
        pid = int(lock.read_text().strip())
    except (OSError, ValueError):
        pid = 0
    # A recycled PID belonging to Python/init is not the old display server.
    if pid and is_display_process(pid):
        raise RuntimeError("The existing owner display is running but unreachable; refusing to remove its lock")
    lock.unlink(missing_ok=True)
    socket.unlink(missing_ok=True)


def main():
    if os.getenv("APPLICATION_BROWSER_HEADLESS", "true").lower() != "false":
        return
    display = os.getenv("DISPLAY", ":99")
    if display != ":99":
        raise RuntimeError("OneHost owner display must be the private :99 display")
    if display_ready():
        return
    remove_stale_display_files()
    # executable is fixed and display is validated as :99 above.
    process = subprocess.Popen(  # nosec B603
        ["/usr/bin/Xvfb", display, "-screen", "0", "1920x1200x24", "-nolisten", "tcp"],
        start_new_session=True,
    )
    for _ in range(50):
        if display_ready():
            return
        if process.poll() is not None:
            raise RuntimeError("The private owner display could not start")
        time.sleep(0.1)
    process.terminate()
    raise RuntimeError("The private owner display did not become ready")


if __name__ == "__main__":
    main()
