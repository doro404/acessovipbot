import threading
import logging
from bot import main as bot_main
from websocket_handler import app, socketio, load_config

# Configuração de logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def run_websocket_server():
    """Inicia o servidor WebSocket em uma thread separada"""
    try:
        config = load_config()
        if not config:
            logger.error("Não foi possível carregar config.json")
            return

        port = config.get('server', {}).get('port', 5000)
        host = config.get('server', {}).get('host', '0.0.0.0')
        
        logger.info(f"Iniciando servidor WebSocket na porta {port}...")
        # Usando socketio.run com allow_unsafe_werkzeug=True para evitar avisos
        socketio.run(app, host=host, port=port, allow_unsafe_werkzeug=True)
    except Exception as e:
        logger.error(f"Erro ao iniciar servidor WebSocket: {e}")

def run_bot():
    """Inicia o bot em uma thread separada"""
    try:
        logger.info("Iniciando bot...")
        bot_main()
    except Exception as e:
        logger.error(f"Erro ao iniciar bot: {e}")

def main():
    """Função principal que inicia tanto o bot quanto o servidor WebSocket"""
    try:
        # Iniciar servidor WebSocket em uma thread
        websocket_thread = threading.Thread(target=run_websocket_server)
        websocket_thread.daemon = True  # Thread será encerrada quando o programa principal terminar
        websocket_thread.start()

        # Iniciar bot na thread principal
        run_bot()
    except Exception as e:
        logger.error(f"Erro ao iniciar aplicação: {e}")
        raise

if __name__ == '__main__':
    main() 