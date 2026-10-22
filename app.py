# -*- coding: utf-8 -*-
"""
Punto de entrada principal para Render y servidores WSGI (gunicorn app:app)
"""
import os
from app_rifa import app

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5090))
    app.run(host='0.0.0.0', port=port)
