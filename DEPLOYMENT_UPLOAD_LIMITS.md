# Upload Limit Deployment Notes (Nginx + Django)

If users see `413 Request Entity Too Large (nginx/1.24.0)`, update Nginx request-size limits.

## 1) Nginx config

Add `client_max_body_size 50M;` in the active `server` block(s) that serve the Django app.
If HTTP redirects to HTTPS, set it in both blocks.

```nginx
server {
    listen 80;
    server_name your-domain.com;
    client_max_body_size 50M;
    # ...
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;
    client_max_body_size 50M;
    # ...
}
```

## 2) Test and reload

```bash
sudo nginx -t
sudo systemctl reload nginx
```

## 3) App behavior in this repo

- Per document file limit: `3 MB`
- Total document size per add-loan submission: `50 MB`
- Server-side validation is handled in:
  - `core/admin_views.py`
  - `core/agent_views.py`
  - `core/upload_limits.py`
