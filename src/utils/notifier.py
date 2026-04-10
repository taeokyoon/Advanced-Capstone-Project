import platform
import os

def send_notify(title, msg):
    os_type = platform.system()
    
    if os_type == "Windows":
        # 🪟 Windows 환경: 작성해두신 세련된 winotify 토스트 알림 사용
        try:
            from winotify import Notification, audio
            toast = Notification(app_id="거북목 감지기", title=title, msg=msg)
            toast.set_audio(audio.Default, loop=False)
            toast.show()
        except ImportError:
            print("winotify가 설치되지 않아 알림을 띄울 수 없습니다.")
            
    elif os_type == "Darwin": # Mac
        # 🍎 Mac 환경: plyer 대신 가장 안전한 시스템 내장 osascript 방식 사용
        ascript = f'display notification "{msg}" with title "{title}"'
        os.system(f"osascript -e '{ascript}'")