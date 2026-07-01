import json
import os
import socket
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer

from p2p.file_sharer import FileSharer
from p2p.multipart_parser import MultipartParser

UPLOAD_CHUNK_SIZE = 4096


class ThreadPoolHTTPServer(HTTPServer):
    """
    http.server hands each accepted connection to process_request(); by
    default that runs serially on the main thread. We override it to
    submit the work to a bounded thread pool instead, mirroring the
    Java version's `Executors.newFixedThreadPool(10)` handed to
    HttpServer.setExecutor(), rather than spawning one unbounded thread
    per connection.
    """

    def __init__(self, server_address, handler_class, max_workers: int = 10):
        super().__init__(server_address, handler_class)
        self.executor = ThreadPoolExecutor(max_workers=max_workers)

    def process_request(self, request, client_address):
        self.executor.submit(self._process_request_thread, request, client_address)

    def _process_request_thread(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)

    def shutdown_and_wait(self):
        self.executor.shutdown(wait=True)


class peershareRequestHandler(BaseHTTPRequestHandler):
    # The shared FileSharer / upload_dir are attached to the server
    # instance by FileController, since a new handler is built per request.

    def _send_text(self, status: int, body: str, content_type: str = "text/plain"):
        encoded = body.encode("utf-8")
        self.send_response(status)
        self._add_cors_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _add_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type,Authorization")

    def do_OPTIONS(self):
        self.send_response(204)
        self._add_cors_headers()
        self.end_headers()

    def do_POST(self):
        if self.path == "/upload" or self.path.startswith("/upload"):
            self._handle_upload()
        else:
            self._send_text(404, "Not Found")

    def do_GET(self):
        if self.path.startswith("/download/"):
            self._handle_download()
        else:
            self._send_text(404, "Not Found")

    # ---- /upload ----------------------------------------------------

    def _handle_upload(self):
        content_type = self.headers.get("Content-Type")
        if not content_type or not content_type.startswith("multipart/form-data"):
            self._send_text(400, "Bad Request: Content-Type must be multipart/form-data")
            return

        try:
            boundary = content_type.split("boundary=", 1)[1]

            content_length = int(self.headers.get("Content-Length", 0))
            request_data = self.rfile.read(content_length)

            parser = MultipartParser(request_data, boundary)
            result = parser.parse()

            if result is None:
                self._send_text(400, "Bad Request: Could not parse file content")
                return

            filename = result.filename.strip() if result.filename else ""
            if not filename:
                filename = "unnamed-file"

            unique_filename = f"{uuid.uuid4()}_{os.path.basename(filename)}"
            file_path = os.path.join(self.server.upload_dir, unique_filename)

            with open(file_path, "wb") as f:
                f.write(result.file_content)

            port = self.server.file_sharer.offer_file(file_path)

            threading.Thread(
                target=self.server.file_sharer.start_file_server,
                args=(port,),
                daemon=True,
            ).start()

            self._send_text(200, json.dumps({"port": port}), content_type="application/json")

        except Exception as e:
            print(f"Error processing file upload: {e}")
            self._send_text(500, f"Server error: {e}")

    # ---- /download/{port} --------------------------------------------

    def _handle_download(self):
        port_str = self.path.rsplit("/", 1)[-1]

        try:
            port = int(port_str)
        except ValueError:
            self._send_text(400, "Bad Request: Invalid port number")
            return

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as peer_socket:
                peer_socket.connect(("localhost", port))

                tmp_fd, tmp_path = tempfile.mkstemp(prefix="download-", suffix=".tmp")
                filename = "downloaded-file"

                try:
                    with os.fdopen(tmp_fd, "wb") as tmp_file:
                        # Read the "Filename: <name>\n" header byte-by-byte,
                        # same approach as the Java version, so we don't
                        # accidentally consume file bytes past the newline.
                        header_bytes = bytearray()
                        while True:
                            b = peer_socket.recv(1)
                            if not b or b == b"\n":
                                break
                            header_bytes += b

                        header = header_bytes.decode("utf-8", errors="replace").strip()
                        if header.startswith("Filename: "):
                            filename = header[len("Filename: "):]

                        while True:
                            chunk = peer_socket.recv(UPLOAD_CHUNK_SIZE)
                            if not chunk:
                                break
                            tmp_file.write(chunk)

                    file_size = os.path.getsize(tmp_path)
                    self.send_response(200)
                    self._add_cors_headers()
                    self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Content-Length", str(file_size))
                    self.end_headers()

                    with open(tmp_path, "rb") as f:
                        while True:
                            chunk = f.read(UPLOAD_CHUNK_SIZE)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                finally:
                    os.remove(tmp_path)

        except OSError as e:
            print(f"Error downloading file from peer: {e}")
            self._send_text(500, f"Error downloading file: {e}")

    def log_message(self, format, *args):
        # Keep stdout focused on the app's own status messages.
        pass


class FileController:
    def __init__(self, port: int):
        self.file_sharer = FileSharer()
        self.upload_dir = os.path.join(tempfile.gettempdir(), "peershare-uploads")
        os.makedirs(self.upload_dir, exist_ok=True)

        self.server = ThreadPoolHTTPServer(("", port), peershareRequestHandler, max_workers=10)
        self.server.file_sharer = self.file_sharer
        self.server.upload_dir = self.upload_dir

    def start(self):
        self._serve_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._serve_thread.start()
        print(f"API server started on port {self.server.server_address[1]}")

    def stop(self):
        self.server.shutdown()
        self.server.shutdown_and_wait()
        self.server.server_close()
        print("server stopped")
