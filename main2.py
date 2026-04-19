import sys
import socket
import uinput
import time
import os
import warnings
from threading import Thread
from flask import Flask, render_template_string, request
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout,
                             QWidget, QLabel)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPalette, QColor

# Подавляем только предупреждения и ошибки, но не ломаем Flask
warnings.filterwarnings('ignore')

# Отключаем логи Flask через настройки
import logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# Создаем приложение Flask
app = Flask(__name__)

# Create virtual mouse device
try:
    device = uinput.Device([
        uinput.REL_X, uinput.REL_Y,
        uinput.REL_WHEEL,
        uinput.BTN_LEFT, uinput.BTN_RIGHT
    ])
except Exception as e:
    pass

# Queues
move_queue = []
scroll_queue = []

def move_worker():
    while True:
        if move_queue:
            dx, dy = move_queue.pop(0)
            if dx != 0:
                device.emit(uinput.REL_X, int(dx))
            if dy != 0:
                device.emit(uinput.REL_Y, int(dy))
            time.sleep(0.005)
        elif scroll_queue:
            delta = scroll_queue.pop(0)
            if delta != 0:
                device.emit(uinput.REL_WHEEL, int(delta))
                time.sleep(0.005)
        else:
            time.sleep(0.001)

Thread(target=move_worker, daemon=True).start()

def click_left():
    device.emit(uinput.BTN_LEFT, 1)
    time.sleep(0.05)
    device.emit(uinput.BTN_LEFT, 0)

def click_right():
    device.emit(uinput.BTN_RIGHT, 1)
    time.sleep(0.05)
    device.emit(uinput.BTN_RIGHT, 0)

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <title>Mouse Control</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            user-select: none;
            touch-action: none;
        }
        body {
            background: #0a0a0a;
            height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            font-family: system-ui, -apple-system, 'Segoe UI', sans-serif;
        }
        .container {
            width: 100%;
            height: 100%;
            max-width: 500px;
            background: #1a1a1a;
            display: flex;
            flex-direction: column;
            padding: 20px;
            gap: 20px;
        }
        .touchpad {
            flex: 1;
            background: #2c2c2e;
            border-radius: 28px;
            touch-action: none;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        }
        .buttons {
            display: flex;
            gap: 20px;
        }
        button {
            flex: 1;
            aspect-ratio: 1 / 1;
            background: #3a3a3c;
            border: none;
            border-radius: 20px;
            cursor: pointer;
            transition: all 0.1s ease;
        }
        button:active {
            background: #5a5a5c;
            transform: scale(0.96);
        }
        .status {
            text-align: center;
            color: #888;
            font-size: 12px;
            margin-top: 8px;
        }
    </style>
</head>
<body>
<div class="container">
    <div class="touchpad" id="touchpad"></div>
    <div class="buttons">
        <button id="leftBtn"></button>
        <button id="rightBtn"></button>
    </div>
    <div class="status" id="status">⚡ 1 finger tap → left click | 2 fingers → scroll</div>
</div>

