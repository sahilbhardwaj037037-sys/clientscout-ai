"""Run from backend: .venv/bin/python -m app.run"""
import uvicorn
from app.core.settings import API_PORT

if __name__ == '__main__':
    uvicorn.run('app.main:app', host='127.0.0.1', port=API_PORT, reload=True)
