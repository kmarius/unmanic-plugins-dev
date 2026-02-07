import os
import re
from typing import override

from unmanic.libs.library import Libraries, Library
from unmanic.libs.unplugins.settings import PluginSettings

import kmarius_library.lib
from kmarius_library.lib import cache, timestamps, logger, PLUGIN_ID
from kmarius_library.lib.metadata_provider import MetadataProvider, PROVIDERS
from kmarius_library.lib.panel import Panel
from kmarius_library.lib.plugin_types import *
from kmarius_library.lib.timestamps import reset_oldest

cache.init([p.name for p in PROVIDERS])
timestamps.init()


class Settings(PluginSettings):
    @staticmethod
    def __build_settings():
        settings = {
            "extensions": '',
            "ignored_paths": "",
            "incremental_scan_enabled": True,
            "quiet_incremental_scan": True,
            "caching_enabled": True,
        }
        form_settings = {
            "ignored_paths": {
                "input_type": "textarea",
                "label": "Regular expression patterns of paths to ignore - one per line"
            },
            "extensions": {
                "label": "Search library only for extensions",
                "description": "A comma separated list of allowed file extensions."
            },
            "incremental_scan_enabled": {
                "label": "Enable incremental scans (ignore unchanged files)",
            },
            "quiet_incremental_scan": {
                "label": "Don't spam the logs with unchanged files and timestamp updates.",
                'display': 'hidden',
                "sub_setting": True,
            },
            "caching_enabled": {
                "label": "Enable metadata caching"
            },
        }

        settings.update({
            p.setting_name_enabled(): p.default_enabled for p in PROVIDERS
        })
        settings.update({
            "quiet_caching": True,
        })

        form_settings.update({
            p.setting_name_enabled(): {
                'label': f'Enable {p.name} caching',
                "sub_setting": True,
                'display': 'hidden',
            } for p in PROVIDERS
        })
        form_settings.update({
            "quiet_caching": {
                'label': "Don't spam the logs with information on caching.",
                "sub_setting": True,
                'display': 'hidden',
            }
        })

        settings.update({
            "hide_empty": False,
        })
        form_settings.update({
            "hide_empty": {
                "label": "Hide empty directories",
                "description": "Hide directories e.g. if all its contents are filtered. This setting only effects the data panel.",
            },
        })

        return settings, form_settings

    def __init__(self, *args, **kwargs):
        super(Settings, self).__init__(*args, **kwargs)
        self.settings, self.form_settings = self.__build_settings()

    @override
    def get_form_settings(self):
        form_settings = super(Settings, self).get_form_settings()
        if not self.settings_configured:
            # FIXME: in staging, settings_configured is not populated at this point and the corresponding method is private
            self._PluginSettings__import_configured_settings()
        if self.settings_configured:
            if self.settings_configured.get("caching_enabled"):
                for setting, val in form_settings.items():
                    if setting.startswith("cache_"):
                        del val["display"]
                    if setting == "quiet_caching":
                        del val["display"]
            if self.settings_configured.get("incremental_scan_enabled"):
                del form_settings["quiet_incremental_scan"]["display"]
        return form_settings


