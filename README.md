# peershare (Python)

Python port of the original Java peershare P2P file-sharing backend. Stdlib only : NO Flask/FastAPI.

## Run

```
python app.py
```

Starts on port 8080. Endpoints match the original API contract exactly, so the existing Next.js UI in `../peershare-main/ui` works unmodified against this backend:

- `POST /upload` (multipart/form-data, field containing the file) → `{"port": <int>}`
- `GET /download/{port}` → streams the file back with `Content-Disposition: attachment`
