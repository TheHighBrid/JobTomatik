"""Start the private owner display before API/worker browser operations."""
import os
import subprocess
import time


def main():
    if os.getenv("APPLICATION_BROWSER_HEADLESS", "true").lower() != "false":
        return
    display = os.getenv("DISPLAY", ":99")
    if display != ":99":
        raise RuntimeError("OneHost owner display must be the private :99 display")
    process = subprocess.Popen(
        ["Xvfb", display, "-screen", "0", "1920x1200x24", "-nolisten", "tcp"],
        start_new_session=True,
    )
    for _ in range(50):
        probe = subprocess.run(["xdotool", "getdisplaygeometry"], capture_output=True)
        if probe.returncode == 0:
            return
        if process.poll() is not None:
            raise RuntimeError("The private owner display could not start")
        time.sleep(0.1)
    process.terminate()
    raise RuntimeError("The private owner display did not become ready")


if __name__ == "__main__":
    main()