# combines settings for multiple libraries, because that's how the panel expects them
# it strips library_N_ prefixes from keys and passes the reqeust through to the respective setting object
# TODO: Create a class to represent what files belong to a library using the settings, use it in the panel, use it in kmarius_incremental_scan
class CombinedSettings:
    def __init__(self):
        self.settings = {}
        self.configured_for = []
        self._allowed_extensions = {}
        self._ignored_path_patterns = {}
        for lib in Libraries().select().where(Libraries.enable_remote_only == False):
            self.configured_for.append(lib.id)

    def is_valid(self) -> bool:
        """Check whether the configuration is still valid. If not, it should be re-created."""
        for lib in Libraries().select().where(Libraries.enable_remote_only == False):
            if not lib.id in self.configured_for:
                return False
        return True

    def get_setting(self, key=None):
        match = re.match(r"^library_(\d+)_(.*)", key)
        if match:
            library_id = match.group(1)
            new_key = match.group(2)
            if library_id not in self.settings:
                self.settings[library_id] = Settings(library_id=library_id)
            return self.settings[library_id].get_setting(new_key)
        else:
            logger.error(f"CombinedSettings: unexpected key: {key}")

    def get_allowed_extensions(self, library_id: int) -> list[str]:
        if library_id not in self._allowed_extensions:
            settings = Settings(library_id=library_id)
            extensions = settings.get_setting("extensions").split(",")
            extensions = [ext.strip().lstrip(".") for ext in extensions]
            extensions = [ext for ext in extensions if ext != ""]
            if len(extensions) == 0:
                extensions = None
            self._allowed_extensions[library_id] = extensions
        return self._allowed_extensions[library_id]

    def is_extension_allowed(self, library_id: int, path: str) -> bool:
        extensions = self.get_allowed_extensions(library_id)
        if extensions is None:
            return True
        _, ext = os.path.splitext(path)
        ext = ext.lstrip(".").lower()
        return ext in extensions

    def get_ignored_path_patterns(self, library_id: int) -> list[re.Pattern]:
        if library_id not in self._ignored_path_patterns:
            settings = Settings(library_id=library_id)
            patterns = []
            for regex_pattern in settings.get_setting("ignored_paths").splitlines():
                regex_pattern = regex_pattern.strip()
                if regex_pattern != "" and not regex_pattern.startswith("#"):
                    pattern = re.compile(regex_pattern)
                    patterns.append(pattern)
            self._ignored_path_patterns[library_id] = patterns
        return self._ignored_path_patterns[library_id]

    def is_path_ignored(self, library_id: int, path: str) -> bool:
        regex_patterns = self.get_ignored_path_patterns(library_id)
        for pattern in regex_patterns:
            if pattern.search(path):
                return True
        return False


panel = Panel(CombinedSettings)
combined_settings = CombinedSettings()


def update_cached_metadata(providers: list[MetadataProvider], path: str, quiet: bool = True):
    try:
        mtime = int(os.path.getmtime(path))

        for p in providers:
            if cache.exists(p.name, path, mtime):
                continue

            res = p.run_prog(path)

            if res:
                cache.put(p.name, path, mtime, res)
                if not quiet:
                    logger.info(f"Updating {p.name} data - {path}")
    except Exception as e:
        logger.error(e)


def update_timestamp(library_id: int, path: str):
    try:
        mtime = int(os.path.getmtime(path))
        timestamps.put(library_id, path, mtime)
    except Exception as e:
        logger.error(e)


def is_file_unchanged(library_id: int, path: str) -> bool:
    mtime = int(os.path.getmtime(path))
    stored_timestamp = timestamps.get(library_id, path, reuse_connection=True)
    return stored_timestamp == mtime


def init_shared_data(data: FileTestData, settings: Settings):
    # we attach a settings instance because we need those in kmarius_library_aux
    if not "shared_info" in data:
        data["shared_info"] = {}
    shared_info = data["shared_info"]
    if not "kmarius_library" in shared_info:
        shared_info["kmarius_library"] = settings