<script>
    let lastX = null, lastY = null;
    let lastSendTime = 0;
    const MIN_INTERVAL = 10;

    let tapTimeout = null;
    let lastTapTime = 0;
    let isTapPending = false;
    let startTapX = 0, startTapY = 0;
    let isMovingDuringTap = false;

    let twoFingerStartY = null;
    let twoFingerActive = false;
    let lastScrollY = null;

    const touchpad = document.getElementById('touchpad');
    const statusDiv = document.getElementById('status');

    touchpad.addEventListener('touchstart', function(e) {
        e.preventDefault();
        const rect = touchpad.getBoundingClientRect();
        const touches = e.touches;

        if (touches.length === 1) {
            const x = touches[0].clientX - rect.left;
            const y = touches[0].clientY - rect.top;
            lastX = x;
            lastY = y;
            isMovingDuringTap = false;
            startTapX = x;
            startTapY = y;

            if (tapTimeout) clearTimeout(tapTimeout);
            isTapPending = true;
            tapTimeout = setTimeout(() => {
                if (isTapPending && !isMovingDuringTap) {
                    fetch('/click', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({button: 'left'})
                    }).catch(e => {});
                    statusDiv.textContent = '✅ left click (tap)';
                    setTimeout(() => statusDiv.textContent = '⚡ 1 finger tap → left click | 2 fingers → scroll', 500);
                }
                isTapPending = false;
                tapTimeout = null;
            }, 150);
        }
        else if (touches.length === 2) {
            if (tapTimeout) clearTimeout(tapTimeout);
            isTapPending = false;
            twoFingerActive = true;
            const y1 = touches[0].clientY - rect.top;
            const y2 = touches[1].clientY - rect.top;
            twoFingerStartY = (y1 + y2) / 2;
            lastScrollY = twoFingerStartY;
            statusDiv.textContent = '📜 scrolling (2 fingers)';
        }
    });

    touchpad.addEventListener('touchmove', function(e) {
        e.preventDefault();
        const rect = touchpad.getBoundingClientRect();
        const touches = e.touches;

        if (touches.length === 1 && lastX !== null && !twoFingerActive) {
            const currentX = touches[0].clientX - rect.left;
            const currentY = touches[0].clientY - rect.top;

            if (Math.hypot(currentX - startTapX, currentY - startTapY) > 5) {
                isMovingDuringTap = true;
                if (isTapPending) {
                    clearTimeout(tapTimeout);
                    isTapPending = false;
                }
            }

            const now = Date.now();
            if (now - lastSendTime < MIN_INTERVAL) return;

            let dx = currentX - lastX;
            let dy = currentY - lastY;

            if (dx !== 0 || dy !== 0) {
                fetch('/move', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({dx: dx, dy: dy})
                }).catch(e => {});

                lastX = currentX;
                lastY = currentY;
                lastSendTime = now;
                statusDiv.textContent = '🖱️ mouse moving';
                setTimeout(() => {
                    if (!twoFingerActive && lastX !== null)
                        statusDiv.textContent = '⚡ 1 finger tap → left click | 2 fingers → scroll';
                }, 200);
            }
        }
        else if (touches.length === 2 && twoFingerActive) {
            const y1 = touches[0].clientY - rect.top;
            const y2 = touches[1].clientY - rect.top;
            const avgY = (y1 + y2) / 2;
            let delta = avgY - lastScrollY;
            if (Math.abs(delta) >= 1) {
                let scrollAmount = -delta;
                if (scrollAmount !== 0) {
                    fetch('/scroll', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({delta: scrollAmount})
                    }).catch(e => {});
                }
                lastScrollY = avgY;
                statusDiv.textContent = '📜 scrolling';
                setTimeout(() => {
                    if (twoFingerActive) statusDiv.textContent = '📜 scrolling (2 fingers)';
                }, 100);
            }
        }
    });

    touchpad.addEventListener('touchend', function(e) {
        const remainingTouches = e.touches.length;
        if (remainingTouches === 0) {
            lastX = null;
            lastY = null;
            twoFingerActive = false;
            twoFingerStartY = null;
            lastScrollY = null;
            isMovingDuringTap = false;
            statusDiv.textContent = '⚡ 1 finger tap → left click | 2 fingers → scroll';
        }
        else if (remainingTouches === 1 && twoFingerActive) {
            twoFingerActive = false;
            twoFingerStartY = null;
            lastScrollY = null;
            statusDiv.textContent = '⚡ 1 finger tap → left click | 2 fingers → scroll';
        }
    });

    let doubleTapTimer = null;
    let doubleTapCount = 0;
    touchpad.addEventListener('touchstart', function(e) {
        if (e.touches.length === 1) {
            doubleTapCount++;
            if (doubleTapCount === 1) {
                doubleTapTimer = setTimeout(() => {
                    doubleTapCount = 0;
                }, 250);
            } else if (doubleTapCount === 2) {
                clearTimeout(doubleTapTimer);
                doubleTapCount = 0;
                fetch('/click', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({button: 'right'})
                }).catch(e => {});
                statusDiv.textContent = '🔽 right click (double tap)';
                setTimeout(() => statusDiv.textContent = '⚡ 1 finger tap → left click | 2 fingers → scroll', 500);
                if (tapTimeout) clearTimeout(tapTimeout);
                isTapPending = false;
            }
        }
    });

    document.getElementById('leftBtn').addEventListener('click', () => {
        fetch('/click', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({button: 'left'})}).catch(e => {});
        statusDiv.textContent = '🖱️ left click (button)';
        setTimeout(() => statusDiv.textContent = '⚡ 1 finger tap → left click | 2 fingers → scroll', 500);
    });
    document.getElementById('rightBtn').addEventListener('click', () => {
        fetch('/click', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({button: 'right'})}).catch(e => {});
        statusDiv.textContent = '🔽 right click (button)';
        setTimeout(() => statusDiv.textContent = '⚡ 1 finger tap → left click | 2 fingers → scroll', 500);
    });
