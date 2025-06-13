from flask import Flask, request, jsonify
import json
import hmac
import hashlib
import os
from dotenv import load_dotenv

app = Flask(__name__)
load_dotenv()

# Carrega a configuração dos planos VIP
def load_vip_plans():
    with open('config.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
        return config.get('vip_plans', [])

# Verifica a assinatura do webhook do WooCommerce
def verify_woocommerce_signature(payload, signature):
    webhook_secret = os.getenv('WOOCOMMERCE_WEBHOOK_SECRET')
    if not webhook_secret:
        return False
    
    expected_signature = hmac.new(
        webhook_secret.encode('utf-8'),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(signature, expected_signature)

@app.route('/webhook/woocommerce', methods=['POST'])
def woocommerce_webhook():
    # Obtém a assinatura do cabeçalho
    signature = request.headers.get('X-WC-Webhook-Signature')
    if not signature:
        return jsonify({'error': 'Assinatura não encontrada'}), 401

    # Verifica a assinatura
    if not verify_woocommerce_signature(request.get_data(), signature):
        return jsonify({'error': 'Assinatura inválida'}), 401

    # Processa o payload
    data = request.json
    
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
    app.run(host='0.0.0.0', port=5000) 