def on_library_management_file_test(data: FileTestData):
    settings = Settings(library_id=data.get('library_id'))
    path = data["path"]
    library_id = data["library_id"]

    if not combined_settings.is_extension_allowed(library_id, path):
        data['add_file_to_pending_tasks'] = False
        return

    if combined_settings.is_path_ignored(library_id, path):
        data['add_file_to_pending_tasks'] = False
        return

    init_shared_data(data, settings)

    if settings.get_setting("incremental_scan_enabled"):
        if is_file_unchanged(library_id, path):
            if not settings.get_setting("quiet_incremental_scan"):
                data["issues"].append({
                    'id': PLUGIN_ID,
                    'message': f"unchanged: {path}, library_id={library_id}"
                })
            data['add_file_to_pending_tasks'] = False
            return

    if settings.get_setting("caching_enabled"):
        mtime = int(os.path.getmtime(path))
        quiet = settings.get_setting("quiet_caching")

        for p in PROVIDERS:
            if not settings.get_setting(p.setting_name_enabled()):
                continue

            res = cache.get(p.name, path, mtime, reuse_connection=True)

            if res is None:
                if not quiet:
                    logger.info(f"No cached {p.name} data found, refreshing - {path}")
                res = p.run_prog(path)
                if res:
                    cache.put(p.name, path, mtime, res, reuse_connection=True)
            else:
                if not quiet:
                    logger.info(f"Cached {p.name} data found - {path}")

            if res:
                data["shared_info"][p.name] = res


def on_postprocessor_task_results(data: TaskResultData):
    if data["task_processing_success"] and data["file_move_processes_success"]:
        settings = Settings(library_id=data["library_id"])
        incremental_scan_enabled = settings.get_setting("incremental_scan_enabled")
        caching_enabled = settings.get_setting("caching_enabled")

        library_id = data["library_id"]

        enabled_providers = []

        if caching_enabled:
            for p in PROVIDERS:
                if settings.get_setting(p.setting_name_enabled()):
                    enabled_providers.append(p)

        quiet = settings.get_setting("quiet_caching")

        for path in data["destination_files"]:
            if combined_settings.is_extension_allowed(library_id, path):
                if caching_enabled:
                    update_cached_metadata(enabled_providers, path, quiet)
                if incremental_scan_enabled:
                    # TODO: it could be desirable to not add this file to the db and have it checked again
                    if not settings.get_setting("quiet_incremental_scan"):
                        logger.info(f"Updating timestamp path={
                        path} library_id={library_id}")
                    update_timestamp(library_id, path)


def _prune_timestamps(library_id=None, fraction=1.0, set_last_update=True):
    num_pruned = 0

    if library_id:
        library_ids = [library_id]
    else:
        library_ids = []
        for lib in Libraries().select().where(Libraries.enable_remote_only == False):
            library_ids.append(lib.id)

    for library_id in library_ids:
        library_path = Library(library_id).get_path()

        def keep_entry(path: str) -> bool:
            if not path.startswith(library_path):
                return False
            if not combined_settings.is_extension_allowed(library_id, path):
                return False
            if combined_settings.is_path_ignored(library_id, path):
                return False
            if not os.path.exists(path):
                return False
            return True

        num_pruned += timestamps.check_oldest(library_id, fraction, keep_entry, set_last_update=set_last_update)
    logger.info(f"Pruned {num_pruned} timestamps")


def _prune_metadata(fraction=1.0):
    all_paths = set(timestamps.get_all_paths())

    num_pruned = 0
    for p in PROVIDERS:
        num_pruned += cache.check_oldest(p.name, fraction, lambda path: path in all_paths)
    logger.info(f"Pruned {num_pruned} metadata items")


kmarius_library.lib.prune_timestamps = _prune_timestamps
kmarius_library.lib.prune_metadata = _prune_metadata


def render_frontend_panel(data: PanelData):
    panel.render_frontend_panel(data)


def render_plugin_api(data: PluginApiData):
    panel.render_plugin_api(data)


def emit_scan_start(data: dict):
    logger.info(f"emit_scan_start {data}")

    library_id = data["library_id"]
    frac = data.get("frac", 0.0)

    items = reset_oldest(library_id, frac)
    _prune_timestamps(library_id, frac, set_last_update=False)
    logger.info(f"reset {items}")


def emit_scan_complete(data: dict):
    logger.info(f"emit_scan_complete {data}")

    frac = data.get("frac", 0.0)
    _prune_metadata(frac)