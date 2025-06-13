import threading
import logging
import asyncio
from bot import main as bot_main  # deve ser async def main()
from websocket_handler import app, socketio, load_config
import os

# Configuração de logs
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Inicia o servidor WebSocket em uma thread separada
def start_websocket_server():
    config = load_config()
    if not config:
        logger.error("Não foi possível carregar config.json")
        return

    port = int(os.environ.get("PORT", config.get('server', {}).get('port', 8080)))
    host = config.get('server', {}).get('host', '0.0.0.0')

    logger.info(f"Iniciando servidor WebSocket na porta {port}...")
    socketio.run(app, host=host, port=port, allow_unsafe_werkzeug=True)

# Função principal
def main():
    # Iniciar servidor WebSocket em segundo plano
    websocket_thread = threading.Thread(target=start_websocket_server, daemon=True)
    websocket_thread.start()

    # Rodar o bot principal (precisa ser feito na thread principal)
    logger.info("Iniciando bot na thread principal...")
    asyncio.run(bot_main())

if __name__ == '__main__':
    main()
