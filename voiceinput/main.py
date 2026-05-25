import signal
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app import VoiceInputApp


def main():
    signal.signal(signal.SIGINT, lambda *a: QApplication.quit())

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("VoiceInput")

    # Timer to let Python process signals — store on app to prevent GC
    app._signal_timer = QTimer()
    app._signal_timer.timeout.connect(lambda: None)
    app._signal_timer.start(200)

    VoiceInputApp()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
