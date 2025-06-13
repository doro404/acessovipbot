# -*- coding: utf-8 -*-
from flask import Flask, request, jsonify
from flask_socketio import SocketIO, emit
import json
import os
import logging
from telegram import Bot
import asyncio

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, cors_allowed_origins='*', async_mode='threading')  # threading evita conflitos

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def load_config():
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Erro ao carregar config.json: {e}")
        return None

def load_vip_plans():
    config = load_config()
    return config.get('vip_plans', []) if config else []

async def notify_admin_pending_payment(order_data):
    try:
        config = load_config()
        if not config:
            return

        bot = Bot(token=config['bot_token'])
        message = (
            f"🆕 *Novo Pagamento Pendente*\n\n"
            f"📦 *Pedido #{order_data.get('id')}*\n"
            f"💰 Total: R${float(order_data.get('total', 0)):.2f}\n"
            f"💳 Método: {order_data.get('payment_method_title', 'N/A')}\n"
            f"📝 Status: {order_data.get('status', '').upper()}\n"
        )
        await bot.send_message(chat_id=config['admin_id'], text=message, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Erro ao notificar admin: {e}")

@app.route('/webhook/woocommerce', methods=['POST'])
def woocommerce_webhook():
    data = request.json

    if data.get('status') == 'pending':
        asyncio.create_task(notify_admin_pending_payment(data))
        return jsonify({'message': 'Notificação enviada ao admin'}), 200

    if data.get('status') == 'completed':
        socketio.emit('order_completed', {'order_id': data.get('id')})
        return jsonify({'message': 'Evento WebSocket enviado'}), 200

    return jsonify({'message': 'Status do pedido ignorado'}), 200

@socketio.on('order_info')
def handle_order_info(data):
    order_id = data.get('order_id')
    produtos = data.get('produtos', [])  # Lista de nomes dos produtos

    logger.info(f"Pedido recebido: {order_id} - Produtos: {produtos}")

    config = load_config()
    if not config:
        emit('order_links', {'error': 'Configuração não carregada'})
        return

    vip_plans = config.get('vip_plans', [])

    matched_plans = []
    for produto_nome in produtos:
        for plan in vip_plans:
            if plan['name'].lower() == produto_nome.lower():
                matched_plans.append(plan)
                break

    if not matched_plans:
        emit('order_links', {'error': 'Nenhum plano VIP correspondente encontrado'})
        return

    response = []
    for plan in matched_plans:
        response.append({
            'plan_id': plan['id'],
            'plan_name': plan['name'],
            'invite_links': plan['groups']
        })

    emit('order_links', {'order_id': order_id, 'plans': response})

if __name__ == '__main__':
    config = load_config()
    if not config:
        logger.error("Não foi possível carregar config.json")
        exit(1)

    port = int(os.environ.get("PORT", config.get('server', {}).get('port', 5000)))
    socketio.run(app, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True)
