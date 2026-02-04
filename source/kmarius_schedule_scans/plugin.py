#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# TODO: stop thread when uninstalled
# TODO: support timezones

import logging
import re
import threading
from typing import Optional, override

from unmanic.libs.library import Libraries, Library

import schedule

from unmanic.libs.libraryscanner import LibraryScannerManager
from unmanic.libs.plugins import PluginsHandler
from unmanic.libs.unplugins.settings import PluginSettings

try:
    from kmarius_schedule_scans.lib.plugin_types import *
except ImportError:
    from lib.plugin_types import *

PLUGIN_ID = "kmarius_schedule_scans"
THREAD_NAME = "kmarius-schedule-scans"

# Configure plugin logger
logger = logging.getLogger(f"Unmanic.Plugin.{PLUGIN_ID}")


class StoppableThread(threading.Thread):
    """Thread class with a stop() method. The thread itself has to check
    regularly for the stopped() condition."""

    def __init__(self, *args, **kwargs):
        super(StoppableThread, self).__init__(*args, **kwargs)
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def stopped(self):
        return self._stop_event.is_set()

    def sleep(self, seconds: float):
        """Sleep for some time, or until the thread is stopped."""
        return self._stop_event.wait(seconds)


def _have_kmarius_library():
    try:
        from kmarius_library.lib import PLUGIN_ID
        return True
    except ImportError:
        pass
    return False


class Settings(PluginSettings):
    @staticmethod
    def __build_settings():
        settings = {}
        for lib in Libraries().select().where(Libraries.enable_remote_only == False):
            settings.update({
                f"library_{lib.id}_cron_enabled": False,
                f"library_{lib.id}_scan_time": "00:00",
                f"library_{lib.id}_reset_old": "0",
            })
        return settings

    @staticmethod
    def __build_form_settings():
        form_settings = {}
        for lib in Libraries().select().where(Libraries.enable_remote_only == False):
            form_settings.update({
                f"library_{lib.id}_cron_enabled": {
                    "label": f"Enable scans for library '{lib.name}'",
                },
                f"library_{lib.id}_scan_time": {
                    "label": f"Scan time(s) for library '{lib.name}' (format: hh:mm[,hh:mm]...)",
                    "sub_setting": True,
                    "display": "hidden"
                },
                f"library_{lib.id}_reset_old": {
                    "label": f"Number of oldest files that will be re-tested",
                    "sub_setting": True,
                    "display": "hidden"
                },
            })
        return form_settings

    def __init__(self, *args, **kwargs):
        super(Settings, self).__init__(*args, **kwargs)
        self.settings = self.__build_settings()
        self.form_settings = self.__build_form_settings()

    @override
    def get_form_settings(self):
        form_settings = super(Settings, self).get_form_settings()
        if not self.settings_configured:
            # FIXME: in staging, settings_configured is not populated at this point and the corresponding method is private
            self._PluginSettings__import_configured_settings()
        if self.settings_configured:
            for setting, val in self.settings_configured.items():

                if setting.endswith("_cron_enabled"):
                    if val:
                        scan_time = setting.replace("_cron_enabled", "_scan_time")
                        del form_settings[scan_time]["display"]

                        delete_old = setting.replace("_cron_enabled", "_reset_old")
                        if _have_kmarius_library():
                            del form_settings[delete_old]["display"]
        return form_settings


def _get_thread_by_name(name: str) -> Optional[threading.Thread]:
    for thread in threading.enumerate():
        if thread.name == name:
            return thread
    return None


def _get_library_scanner() -> Optional[LibraryScannerManager]:
    return _get_thread_by_name("LibraryScannerManager")


def _start_library_scan(library_id: int):
    settings = Settings()

    scanner = _get_library_scanner()
    if scanner is None:
        logger.error("Could not get library scanner thread")
        return

    if _have_kmarius_library():
        reset_old = settings.get_setting(f"library_{library_id}_reset_old")
        try:
            if int(reset_old) > 0:
                from kmarius_library.lib.timestamps import reset_oldest
                items = reset_oldest(library_id, reset_old)
                logger.info(f"reset {items}")
        except Exception as e:
            logger.error(e)

    library = Library(library_id)
    if library.get_enable_remote_only():
        logger.error(f"Scan scheduled but library is remote: {
        library.get_name()}")
    if not library.get_enable_scanner():
        logger.error(f"Scan scheduled but scanner is disabled: {
        library.get_name()}")
        return

    logger.info(f"Starting scheduled scan of library {library.get_name()}")
    scanner.scan_library_path(library.get_path(), library_id)


def _scheduler_main():
    thread: StoppableThread = threading.current_thread()
    plugins_handler = PluginsHandler()
    sched = schedule.Scheduler()

    settings = Settings()
    for lib in Libraries().select().where(Libraries.enable_remote_only == False):
        if settings.get_setting(f"library_{lib.id}_cron_enabled"):
            for time_str in settings.get_setting(f"library_{lib.id}_scan_time").split(","):
                time_str = time_str.strip()
                if time_str == "":
                    continue
                if re.match(r"^\d{1}:\d{2}$", time_str):
                    time_str = "0" + time_str
                if not re.match(r"^\d{2}:\d{2}$", time_str):
                    logger.error(f"Invalid time format for library {
                    lib.name}: '{time_str}'")
                    continue
                sched.every().day.at(time_str).do(_start_library_scan, lib.id)

    if len(sched.jobs) == 0:
        logger.info("No jobs scheduled, stopping thread.")
        return

    while not thread.stopped():
        sched.run_pending()
        delay = sched.idle_seconds

        if delay > 0:
            hours = int(delay) // 3600
            minutes = (int(delay) % 3600) // 60
            logger.info(f"Next action in {delay:.0f} seconds ({
            hours} hours, {minutes} minutes)")
            thread.sleep(delay)

        if len(plugins_handler.get_plugin_list_filtered_and_sorted(plugin_id=PLUGIN_ID, length=1)) == 0:
            logger.info("Plugin was uninstalled, stopping thread.")
            return


def _restart_scheduler_thread():
    for thread in threading.enumerate():
        if thread.name == THREAD_NAME and hasattr(thread, "stop"):
            thread.stop()
            thread.join()
    StoppableThread(target=_scheduler_main,
                    name=THREAD_NAME, daemon=True).start()


logger.info("Plugin (re-)loaded.")
_restart_scheduler_thread()