# peershare (Python)

Python port of the original Java peershare P2P file-sharing backend. Stdlib only — no Flask/FastAPI, no `python-multipart`.

## What's hand-rolled vs. stdlib

| Piece | Implementation |
|---|---|
| HTTP routing/headers | `http.server.HTTPServer` + `BaseHTTPRequestHandler` (mirrors the original's use of Java's built-in `com.sun.net.httpserver.HttpServer`) |
| Fixed-size thread pool for the HTTP server | Custom `ThreadPoolHTTPServer.process_request` override + `ThreadPoolExecutor`, mirroring `Executors.newFixedThreadPool(10)` |
| multipart/form-data parsing | [p2p/multipart_parser.py](p2p/multipart_parser.py) — manual byte-offset scanning for `filename=`, `Content-Type:`, and the boundary marker. No `cgi`/`email`/third-party multipart libs |
| P2P file transfer | [p2p/file_sharer.py](p2p/file_sharer.py) — raw `socket`/`ServerSocket`-equivalent, one-shot dynamic port per file, custom `Filename: <name>\n` header followed by raw bytes |

## Run

```
python app.py
```

Starts on port 8080. Endpoints match the original API contract exactly, so the existing Next.js UI in `../peershare-main/ui` works unmodified against this backend:

- `POST /upload` (multipart/form-data, field containing the file) → `{"port": <int>}`
- `GET /download/{port}` → streams the file back with `Content-Disposition: attachment`

## Note on a fixed bug

The original Java `UploadUtils.generateCode()` had a bug: `random.nextInt((DYNAMIC_ENDING_PORT - DYNAMIC_STARTING_PORT) + DYNAMIC_STARTING_PORT)` actually returns a value in `[0, 65535)`, not the intended `[49152, 65535]` dynamic port range — meaning it could hand out privileged/invalid ports. [p2p/upload_utils.py](p2p/upload_utils.py) fixes this with `random.randint(49152, 65535)`.
