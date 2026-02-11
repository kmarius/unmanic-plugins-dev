import os
import subprocess

from kmarius_executor.lib import init_task_data
from kmarius_faststart.lib.types import FileTestData


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


def on_library_management_file_test(data: FileTestData):
    task_data = init_task_data(data)
    path = data.get("path")

    if task_data.get("add_file_to_pending_tasks", False):
        # we only need to test if no other ffmpeg commands run, because we always move the moov atom
        return

    ext = os.path.splitext(path)[1][1:].lower()
    if ext != "mp4":
        return

    # use mp4box metadata if available, otherwise fall back to ffprobe
    if "mp4box" in data["shared_info"]:
        mp4box = data["shared_info"]["mp4box"]
        if "progressive" in mp4box:
            if not mp4box["progressive"]:
                data["issues"].append({
                    'id': "kmarius_faststart_handler",
                    'message': f"MOOV atom not at front (via mp4box): {path}",
                })
                task_data["moov_to_front"] = True
                task_data["add_file_to_pending_tasks"] = True
            return

    if not is_moov_at_front(path):
        data["issues"].append({
            'id': "kmarius_faststart_handler",
            'message': f"MOOV atom not at front: {path}",
        })
        task_data["moov_to_front"] = True
        task_data["add_file_to_pending_tasks"] = True