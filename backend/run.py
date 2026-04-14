"""Entry point — run with: python -m backend.run"""

import uvicorn
from dotenv import load_dotenv

load_dotenv("backend/.env")

if __name__ == "__main__":
    uvicorn.run("backend.api.server:app", host="0.0.0.0", port=8000, reload=True)
