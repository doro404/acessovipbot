# -*- coding: utf-8 -*-

from flask import Flask, request, jsonify
import json
import os
from dotenv import load_dotenv
import logging
from telegram import Bot
import asyncio

app = Flask(__name__)
load_dotenv()

# Configuração de logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Carrega a configuração completa
def load_config():
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            config = json.load(f)
            logger.info("Config carregada com sucesso")
            return config
    except Exception as e:
        logger.error(f"Erro ao carregar config.json: {e}")
        return None

# Carrega apenas os planos VIP
def load_vip_plans():
    config = load_config()
    if config:
        return config.get('vip_plans', [])
    return []

# Notifica o admin sobre novo pagamento pendente
async def notify_admin_pending_payment(order_data):
    try:
        config = load_config()
        if not config:
            logger.error("Não foi possível carregar a configuração")
            return
            
        bot_token = config['bot_token']
        admin_id = config['admin_id']
        
        # Extrair informações do pedido
        order_id = order_data.get('id')
        order_total = order_data.get('total')
        order_status = order_data.get('status')
        payment_method = order_data.get('payment_method_title', 'Método não especificado')
        
        # Extrair produtos do pedido
        line_items = order_data.get('line_items', [])
        products_info = []
        for item in line_items:
            products_info.append(f"• {item['name']} - R${float(item['total']):.2f}")
        
        # Criar mensagem para o admin
        message = (
            f"🆕 *Novo Pagamento Pendente*\n\n"
            f"📦 *Pedido #{order_id}*\n"
            f"💰 Total: R${float(order_total):.2f}\n"
            f"💳 Método: {payment_method}\n"
            f"📝 Status: {order_status.upper()}\n\n"
            f"*Produtos:*\n" + "\n".join(products_info) + "\n\n"
            f"👤 *Cliente:*\n"
            f"Email: {order_data.get('billing', {}).get('email', 'Não informado')}\n"
            f"IP: {order_data.get('customer_ip_address', 'Não informado')}\n\n"
            f"⏰ Data: {order_data.get('date_created', 'Não informada')}"
        )
        
        # Enviar mensagem usando o bot
        bot = Bot(token=bot_token)
        await bot.send_message(
            chat_id=admin_id,
            text=message,
            parse_mode='Markdown'
        )
        logger.info(f"Admin notificado sobre novo pagamento pendente - Pedido #{order_id}")
        
    except Exception as e:
        logger.error(f"Erro ao notificar admin sobre pagamento pendente: {e}")

@app.route('/webhook/woocommerce', methods=['POST'])
def woocommerce_webhook():
    data = request.json

    # Se for um pedido pendente, notifica o admin
    if data.get('status') == 'pending':
        asyncio.run(notify_admin_pending_payment(data))
        return jsonify({'message': 'Notificação enviada ao admin'}), 200

    # Verifica se é um pedido concluído
    if data.get('status') != 'completed':
        return jsonify({'message': 'Pedido não está concluído'}), 200

    # Obtém o nome do produto/plano
    order_items = data.get('line_items', [])
    if not order_items:
        return jsonify({'error': 'Nenhum item encontrado no pedido'}), 400

    product_name = order_items[0].get('name')
    if not product_name:
        return jsonify({'error': 'Nome do produto não encontrado'}), 400

    # Busca o plano VIP correspondente
    vip_plans = load_vip_plans()
    matching_plan = next((plan for plan in vip_plans if plan['name'].lower() == product_name.lower()), None)

    if not matching_plan:
        return jsonify({
            'error': f'Plano "{product_name}" não encontrado',
            'available_plans': [plan['name'] for plan in vip_plans]
        }), 404

    # Retorna os grupos do plano
    return jsonify({
        'success': True,
        'plan_name': matching_plan['name'],
        'groups': matching_plan['groups'],
        'duration_days': matching_plan['duration_days']
    })

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
