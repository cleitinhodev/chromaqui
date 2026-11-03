"""Ponto de entrada (usado também pelo PyInstaller)."""
import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from chromaqui.app import main
    main()