</script>
</body>
</html>
'''

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/move', methods=['POST'])
def move():
    data = request.get_json()
    dx = data.get('dx', 0)
    dy = data.get('dy', 0)
    move_queue.append((dx, dy))
    return 'ok'

@app.route('/scroll', methods=['POST'])
def scroll():
    data = request.get_json()
    delta = data.get('delta', 0)
    if delta != 0:
        scroll_queue.append(delta)
    return 'ok'

@app.route('/click', methods=['POST'])
def click():
    data = request.get_json()
    if data.get('button') == 'left':
        click_left()
    else:
        click_right()
    return 'ok'

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Remote Mouse Control")
        self.setFixedSize(600, 400)

        # Dark theme
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1a1a1a;
            }
            QLabel {
                color: #ffffff;
            }
        """)

        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Layout
        layout = QVBoxLayout()
        layout.setSpacing(30)
        layout.setContentsMargins(40, 40, 40, 40)
        central_widget.setLayout(layout)

        # Spacer at top
        layout.addStretch()

        # Main text
        main_label = QLabel("Enter this in your browser on phone")
        main_label.setAlignment(Qt.AlignCenter)
        main_label.setStyleSheet("""
            font-size: 18px;
            color: #ffffff;
            font-weight: normal;
        """)
        layout.addWidget(main_label)

        # IP Address display
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip_address = s.getsockname()[0]
            s.close()
        except:
            ip_address = "127.0.0.1"

        self.ip_label = QLabel(f"http://{ip_address}:9898")
        self.ip_label.setAlignment(Qt.AlignCenter)
        self.ip_label.setStyleSheet("""
            font-size: 24px;
            font-weight: bold;
            color: #00ff88;
            font-family: monospace;
            padding: 20px;
        """)
        layout.addWidget(self.ip_label)

        # Bottom text
        bottom_label = QLabel("You must be connected to the same network")
        bottom_label.setAlignment(Qt.AlignCenter)
        bottom_label.setStyleSheet("""
            font-size: 14px;
            color: #888888;
            margin-top: 20px;
        """)
        layout.addWidget(bottom_label)

        # Spacer at bottom
        layout.addStretch()

        # Start Flask server in separate thread
        self.flask_thread = Thread(target=self.run_flask, daemon=True)
        self.flask_thread.start()

    def run_flask(self):
        # Запускаем Flask с отключенным выводом в консоль
        app.run(host='0.0.0.0', port=9898, debug=False, threaded=True, use_reloader=False)

def main():
    qt_app = QApplication(sys.argv)

    # Set dark theme palette
    qt_app.setStyle('Fusion')
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(26, 26, 26))
    palette.setColor(QPalette.WindowText, QColor(255, 255, 255))
    palette.setColor(QPalette.Base, QColor(44, 44, 46))
    palette.setColor(QPalette.AlternateBase, QColor(58, 58, 60))
    palette.setColor(QPalette.Text, QColor(255, 255, 255))
    palette.setColor(QPalette.Button, QColor(58, 58, 60))
    palette.setColor(QPalette.ButtonText, QColor(255, 255, 255))
    palette.setColor(QPalette.Highlight, QColor(0, 255, 136))
    palette.setColor(QPalette.HighlightedText, QColor(0, 0, 0))
    qt_app.setPalette(palette)

    window = MainWindow()
    window.show()

    sys.exit(qt_app.exec_())

if __name__ == '__main__':
    main()
