import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import override

from unmanic.libs.unplugins.settings import PluginSettings

from kmarius_notify.lib.types import *
from kmarius_notify.lib import logger


class Settings(PluginSettings):
    settings = {
        "smtp_server": "",
        "smtp_port": 465,
        "username": "",
        "show_password": False,
        "password": "",
        "destination": "",
    }
    form_settings = {
        "smtp_server": {"label": "SMTP Server"},
        "smtp_port": {"label": "SMTP Port"},
        "username": {"label": "SMTP username"},
        "show_password": {"label": "Show password"},
        "password": {"label": "SMTP password", "sub_setting": True, "display": "hidden"},
        "destination": {"label": "Destination address"},
    }

    def __init__(self, *args, **kwargs):
        super(Settings, self).__init__(*args, **kwargs)
        if "library_id" in kwargs and kwargs["library_id"] and kwargs["library_id"] > 0:
            self.settings, self.form_settings = {}, {}

    @override
    def get_form_settings(self):
        form_settings = super(Settings, self).get_form_settings()
        if not self.settings_configured:
            # FIXME: in staging, settings_configured is not populated at this point and the corresponding method is private
            self._PluginSettings__import_configured_settings()
        if self.settings_configured:
            if self.settings_configured.get("show_password"):
                if "display" in form_settings["password"]:
                    del form_settings["password"]["display"]
        return form_settings


def on_postprocessor_task_results(data: TaskResultData):
    settings = Settings()
    if not data["task_processing_success"]:
        smtp_server = settings.get_setting("smtp_server")
        smtp_port = int(settings.get_setting("smtp_port"))
        username = settings.get_setting("username")
        password = settings.get_setting("password")
        destination = settings.get_setting("destination")

        msg = MIMEMultipart()
        msg['From'] = username
        msg['To'] = destination
        msg['Subject'] = "Unmanic: Processing failed"
        msg.attach(MIMEText(f"Processing failed: {data["source_data"]["abspath"]}"))

        try:
            with smtplib.SMTP_SSL(smtp_server, smtp_port) as smtp_server:
                smtp_server.login(username, password)
                smtp_server.sendmail(username, destination, msg.as_string())
        except Exception as a:
            logger.error(a)