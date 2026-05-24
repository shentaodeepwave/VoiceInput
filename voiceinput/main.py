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

    # Timer to let Python process signals
    timer = QTimer()
    timer.timeout.connect(lambda: None)
    timer.start(200)

    VoiceInputApp()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
