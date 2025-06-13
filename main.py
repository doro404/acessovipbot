import threading
import logging
import os
from bot import main as bot_main
from websocket_handler import app, socketio, load_config

# Configuração de logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def start_bot():
    """Inicia o bot em uma thread separada"""
    try:
        logger.info("Iniciando bot em segundo plano...")
        bot_thread = threading.Thread(target=bot_main)
        bot_thread.daemon = True
        bot_thread.start()
    except Exception as e:
        logger.error(f"Erro ao iniciar bot: {e}")

def main():
    config = load_config()
    if not config:
        logger.error("Não foi possível carregar config.json")
        return

    port = int(os.environ.get("PORT", config.get('server', {}).get('port', 8080)))
    host = config.get('server', {}).get('host', '0.0.0.0')

    # Inicia o bot em segundo plano
    start_bot()

    logger.info(f"Iniciando servidor WebSocket na porta {port}...")
    socketio.run(app, host=host, port=port, allow_unsafe_werkzeug=True)

if __name__ == '__main__':
    main()
