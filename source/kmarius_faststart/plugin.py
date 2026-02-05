import logging
import os
import subprocess

from kmarius_executor.lib import lazy_init

logger = logging.getLogger("Unmanic.Plugin.kmarius_faststart_handler")


def is_moov_at_front(path: str) -> bool:
    command = ["ffprobe", "-v", "trace", path]
    pipe = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    for line in pipe.stdout:
        if b"moov" in line:
            pipe.kill()
            return True
        if b"mdat" in line:
            pipe.kill()
            return False
    return False


def on_library_management_file_test(data: dict):
    mydata = lazy_init(data, logger)
    path = data.get("path")

    if mydata.get("add_file_to_pending_tasks", False):
        # we only need to test if no other ffmpeg commands run, because we always move the moov atom
        return

    ext = os.path.splitext(path)[-1][1:].lower()
    if ext == "mp4" and not is_moov_at_front(path):
        data["issues"].append({
            'id': "kmarius_faststart_handler",
            'message': f"MOOV atom not at front: {path}",
        })
        mydata["moov_to_front"] = True
        mydata["add_file_to_pending_tasks"] = True