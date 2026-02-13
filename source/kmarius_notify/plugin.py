import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from unmanic.libs.unplugins.settings import PluginSettings

from kmarius_notify.lib.types import *
from kmarius_notify.lib import logger


class Settings(PluginSettings):
    settings = {
        "smtp_server": "",
        "smtp_port": 465,
        "username": "",
        "password": "",
        "destination": "",
    }
    form_settings = {
        "smtp_server": {"label": "SMTP Server"},
        "smtp_port": {"label": "SMTP Port"},
        "username": {"label": "SMTP username"},
        "password": {"label": "SMTP password"},
        "destination": {"label": "Destination address"},
    }

    def __init__(self, *args, **kwargs):
        super(Settings, self).__init__(*args, **kwargs)


def on_postprocessor_task_results(data: TaskResultData):
    settings = Settings()
    if not data["task_processing_success"]:
        try:
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

            with smtplib.SMTP_SSL(smtp_server, smtp_port) as smtp_server:
                smtp_server.login(username, password)
                smtp_server.sendmail(username, destination, msg.as_string())

        except Exception as a:
            logger.error(a)