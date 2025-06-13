from websocket_handler import app
import logging
import os

# Configuração de logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"Iniciando servidor webhook na porta {port}...")
    app.run(host='0.0.0.0', port=port)
