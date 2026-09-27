from app import app
from fastapi.middleware.cors import CORSMiddleware

# Keep CORS outside app.py so the compositor itself remains unchanged.
# These are the only browser origins allowed to upload captures.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://www.digitmatchstar.com",
        "https://digitmatchstar.com",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=86400,
)
