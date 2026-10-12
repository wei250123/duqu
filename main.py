import sys
import os
import atexit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication, QSplashScreen, QMessageBox, QInputDialog, QLineEdit
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap, QFont

from config.config_manager import config_manager
from utils.logger import log_manager
from utils.watchdog import watchdog
from core.security.auth import auth_manager
from core.runtime.gateway_runtime import GatewayRuntime


runtime = None


def setup_directories():
    from config.config_manager import DATA_DIR, LOG_DIR, CONFIG_DIR, DB_DIR, CACHE_DIR
    for d in [DATA_DIR, LOG_DIR, CONFIG_DIR, DB_DIR, CACHE_DIR]:
        os.makedirs(d, exist_ok=True)


def cleanup():
    global runtime
    log_manager.info("系统", "正在执行清理操作...")
    try:
        if runtime:
            runtime.stop()
            runtime = None
        widget_instance = getattr(cleanup, '_widget_instance', None)
        if widget_instance:
            import matplotlib.pyplot as plt
            plt.close('all')
    except Exception as e:
        log_manager.error("系统", f"清理异常: {e}")
    log_manager.info("系统", "程序已退出")


def authenticate_user() -> bool:
    for _ in range(3):
        username, ok = QInputDialog.getText(None, "用户登录", "用户名:")
        if not ok:
            return False
        password, ok = QInputDialog.getText(
            None, "用户登录", "密码:", QLineEdit.EchoMode.Password
        )
        if not ok:
            return False
        success, message = auth_manager.login(username.strip(), password)
        if success:
            return True
        QMessageBox.warning(None, "登录失败", message)
    return False


def main():
    global runtime
    setup_directories()
    log_manager.info("系统", "=" * 60)
    log_manager.info("系统", "工业设备数据采集与MQTT上传网关 v1.0.0 启动中...")
    log_manager.info("系统", "=" * 60)

    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app_font = QFont("Microsoft YaHei", 9)
    app.setFont(app_font)

    watchdog.set_restart_callback(lambda: cleanup())
    app_config = config_manager.app_config
    if not authenticate_user():
        log_manager.error("安全", "用户登录失败或取消")
        sys.exit(1)

    if auth_manager.has_startup_password():
        password, ok = QInputDialog.getText(
            None, "启动验证", "请输入启动密码:",
            QLineEdit.EchoMode.Password
        )
        if not ok or not auth_manager.verify_startup_password(password):
            log_manager.error("系统", "启动密码验证失败")
            sys.exit(1)
        log_manager.info("系统", "启动密码验证成功")

    runtime = GatewayRuntime(app_config)
    try:
        runtime.start()
    except Exception as exc:
        log_manager.fatal("系统", f"后台运行时启动失败: {exc}")
        sys.exit(1)
    
    splash = QSplashScreen()
    splash.showMessage("正在初始化系统组件...", Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignCenter)
    splash.show()
    app.processEvents()

    from ui.main_window import MainWindow
    window = MainWindow()
    splash.finish(window)
    window.show()

    watchdog.enable(check_interval=5.0, heartbeat_timeout=30.0)

    runtime.start_collection()

    log_manager.info("系统", "程序启动完成，等待操作...")

    try:
        exit_code = app.exec()
    except Exception as e:
        log_manager.fatal("系统", f"程序异常退出: {e}")
        exit_code = 1
    finally:
        cleanup()

    sys.exit(exit_code)
    
if __name__ == '__main__':
    atexit.register(cleanup)
    main()
