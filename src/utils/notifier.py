import platform

def send_notify(title, msg):
    os_type = platform.system()
    if os_type == "Windows":
        from winotify import Notification, audio
        toast = Notification(app_id="거북목 감지기", title=title, msg=msg)
        toast.set_audio(audio.Default, loop=False)
        toast.show()
    elif os_type == "Darwin": # Mac
        from plyer import notification
        notification.notify(title=title, message=msg, app_name="거북목 감지기")