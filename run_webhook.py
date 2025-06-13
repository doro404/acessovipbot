from webhook_handler import app
import logging

# Configuração de logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

if __name__ == '__main__':
    logger.info("Iniciando servidor webhook na porta 5000...")
    app.run(host='0.0.0.0', port=5000) 