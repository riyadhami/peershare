"""peershare - P2P File Sharing Application (Python port)."""
import signal
import sys

from p2p.file_controller import FileController


def main():
    try:
        file_controller = FileController(8080)
        file_controller.start()

        print("peershare server started on port 8080")
        print("UI available at http://localhost:3000")

        def handle_shutdown(signum, frame):
            print("Shutting down server...")
            file_controller.stop()
            sys.exit(0)

        signal.signal(signal.SIGINT, handle_shutdown)
        signal.signal(signal.SIGTERM, handle_shutdown)

        print("Press Enter to stop the server")
        input()

        print("Shutting down server...")
        file_controller.stop()

    except OSError as e:
        print(f"Error starting server: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
