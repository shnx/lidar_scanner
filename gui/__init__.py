# Lazy imports — do not import MainWindow here so that gui.i18n
# can be loaded without requiring PyQt5 at package init time.
# main.py imports MainWindow directly via: from gui.main_window import MainWindow

__all__ = ["MainWindow"]
