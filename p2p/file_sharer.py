import os
import socket
import threading

from p2p import upload_utils


class FileSharer:
    """
    Hands out a one-time-use port for each uploaded file, then runs a
    tiny raw-socket file server on that port so a peer can connect and
    stream the bytes down directly (no HTTP involved in the transfer).
    """

    def __init__(self):
        self.available_files = {}

    def offer_file(self, file_path: str) -> int:
        while True:
            port = upload_utils.generate_code()
            if port not in self.available_files:
                self.available_files[port] = file_path
                return port

    def start_file_server(self, port: int) -> None:
        file_path = self.available_files.get(port)
        if file_path is None:
            print(f"No file associated with port: {port}")
            return

        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server_socket.bind(("", port))
            server_socket.listen(1)
            print(f"Serving file '{os.path.basename(file_path)}' on port {port}")

            client_socket, client_address = server_socket.accept()
            print(f"Client connected: {client_address[0]}")

            threading.Thread(
                target=self._send_file,
                args=(client_socket, file_path),
                daemon=True,
            ).start()
        except OSError as e:
            print(f"Error starting file server on port {port}: {e}")
        finally:
            server_socket.close()

    @staticmethod
    def _send_file(client_socket: socket.socket, file_path: str) -> None:
        filename = os.path.basename(file_path)
        try:
            # Custom one-line header so the receiving end knows the
            # original filename before the raw file bytes start.
            header = f"Filename: {filename}\n".encode("utf-8")
            client_socket.sendall(header)

            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(4096)
                    if not chunk:
                        break
                    client_socket.sendall(chunk)

            print(f"File '{filename}' sent to {client_socket.getpeername()[0]}")
        except OSError as e:
            print(f"Error sending file to client: {e}")
        finally:
            client_socket.close()
