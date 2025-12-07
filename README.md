# Spleeter Audio Stem Separator

AI-powered audio stem separation for Worship Team Sync.

## Deploy to Railway (Free Tier)

1. Fork or push this repo to your GitHub
2. Go to [railway.app](https://railway.app)
3. New Project → Deploy from GitHub repo
4. Select this repo - Railway auto-detects Dockerfile
5. Wait 3-5 minutes for build
6. Click "Generate Domain" for your public URL

## API Endpoints

- `GET /` - Frontend UI
- `GET /api/health` - Health check
- `POST /api/analyze` - BPM/Key detection
- `POST /api/separate` - Start stem separation
- `GET /api/status/<job_id>` - Check job progress
- `GET /api/download/<job_id>/<file>` - Download stem

## Notes

- First separation downloads ~300MB model (one time)
- Processing takes ~30-60 seconds per song
- Supports 2, 4, or 5 stem separation
