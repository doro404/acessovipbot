import asyncio
import logging
from bot import main as bot_main
from websocket_handler import app, socketio, load_config

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def start_bot_async():
    """Inicia o bot como uma tarefa assíncrona"""
    try:
        logger.info("Iniciando bot em segundo plano...")
        asyncio.create_task(bot_main())  # bot_main deve ser async para isso funcionar
    except Exception as e:
        logger.error(f"Erro ao iniciar bot: {e}")

def main():
    config = load_config()
    if not config:
        logger.error("Não foi possível carregar config.json")
        return

    port = int(config.get('server', {}).get('port', 8080))  # Railway espera 8080
    host = config.get('server', {}).get('host', '0.0.0.0')

    start_bot_async()

    logger.info(f"Iniciando servidor WebSocket na porta {port}...")
    socketio.run(app, host=host, port=port, allow_unsafe_werkzeug=True)

if __name__ == '__main__':
    asyncio.run(main())
