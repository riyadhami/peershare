from dataclasses import dataclass
from typing import Optional


@dataclass
class ParseResult:
    filename: str
    content_type: str
    file_content: bytes


class MultipartParser:
    """
    Hand-rolled multipart/form-data parser. Deliberately avoids
    cgi.FieldStorage / email.parser / python-multipart so the byte-level
    mechanics (locating headers, then locating the boundary that marks
    the end of the file content) stay visible.
    """

    def __init__(self, data: bytes, boundary: str):
        self.data = data
        self.boundary = boundary

    def parse(self) -> Optional[ParseResult]:
        try:
            # Headers are always ASCII, so it's safe to decode just the
            # leading portion of the payload to hunt for header markers.
            header_end_marker = b"\r\n\r\n"
            header_end = self.data.find(header_end_marker)
            if header_end == -1:
                return None

            header_section = self.data[:header_end].decode("ascii", errors="replace")

            filename_marker = 'filename="'
            filename_start = header_section.find(filename_marker)
            if filename_start == -1:
                return None
            filename_start += len(filename_marker)
            filename_end = header_section.find('"', filename_start)
            filename = header_section[filename_start:filename_end]

            content_type_marker = "Content-Type: "
            content_type_start = header_section.find(content_type_marker, filename_end)
            content_type = "application/octet-stream"
            if content_type_start != -1:
                content_type_start += len(content_type_marker)
                content_type = header_section[content_type_start:].strip()

            content_start = header_end + len(header_end_marker)

            boundary_bytes = f"\r\n--{self.boundary}--".encode("ascii")
            content_end = self.data.find(boundary_bytes, content_start)

            if content_end == -1:
                boundary_bytes = f"\r\n--{self.boundary}".encode("ascii")
                content_end = self.data.find(boundary_bytes, content_start)

            if content_end == -1 or content_end <= content_start:
                return None

            file_content = self.data[content_start:content_end]

            return ParseResult(filename, content_type, file_content)
        except Exception as e:
            print(f"Error parsing multipart data: {e}")
            return None
