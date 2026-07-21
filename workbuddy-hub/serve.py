from __future__ import annotations

import argparse
import os
import re
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class RangeRequestHandler(SimpleHTTPRequestHandler):
    range: tuple[int, int] | None = None

    def send_head(self):
        path = self.translate_path(self.path)
        if os.path.isdir(path):
            return super().send_head()

        content_type = self.guess_type(path)
        try:
            source = open(path, "rb")
        except OSError:
            self.send_error(404, "File not found")
            return None

        size = os.fstat(source.fileno()).st_size
        self.range = self._parse_range(self.headers.get("Range"), size)
        if self.range:
            start, end = self.range
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            content_length = end - start + 1
        else:
            self.send_response(200)
            content_length = size

        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(content_length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Last-Modified", self.date_time_string(os.fstat(source.fileno()).st_mtime))
        self.end_headers()
        return source

    def copyfile(self, source, outputfile):
        if not self.range:
            return super().copyfile(source, outputfile)

        start, end = self.range
        source.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = source.read(min(64 * 1024, remaining))
            if not chunk:
                break
            try:
                outputfile.write(chunk)
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                break
            remaining -= len(chunk)

    @staticmethod
    def _parse_range(header: str | None, size: int) -> tuple[int, int] | None:
        if not header:
            return None
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", header.strip())
        if not match:
            return None

        start_text, end_text = match.groups()
        if start_text:
            start = int(start_text)
            end = int(end_text) if end_text else size - 1
        elif end_text:
            suffix_length = int(end_text)
            start = max(size - suffix_length, 0)
            end = size - 1
        else:
            return None

        if start >= size or start > end:
            return None
        return start, min(end, size - 1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the WorkBuddy site with MP4 range support.")
    parser.add_argument("--port", type=int, default=4173)
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    handler = lambda *handler_args, **kwargs: RangeRequestHandler(  # noqa: E731
        *handler_args, directory=str(project_root), **kwargs
    )
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"WorkBuddy site: http://127.0.0.1:{args.port}/workbuddy-hub/")
    server.serve_forever()


if __name__ == "__main__":
    main()
