import json
import logging
import os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters, JobQueue
import qrcode
from PIL import Image
import io
import mercadopago
import asyncio
import threading
import time
from threading import Thread

# Configuração de logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Lock para operações no JSON
json_lock = threading.Lock()

# Variável global para a instância do bot
_bot_instance = None

def get_bot_instance():
    """Retorna a instância global do bot"""
    global _bot_instance
    return _bot_instance

# Carregar configurações
def load_config():
    try:
        with json_lock:
            with open('config.json', 'r', encoding='utf-8') as f:
                config = json.load(f)
                logger.info("Config carregada com sucesso")
                # Verificar estrutura do config
                if 'payment_methods' not in config:
                    logger.error("Estrutura payment_methods não encontrada no config")
                    return None
                if 'pix_automatico' not in config['payment_methods']:
                    logger.error("pix_automatico não encontrado no config")
                    return None
                if 'pix_manual' not in config['payment_methods']:
                    logger.error("pix_manual não encontrado no config")
                    return None
                return config
    except Exception as e:
        logger.error(f"Erro ao carregar config.json: {e}")
        return None

# Salvar configurações
def save_config(config):
    try:
        with json_lock:
            # Primeiro salva em um arquivo temporário
            temp_file = 'config.json.tmp'
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
            
            # Se salvou com sucesso, renomeia para o arquivo original
            os.replace(temp_file, 'config.json')
            logger.info("Configuração salva com sucesso")
            return True
    except Exception as e:
        logger.error(f"Erro ao salvar config.json: {e}")
        return False

# Editar uma configuração específica
def edit_config(key, value):
    try:
        logger.info(f"Iniciando edição de {key} com valor: {value}")
        config = load_config()
        if not config:
            logger.error("Não foi possível carregar o config.json")
            return False
        
        # Navega pela estrutura do JSON usando a chave
        keys = key.split('.')
        current = config
        for k in keys[:-1]:
            if k not in current:
                current[k] = {}
            current = current[k]
        
        # Atualiza o valor
        current[keys[-1]] = value
        logger.info(f"Valor atualizado na memória: {current[keys[-1]]}")
        
        # Salva as alterações
        if save_config(config):
            logger.info("Configuração salva com sucesso")
            return True
        else:
            logger.error("Erro ao salvar configuração")
            return False
            
    except Exception as e:
        logger.error(f"Erro ao editar config.json: {e}")
        return False

# Exemplo de uso:
# edit_config('admin_settings.welcome_message', 'Nova mensagem de boas-vindas')
# edit_config('mercadopago.access_token', 'Novo token')
# edit_config('payment_methods.pix_manual.chave_pix', 'Nova chave PIX')

# Verificar pagamento no Mercado Pago
def check_payment(payment_id):
    config = load_config()
    sdk = mercadopago.SDK(config['mercadopago']['access_token'])
    
    payment_response = sdk.payment().get(payment_id)
    payment = payment_response["response"]
    
    return payment

# Registrar assinatura VIP
async def register_vip_subscription(user_id, plan_id, payment_id, context):
    try:
        # Carregar assinaturas existentes
        try:
            with json_lock:
                with open('subscriptions.json', 'r', encoding='utf-8') as f:
                    subscriptions = json.load(f)
        except FileNotFoundError:
            subscriptions = []
        
        # Encontrar o plano
        config = load_config()
        plan = next((p for p in config['vip_plans'] if p['id'] == plan_id), None)
        if not plan:
            return False
        
        # Calcular data de expiração para nova assinatura
        if plan['duration_days'] == -1:
            # Plano permanente
            end_date = datetime(2099, 12, 31)  # Data muito futura
        else:
            # Nova assinatura
            end_date = datetime.now() + timedelta(days=plan['duration_days'])
        
        # Adicionar nova assinatura
        subscriptions.append({
            "user_id": user_id,
            "plan_id": plan_id,
            "end_date": end_date.strftime("%Y-%m-%d %H:%M:%S"),
            "payment_method": "mercadopago",
            "payment_status": "approved",
            "payment_id": payment_id,
            "is_permanent": plan['duration_days'] == -1
        })
        
        # Salvar assinaturas
        with json_lock:
            with open('subscriptions.json', 'w', encoding='utf-8') as f:
                json.dump(subscriptions, f, indent=4, ensure_ascii=False)
        
        logger.info(f"Nova assinatura registrada: usuário {user_id}, plano {plan_id}")
        logger.info(f"Data de expiração: {end_date}")

        # Notificar admin
        try:
            admin_id = config['admin_id']
            admin_message = (
                f"🎉 Nova Assinatura VIP!\n\n"
                f"👤 Usuário: {user_id}\n"
                f"💎 Plano: {plan['name']}\n"
                f"💰 Valor: R${plan['price']:.2f}\n"
                f"⏱️ Duração: {'Permanente' if plan['duration_days'] == -1 else f'{plan['duration_days']} dias'}\n"
                f"📅 Expira em: {end_date.strftime('%d/%m/%Y %H:%M')}\n"
                f"💳 ID do Pagamento: {payment_id}"
            )
            await context.bot.send_message(chat_id=admin_id, text=admin_message)
        except Exception as e:
            logger.error(f"Erro ao notificar admin sobre nova assinatura: {e}")

        return True
        
    except Exception as e:
        logger.error(f"Erro ao registrar assinatura: {e}")
        return False

async def renew_vip_subscription(user_id, plan_id, payment_id, context):
    try:
        # Carregar assinaturas existentes
        try:
            with json_lock:
                with open('subscriptions.json', 'r', encoding='utf-8') as f:
                    subscriptions = json.load(f)
        except FileNotFoundError:
            subscriptions = []
        
        # Encontrar o plano
        config = load_config()
        plan = next((p for p in config['vip_plans'] if p['id'] == plan_id), None)
        if not plan:
            return False
        
        # Encontrar assinatura atual
        current_subscription = next(
            (sub for sub in subscriptions 
             if sub['user_id'] == user_id 
             and datetime.strptime(sub['end_date'], "%Y-%m-%d %H:%M:%S") > datetime.now()),
            None
        )
        
        if not current_subscription:
            logger.error(f"Tentativa de renovação sem assinatura ativa: usuário {user_id}")
            return False
        
        # Calcular nova data de expiração
        if plan['duration_days'] == -1:
            # Plano permanente
            end_date = datetime(2099, 12, 31)  # Data muito futura
        else:
            # Renovação - soma os dias
            current_end_date = datetime.strptime(current_subscription['end_date'], "%Y-%m-%d %H:%M:%S")
            days_left = (current_end_date - datetime.now()).days
            end_date = current_end_date + timedelta(days=plan['duration_days'])
            logger.info(f"Renovação detectada. Dias restantes: {days_left}, Novos dias: {plan['duration_days']}, Total: {days_left + plan['duration_days']}")
        
        # Remover assinatura antiga
        subscriptions = [sub for sub in subscriptions if sub != current_subscription]
        logger.info(f"Assinatura antiga removida para usuário {user_id}")
        
        # Adicionar nova assinatura (sem notificações)
        subscriptions.append({
            "user_id": user_id,
            "plan_id": plan_id,
            "end_date": end_date.strftime("%Y-%m-%d %H:%M:%S"),
            "payment_method": "mercadopago",
            "payment_status": "approved",
            "payment_id": payment_id,
            "is_permanent": plan['duration_days'] == -1,
            # Limpar todas as notificações
            "notified_1": False,
            "notified_2": False,
            "notified_3": False,
            "renewal_notified": False
        })
        
        # Salvar assinaturas
        with json_lock:
            with open('subscriptions.json', 'w', encoding='utf-8') as f:
                json.dump(subscriptions, f, indent=4, ensure_ascii=False)
        
        logger.info(f"Renovação registrada: usuário {user_id}, plano {plan_id}")
        logger.info(f"Nova data de expiração: {end_date}")
        logger.info(f"Notificações de expiração limpas para o usuário {user_id}")

        # Notificar admin
        try:
            admin_id = config['admin_id']
            admin_message = (
                f"🔄 Renovação de Assinatura VIP!\n\n"
                f"👤 Usuário: {user_id}\n"
                f"💎 Plano: {plan['name']}\n"
                f"💰 Valor: R${plan['price']:.2f}\n"
                f"⏱️ Duração: {'Permanente' if plan['duration_days'] == -1 else f'{plan['duration_days']} dias'}\n"
                f"📅 Nova expiração: {end_date.strftime('%d/%m/%Y %H:%M')}\n"
                f"💳 ID do Pagamento: {payment_id}"
            )
            await context.bot.send_message(chat_id=admin_id, text=admin_message)
        except Exception as e:
            logger.error(f"Erro ao notificar admin sobre renovação: {e}")

        return True
        
    except Exception as e:
        logger.error(f"Erro ao renovar assinatura: {e}")
        return False

# Adicionar usuário aos grupos VIP
async def add_user_to_vip_groups(bot, user_id, plan_id):
    config = load_config()
    
    # Encontrar o plano
    plan = next((p for p in config['vip_plans'] if p['id'] == plan_id), None)
    if not plan:
        return False
    
    # Adicionar usuário aos grupos
    for group_id in plan['groups']:
        try:
            # Verificar se o grupo é um supergrupo
            chat = await bot.get_chat(group_id)
            if chat.type in ['group', 'supergroup']:
                try:
                    # Tentar criar link de convite
                    invite_link = await bot.create_chat_invite_link(
                        chat_id=group_id,
                        name=f"VIP {user_id}",
                        expire_date=datetime.now() + timedelta(days=7),
                        member_limit=1,
                        creates_join_request=False
                    )
                    
                    # Enviar link para o usuário
                    await bot.send_message(
                        chat_id=user_id,
                        text=f"🎉 Use este link para entrar no grupo VIP:\n{invite_link.invite_link}\n\nO link expira em 7 dias e só pode ser usado uma vez."
                    )
                    logger.info(f"Link de convite enviado para usuário {user_id} - grupo {group_id}")
                    
                except Exception as e:
                    logger.error(f"Erro ao criar link de convite para grupo {group_id}: {e}")
                    # Se falhar, tenta obter link existente
                    try:
                        invite_link = await bot.export_chat_invite_link(chat_id=group_id)
                        await bot.send_message(
                            chat_id=user_id,
                            text=f"🎉 Use este link para entrar no grupo VIP:\n{invite_link}\n\nO link expira em 7 dias."
                        )
                        logger.info(f"Link existente enviado para usuário {user_id} - grupo {group_id}")
                    except Exception as e2:
                        logger.error(f"Erro ao obter link existente: {e2}")
                        # Se tudo falhar, notifica o admin
                        admin_id = config['admin_id']
                        await bot.send_message(
                            chat_id=admin_id,
                            text=f"⚠️ Erro ao gerar link para usuário {user_id} no grupo {group_id}.\nErro: {e}\nErro do link: {e2}\n\nVerifique se o bot tem permissões de administrador no grupo."
                        )
            else:
                logger.error(f"Grupo {group_id} não é um grupo ou supergrupo válido")
                # Notifica o admin
                admin_id = config['admin_id']
                await bot.send_message(
                    chat_id=admin_id,
                    text=f"⚠️ Grupo {group_id} não é um grupo ou supergrupo válido.\nTipo: {chat.type}"
                )
                
        except Exception as e:
            logger.error(f"Erro ao processar grupo {group_id}: {e}")
            # Notifica o admin
            admin_id = config['admin_id']
            await bot.send_message(
                chat_id=admin_id,
                text=f"⚠️ Erro ao processar grupo {group_id} para usuário {user_id}.\nErro: {e}"
            )
    
    return True

# Gerar QR Code PIX do Mercado Pago
def generate_mercadopago_pix(amount, description, external_reference):
    config = load_config()
    sdk = mercadopago.SDK(config['mercadopago']['access_token'])
    
    payment_data = {
        "transaction_amount": float(amount),
        "description": description,
        "payment_method_id": "pix",
        "external_reference": external_reference,
        "payer": {
            "email": "cliente@email.com",
            "first_name": "Cliente",
            "last_name": "Teste"
        }
    }

    try:
        payment_response = sdk.payment().create(payment_data)
        payment = payment_response["response"]
        
        # Verificar se tem os dados do PIX
        if "point_of_interaction" in payment and "transaction_data" in payment["point_of_interaction"]:
            return {
                "qr_code": payment["point_of_interaction"]["transaction_data"]["qr_code"],
                "qr_code_base64": payment["point_of_interaction"]["transaction_data"]["qr_code_base64"],
                "payment_id": payment["id"]
            }
        else:
            logger.error(f"Dados do PIX não encontrados na resposta: {payment}")
            return None
    except Exception as e:
        logger.error(f"Erro ao gerar PIX: {e}")
        return None

# Gerar QR Code PIX
def generate_pix_qr_code(payment_data):
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(payment_data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Converter para bytes
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    return img_byte_arr

# Adicionar usuário às estatísticas
async def add_user_to_stats(user, bot):
    try:
        # Carregar estatísticas atuais
        try:
            with json_lock:
                with open('stats.json', 'r', encoding='utf-8') as f:
                    stats = json.load(f)
        except FileNotFoundError:
            stats = {
                "total_users": 0,
                "users": [],
                "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        
        # Verificar se usuário já existe
        user_exists = any(u['id'] == user.id for u in stats['users'])
        
        if not user_exists:
            # Adicionar novo usuário
            stats['users'].append({
                "id": user.id,
                "username": user.username,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "joined_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "is_vip": False
            })
            stats['total_users'] = len(stats['users'])
            stats['last_update'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # Salvar estatísticas
            with json_lock:
                with open('stats.json', 'w', encoding='utf-8') as f:
                    json.dump(stats, f, indent=4, ensure_ascii=False)
            
            logger.info(f"Novo usuário adicionado: {user.id}")

            # Notificar admin sobre novo usuário
            try:
                config = load_config()
                admin_id = config['admin_id']
                msg = (
                    f"👤 Novo usuário acessou o bot!\n\n"
                    f"ID: {user.id}\n"
                    f"Nome: {user.first_name or ''} {user.last_name or ''}\n"
                    f"Username: @{user.username if user.username else '-'}\n"
                    f"Data de entrada: {datetime.now().strftime('%d/%m/%Y %H:%M')}"
                )
                await bot.send_message(chat_id=admin_id, text=msg)
            except Exception as e:
                logger.error(f"Erro ao notificar admin sobre novo usuário: {e}")
        
    except Exception as e:
        logger.error(f"Erro ao adicionar usuário às estatísticas: {e}")

# Atualizar status VIP do usuário
async def update_user_vip_status(user_id, is_vip=True):
    try:
        # Carregar estatísticas atuais
        with json_lock:
            with open('stats.json', 'r', encoding='utf-8') as f:
                stats = json.load(f)
        
        # Encontrar e atualizar o usuário
        for user in stats['users']:
            if user['id'] == user_id:
                user['is_vip'] = is_vip
                break
        
        # Salvar estatísticas
        with json_lock:
            with open('stats.json', 'w', encoding='utf-8') as f:
                json.dump(stats, f, indent=4, ensure_ascii=False)
        
        logger.info(f"Status VIP atualizado para usuário {user_id}: {is_vip}")
        return True
        
    except Exception as e:
        logger.error(f"Erro ao atualizar status VIP: {e}")
        return False

# Comandos do bot
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    config = load_config()
    
    # Verifica modo manutenção
    if config.get('admin_settings', {}).get('maintenance_mode', False):
        await update.message.reply_text("🛠️ O bot está em manutenção. Tente novamente mais tarde.")
        return
    
    # Adiciona usuário às estatísticas
    await add_user_to_stats(update.effective_user, context.bot)
    
    # Carregar mensagens do arquivo
    try:
        with open('messages.txt', 'r', encoding='utf-8') as f:
            messages = dict(line.strip().split('=', 1) for line in f if line.strip())
    except Exception as e:
        logger.error(f"Erro ao carregar mensagens: {e}")
        await update.message.reply_text("Erro ao carregar mensagens.")
        return
    
    # Verificar assinaturas ativas do usuário
    try:
        with open('subscriptions.json', 'r', encoding='utf-8') as f:
            subscriptions = json.load(f)
    except FileNotFoundError:
        subscriptions = []
    
    # Filtrar assinaturas ativas do usuário
    active_subscriptions = [
        sub for sub in subscriptions 
        if sub['user_id'] == update.effective_user.id 
        and datetime.strptime(sub['end_date'], "%Y-%m-%d %H:%M:%S") > datetime.now()
    ]
    
    # Se tiver assinatura ativa, mostra status e planos disponíveis
    if active_subscriptions:
        # Encontrar o plano atual
        current_plan = next(
            (p for p in config['vip_plans'] 
             if p['id'] == active_subscriptions[0]['plan_id']),
            None
        )
        
        if current_plan:
            # Calcular tempo restante
            end_date = datetime.strptime(active_subscriptions[0]['end_date'], "%Y-%m-%d %H:%M:%S")
            time_left = end_date - datetime.now()
            days_left = time_left.days
            hours_left = time_left.seconds // 3600
            
            # Verificar se está próximo de expirar (1, 2 ou 3 dias, ou menos de 24 horas)
            is_expiring_soon = (
                (days_left == 0 and hours_left <= 24) or
                days_left in [1, 2, 3]
            ) and not active_subscriptions[0].get('is_permanent', False)
            
            # Criar teclado
            keyboard = []
            
            # Se estiver próximo de expirar, adicionar botão de renovação
            if is_expiring_soon:
                keyboard.append([InlineKeyboardButton(
                    "🔄 Renovar Plano Atual",
                    callback_data=f"renew_{current_plan['id']}"
                )])
            
            # Adicionar outros planos disponíveis
            available_plans = [
                plan for plan in config['vip_plans']
                if plan['id'] != current_plan['id']
            ]
            
            for plan in available_plans:
                keyboard.append([InlineKeyboardButton(
                    f"💎 {plan['name']} - R${plan['price']:.2f}",
                    callback_data=f"plan_{plan['id']}"
                )])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Mensagem de status
            status_message = f"✨ Você já é VIP!\n\n"
            status_message += f"Plano atual: {current_plan['name']}\n"
            
            if active_subscriptions[0].get('is_permanent', False):
                status_message += "Duração: Permanente\n\n"
            else:
                if days_left == 0:
                    status_message += f"Horas restantes: {hours_left}\n\n"
                else:
                    status_message += f"Dias restantes: {days_left}\n\n"
            
            if is_expiring_soon:
                status_message += "⚠️ Sua assinatura está próxima de expirar! Renove agora para manter seu acesso VIP.\n\n"
            
            status_message += "Seu acesso aos grupos VIP está ativo. Aproveite! 🎉"
            
            await update.message.reply_text(
                status_message,
                reply_markup=reply_markup
            )
            return
    
    # Se não tiver assinatura ativa, mostra todos os planos
    keyboard = []
    for plan in config['vip_plans']:
        keyboard.append([InlineKeyboardButton(
            f"💎 {plan['name']} - R${plan['price']:.2f}",
            callback_data=f"plan_{plan['id']}"
        )])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        messages.get('start_message', 'Escolha um dos planos VIP disponíveis:'),
        reply_markup=reply_markup
    )

async def handle_plan_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # Verificar se é uma renovação
    if query.data.startswith("renew_"):
        plan_id = int(query.data.split('_')[1])
        
        # Carregar assinaturas ativas do usuário
        try:
            with open('subscriptions.json', 'r', encoding='utf-8') as f:
                subscriptions = json.load(f)
        except FileNotFoundError:
            subscriptions = []
        
        # Encontrar assinatura atual
        current_subscription = next(
            (sub for sub in subscriptions 
             if sub['user_id'] == update.effective_user.id 
             and datetime.strptime(sub['end_date'], "%Y-%m-%d %H:%M:%S") > datetime.now()),
            None
        )
        
        if current_subscription:
            # Calcular dias restantes
            end_date = datetime.strptime(current_subscription['end_date'], "%Y-%m-%d %H:%M:%S")
            days_left = (end_date - datetime.now()).days
            
            # Criar teclado de confirmação
            keyboard = [
                [InlineKeyboardButton("✅ Confirmar Renovação", callback_data=f"confirm_renew_{plan_id}")],
                [InlineKeyboardButton("❌ Cancelar", callback_data="cancel_renew")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Mensagem de confirmação
            config = load_config()
            plan = next((p for p in config['vip_plans'] if p['id'] == plan_id), None)
            if plan:
                message = f"🔄 Confirmação de Renovação\n\n"
                message += f"Plano: {plan['name']}\n"
                message += f"Valor: R${plan['price']:.2f}\n"
                message += f"Duração do plano: {plan['duration_days']} dias\n"
                message += f"Dias restantes atuais: {days_left} dias\n"
                message += f"Total após renovação: {days_left + plan['duration_days']} dias\n\n"
                message += "⚠️ Importante: Os dias do novo plano serão somados aos dias restantes da sua assinatura atual.\n\n"
                message += "Deseja confirmar a renovação?"
                
                await query.message.edit_text(
                    message,
                    reply_markup=reply_markup
                )
                return
    else:
        plan_id = int(query.data.split('_')[1])
    
    config = load_config()
    
    # Verifica modo manutenção
    if config.get('admin_settings', {}).get('maintenance_mode', False):
        await query.message.reply_text("🛠️ O bot está em manutenção. Tente novamente mais tarde.")
        return
    
    # Carregar mensagens do arquivo
    try:
        with open('messages.txt', 'r', encoding='utf-8') as f:
            messages = dict(line.strip().split('=', 1) for line in f if line.strip())
    except Exception as e:
        logger.error(f"Erro ao carregar mensagens: {e}")
        await query.message.reply_text("Erro ao carregar mensagens.")
        return
    
    plan = next((p for p in config['vip_plans'] if p['id'] == plan_id), None)
    if not plan:
        await query.message.reply_text("Plano não encontrado.")
        return
    
    keyboard = []
    if config['payment_methods']['pix_automatico']['enabled']:
        keyboard.append([InlineKeyboardButton("💳 PIX Automático", callback_data=f"pix_auto_{plan_id}")])
    if config['payment_methods']['pix_manual']['enabled']:
        keyboard.append([InlineKeyboardButton("💳 PIX Manual", callback_data=f"pix_manual_{plan_id}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Mensagem personalizada para renovação
    if query.data.startswith("renew_"):
        message = f"🔄 Renovação do Plano: {plan['name']}\n"
        message += f"💰 Valor: R${plan['price']:.2f}\n"
        message += f"⏱️ Duração: {'Permanente' if plan['duration_days'] == -1 else f'{plan['duration_days']} dias'}\n\n"
        message += f"{messages.get('payment_instructions', 'Para renovar, escolha o método de pagamento:')}"
    else:
        message = f"💎 Plano: {plan['name']}\n"
        message += f"💰 Valor: R${plan['price']:.2f}\n"
        message += f"⏱️ Duração: {'Permanente' if plan['duration_days'] == -1 else f'{plan['duration_days']} dias'}\n\n"
        message += f"{messages.get('payment_instructions', 'Para pagar, escolha o método de pagamento:')}"
    
    await query.message.reply_text(
        message,
        reply_markup=reply_markup
    )

async def handle_renewal_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel_renew":
        # Voltar para o menu inicial
        keyboard = []
        config = load_config()
        for plan in config['vip_plans']:
            keyboard.append([InlineKeyboardButton(
                f"💎 {plan['name']} - R${plan['price']:.2f}",
                callback_data=f"plan_{plan['id']}"
            )])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(
            "Escolha um dos planos VIP disponíveis:",
            reply_markup=reply_markup
        )
        return
    
    # Extrair ID do plano
    plan_id = int(query.data.split('_')[2])
    
    # Mostrar opções de pagamento
    config = load_config()
    plan = next((p for p in config['vip_plans'] if p['id'] == plan_id), None)
    if not plan:
        await query.message.reply_text("Plano não encontrado.")
        return
    
    keyboard = []
    if config['payment_methods']['pix_automatico']['enabled']:
        keyboard.append([InlineKeyboardButton("💳 PIX Automático", callback_data=f"pix_auto_{plan_id}")])
    if config['payment_methods']['pix_manual']['enabled']:
        keyboard.append([InlineKeyboardButton("💳 PIX Manual", callback_data=f"pix_manual_{plan_id}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Carregar mensagens do arquivo
    try:
        with open('messages.txt', 'r', encoding='utf-8') as f:
            messages = dict(line.strip().split('=', 1) for line in f if line.strip())
    except Exception as e:
        logger.error(f"Erro ao carregar mensagens: {e}")
        await query.message.reply_text("Erro ao carregar mensagens.")
        return
    
    message = f"🔄 Renovação Confirmada!\n\n"
    message += f"Plano: {plan['name']}\n"
    message += f"Valor: R${plan['price']:.2f}\n"
    message += f"Duração: {plan['duration_days']} dias\n\n"
    message += f"{messages.get('payment_instructions', 'Escolha o método de pagamento:')}"
    
    await query.message.edit_text(
        message,
        reply_markup=reply_markup
    )

async def handle_payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    config = load_config()
    
    # Verifica modo manutenção
    if config.get('admin_settings', {}).get('maintenance_mode', False):
        await query.message.reply_text("🛠️ O bot está em manutenção. Tente novamente mais tarde.")
        return
    
    # Corrigindo o split do callback_data
    parts = query.data.split('_')
    method = parts[1]  # pix_auto ou pix_manual
    plan_id = parts[2]  # ID do plano
    
    # Carregar mensagens do arquivo
    try:
        with open('messages.txt', 'r', encoding='utf-8') as f:
            messages = dict(line.strip().split('=', 1) for line in f if line.strip())
    except Exception as e:
        logger.error(f"Erro ao carregar mensagens: {e}")
        await query.message.reply_text("Erro ao carregar mensagens.")
        return
    
    plan = next((p for p in config['vip_plans'] if p['id'] == int(plan_id)), None)
    if not plan:
        await query.message.reply_text("Plano não encontrado.")
        return
    
    if method == "auto":
        # Gerar PIX do Mercado Pago
        pix_data = generate_mercadopago_pix(
            plan['price'],
            f"VIP {plan['name']} - {plan['duration_days']} dias",
            f"{update.effective_user.id}_{plan_id}"  # Referência externa
        )
        
        if pix_data:
            # Converter QR Code base64 para imagem
            import base64
            qr_code_bytes = base64.b64decode(pix_data['qr_code_base64'])
            qr_code = io.BytesIO(qr_code_bytes)
            
            # Criar botão "Já Paguei"
            keyboard = [[InlineKeyboardButton("✅ Já Paguei", callback_data=f"check_{pix_data['payment_id']}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Enviar mensagem inicial
            message = await query.message.reply_photo(
                photo=qr_code,
                caption=f"{messages.get('pix_automatico_instructions', 'Escaneie o QR Code abaixo para pagar automaticamente:')}\n\nValor: R${plan['price']:.2f}\nID do Pagamento: {pix_data['payment_id']}\n\n⏳ Aguardando pagamento...",
                reply_markup=reply_markup
            )
            
            # Iniciar verificação automática
            context.job_queue.run_repeating(
                check_payment_auto,
                interval=5,
                first=5,
                data={
                    'message_id': message.message_id,
                    'chat_id': message.chat_id,
                    'payment_id': pix_data['payment_id'],
                    'user_id': update.effective_user.id,
                    'plan_id': plan_id,
                    'plan': plan
                }
            )
        else:
            await query.message.reply_text("Erro ao gerar PIX. Tente novamente mais tarde.")
    else:
        chave_pix = config['payment_methods']['pix_manual']['chave_pix']
        nome_titular = config['payment_methods']['pix_manual']['nome_titular']
        admin_user = config['admin_user']
        
        # Criar mensagem com instruções do PIX
        message = (
            f"💳 *Pagamento via PIX Manual*\n\n"
            f"📝 *Instruções:*\n"
            f"1. Faça o PIX para a chave: `{chave_pix}`\n"
            f"2. Nome do titular: {nome_titular}\n"
            f"3. Após o pagamento, clique no botão abaixo para enviar o comprovante\n\n"
            f"⚠️ *Importante:*\n"
            f"• Envie o comprovante apenas após realizar o pagamento\n"
            f"• Aguarde a confirmação do admin\n"
            f"• O processo pode levar alguns minutos"
        )
        
        # Criar botão para contato com admin
        keyboard = [
            [InlineKeyboardButton("📤 Enviar Comprovante", url=f"https://t.me/{admin_user}")],
            [InlineKeyboardButton("🔙 Voltar", callback_data="back_to_plans")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.reply_text(
            text=message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

async def check_payment_auto(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    data = job.data
    
    payment = check_payment(data['payment_id'])
    config = load_config()
    
    # Carregar mensagens do arquivo
    try:
        with open('messages.txt', 'r', encoding='utf-8') as f:
            messages = dict(line.strip().split('=', 1) for line in f if line.strip())
    except Exception as e:
        logger.error(f"Erro ao carregar mensagens: {e}")
        return
    
    # Criar botão "Já Paguei"
    keyboard = [[InlineKeyboardButton("✅ Já Paguei", callback_data=f"check_{data['payment_id']}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if payment and payment.get('status') == 'approved':
        # Verificar se o pagamento já foi processado
        try:
            with open('subscriptions.json', 'r', encoding='utf-8') as f:
                subscriptions = json.load(f)
                
            # Verificar se já existe uma assinatura com este payment_id
            payment_already_processed = any(
                sub.get('payment_id') == str(data['payment_id']) 
                for sub in subscriptions
            )
            
            if payment_already_processed:
                logger.info(f"Pagamento {data['payment_id']} já foi processado anteriormente. Ignorando...")
                # Parar a verificação
                job.schedule_removal()
                return
                
        except Exception as e:
            logger.error(f"Erro ao verificar duplicidade: {e}")
        
        # Extrair informações do pagamento
        external_reference = payment.get('external_reference', '')
        if external_reference:
            user_id, plan_id = external_reference.split('_')
            user_id = int(user_id)
            plan_id = int(plan_id)
            
            # Verificar se é renovação ou nova assinatura
            is_renewal = any(
                sub['user_id'] == user_id 
                and datetime.strptime(sub['end_date'], "%Y-%m-%d %H:%M:%S") > datetime.now()
                for sub in subscriptions
            )
            
            success = False
            if is_renewal:
                success = await renew_vip_subscription(user_id, plan_id, data['payment_id'], context)
            else:
                success = await register_vip_subscription(user_id, plan_id, data['payment_id'], context)
            
            if success:
                # Atualizar status VIP nas estatísticas
                await update_user_vip_status(user_id, True)
                
                # Adicionar usuário aos grupos VIP
                await add_user_to_vip_groups(context.bot, user_id, plan_id)
                
                try:
                    # Atualizar mensagem com confirmação
                    success_message = f"✅ {messages.get('payment_success', 'Pagamento aprovado!').format(dias=data['plan']['duration_days'])}\n\nID do Pagamento: {data['payment_id']}"
                    await context.bot.edit_message_caption(
                        chat_id=data['chat_id'],
                        message_id=data['message_id'],
                        caption=success_message,
                        reply_markup=None  # Remove o botão após aprovação
                    )
                except Exception as e:
                    logger.error(f"Erro ao atualizar mensagem: {e}")
                    # Se falhar, tenta enviar uma nova mensagem
                    await context.bot.send_message(
                        chat_id=data['chat_id'],
                        text=success_message
                    )
                
                # Parar a verificação
                job.schedule_removal()
    elif payment and payment.get('status') == 'rejected':
        try:
            # Atualizar mensagem com erro
            error_message = f"❌ {messages.get('payment_error', 'Ocorreu um erro no pagamento. Tente novamente.')}\n\nID do Pagamento: {data['payment_id']}"
            await context.bot.edit_message_caption(
                chat_id=data['chat_id'],
                message_id=data['message_id'],
                caption=error_message,
                reply_markup=None  # Remove o botão após rejeição
            )
        except Exception as e:
            logger.error(f"Erro ao atualizar mensagem: {e}")
            await context.bot.send_message(
                chat_id=data['chat_id'],
                text=error_message
            )
        # Parar a verificação
        job.schedule_removal()
    elif payment and payment.get('status') in ['pending', 'in_process']:
        # Só atualiza se o status mudou
        current_status = payment.get('status')
        if current_status != data.get('last_status'):
            try:
                status_message = f"{messages.get('pix_automatico_instructions', 'Escaneie o QR Code abaixo para pagar automaticamente:')}\n\nValor: R${data['plan']['price']:.2f}\nID do Pagamento: {data['payment_id']}\n\n⏳ Aguardando confirmação do pagamento..."
                await context.bot.edit_message_caption(
                    chat_id=data['chat_id'],
                    message_id=data['message_id'],
                    caption=status_message,
                    reply_markup=reply_markup  # Mantém o botão durante a espera
                )
                # Atualiza o último status
                data['last_status'] = current_status
            except Exception as e:
                logger.error(f"Erro ao atualizar mensagem: {e}")
                # Se falhar, tenta enviar uma nova mensagem
                await context.bot.send_message(
                    chat_id=data['chat_id'],
                    text=status_message,
                    reply_markup=reply_markup
                )

async def check_payment_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    payment_id = query.data.split('_')[1]
    payment = check_payment(payment_id)
    config = load_config()
    
    # Carregar mensagens do arquivo
    try:
        with open('messages.txt', 'r', encoding='utf-8') as f:
            messages = dict(line.strip().split('=', 1) for line in f if line.strip())
    except Exception as e:
        logger.error(f"Erro ao carregar mensagens: {e}")
        await query.message.reply_text("Erro ao carregar mensagens.")
        return
    
    if payment and payment.get('status') == 'approved':
        # Extrair informações do pagamento
        external_reference = payment.get('external_reference', '')
        if external_reference:
            user_id, plan_id = external_reference.split('_')
            
            # Encontrar o plano
            plan = next((p for p in config['vip_plans'] if p['id'] == int(plan_id)), None)
            if not plan:
                await query.message.reply_text("Plano não encontrado.")
                return
            
            # Registrar assinatura
            if await register_vip_subscription(int(user_id), int(plan_id), payment_id, context):
                # Adicionar usuário aos grupos VIP
                await add_user_to_vip_groups(context.bot, int(user_id), int(plan_id))
                
                try:
                    # Atualizar mensagem com confirmação
                    success_message = f"✅ {messages.get('payment_success', 'Pagamento aprovado!').format(dias=plan['duration_days'])}\n\nID do Pagamento: {payment_id}"
                    await query.message.edit_caption(caption=success_message)
                    
                    # Remover botão
                    await query.message.edit_reply_markup(reply_markup=None)
                except Exception as e:
                    logger.error(f"Erro ao atualizar mensagem: {e}")
                    # Se falhar, tenta enviar uma nova mensagem
                    await query.message.reply_text(success_message)
                
                # Parar verificação automática se existir
                if hasattr(context, 'job_queue') and context.job_queue:
                    for job in context.job_queue.jobs():
                        if job.data.get('payment_id') == payment_id:
                            job.schedule_removal()
    else:
        status = messages.get('payment_pending', 'Aguardando confirmação do pagamento...')
        if payment:
            if payment.get('status') == 'rejected':
                status = messages.get('payment_error', 'Ocorreu um erro no pagamento. Tente novamente.')
        
        await query.answer(status, show_alert=True)

# Comandos do admin
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    config = load_config()
    
    if str(update.effective_user.id) != config['admin_id']:
        await update.message.reply_text("Acesso negado.")
        return
    
    # Carregar mensagens do arquivo
    try:
        with open('messages.txt', 'r', encoding='utf-8') as f:
            messages = dict(line.strip().split('=', 1) for line in f if line.strip())
    except Exception as e:
        logger.error(f"Erro ao carregar mensagens: {e}")
        await update.message.reply_text("Erro ao carregar mensagens.")
        return
    
    keyboard = [
        [InlineKeyboardButton("📊 Estatísticas", callback_data="admin_stats")],
        [InlineKeyboardButton("⚙️ Configurações", callback_data="admin_settings")],
        [InlineKeyboardButton("👥 Usuários VIP", callback_data="admin_vip_users")],
        [InlineKeyboardButton("📝 Mensagens", callback_data="admin_messages")],
        [InlineKeyboardButton("🔄 Manutenção", callback_data="admin_maintenance")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        messages.get('admin_welcome', 'Bem-vindo ao painel administrativo.'),
        reply_markup=reply_markup
    )

async def handle_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    logger.info(f"Callback recebido: {query.data}")
    
    config = load_config()
    if str(update.effective_user.id) != config['admin_id']:
        await query.message.reply_text("Acesso negado.")
        return
    
    # Carregar mensagens do arquivo
    try:
        with open('messages.txt', 'r', encoding='utf-8') as f:
            messages = dict(line.strip().split('=', 1) for line in f if line.strip())
    except Exception as e:
        logger.error(f"Erro ao carregar mensagens: {e}")
        await query.message.reply_text("Erro ao carregar mensagens.")
        return
    
    # Verificar se é um callback de edição de configurações
    if query.data == "admin_edit_bot_token":
        keyboard = [[InlineKeyboardButton("⬅️ Voltar", callback_data="admin_settings")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(
            "🔑 Editar Token do Bot\n\n"
            f"Token atual: {config['bot_token']}\n\n"
            "Envie o novo token do bot:",
            reply_markup=reply_markup
        )
        context.user_data['editing'] = 'bot_token'
        return
    elif query.data == "admin_edit_mp_token":
        keyboard = [[InlineKeyboardButton("⬅️ Voltar", callback_data="admin_settings")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(
            "💳 Editar Token do MercadoPago\n\n"
            f"Token atual: {config['mercadopago']['access_token']}\n\n"
            "Envie o novo token do MercadoPago:",
            reply_markup=reply_markup
        )
        context.user_data['editing'] = 'mp_token'
        return
    elif query.data == "admin_edit_pix_key":
        keyboard = [[InlineKeyboardButton("⬅️ Voltar", callback_data="admin_settings")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(
            "📱 Editar Chave PIX\n\n"
            f"Chave atual: {config['payment_methods']['pix_manual']['chave_pix']}\n\n"
            "Envie a nova chave PIX:",
            reply_markup=reply_markup
        )
        context.user_data['editing'] = 'pix_key'
        return
    elif query.data == "admin_edit_pix_name":
        keyboard = [[InlineKeyboardButton("⬅️ Voltar", callback_data="admin_settings")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(
            "👤 Editar Nome do Titular PIX\n\n"
            f"Nome atual: {config['payment_methods']['pix_manual']['nome_titular']}\n\n"
            "Envie o novo nome do titular:",
            reply_markup=reply_markup
        )
        context.user_data['editing'] = 'pix_name'
        return
    
    # Verificar se é um callback de broadcast
    if query.data == "admin_broadcast":
        # Menu de broadcast
        keyboard = [
            [InlineKeyboardButton("📢 Enviar para Todos", callback_data="admin_broadcast_all")],
            [InlineKeyboardButton("👥 Enviar para VIPs", callback_data="admin_broadcast_vip")],
            [InlineKeyboardButton("⬅️ Voltar", callback_data="admin_back")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(
            "📢 Broadcast\n\nEscolha o tipo de broadcast:",
            reply_markup=reply_markup
        )
        return
    elif query.data == "admin_settings":
        # Menu de configurações
        keyboard = [
            [InlineKeyboardButton("🔑 Token do Bot", callback_data="admin_edit_bot_token")],
            [InlineKeyboardButton("💳 Token MercadoPago", callback_data="admin_edit_mp_token")],
            [InlineKeyboardButton("📱 Chave PIX", callback_data="admin_edit_pix_key")],
            [InlineKeyboardButton("👤 Nome Titular PIX", callback_data="admin_edit_pix_name")],
            [InlineKeyboardButton(
                f"{'🔴' if not config['payment_methods']['pix_automatico']['enabled'] else '🟢'} PIX Automático",
                callback_data="admin_toggle_pix_auto"
            )],
            [InlineKeyboardButton(
                f"{'🔴' if not config['payment_methods']['pix_manual']['enabled'] else '🟢'} PIX Manual",
                callback_data="admin_toggle_pix_manual"
            )],
            [InlineKeyboardButton("⬅️ Voltar", callback_data="admin_back")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(
            "⚙️ Configurações\n\nEscolha uma opção para editar:",
            reply_markup=reply_markup
        )
        return
    elif query.data == "admin_messages":
        # Menu de mensagens
        keyboard = [
            [InlineKeyboardButton("👋 Mensagem de Boas-vindas", callback_data="admin_edit_welcome_message")],
            [InlineKeyboardButton("💎 Mensagem de Pagamento", callback_data="admin_edit_payment_message")],
            [InlineKeyboardButton("✅ Mensagem de Sucesso", callback_data="admin_edit_success_message")],
            [InlineKeyboardButton("❌ Mensagem de Erro", callback_data="admin_edit_error_message")],
            [InlineKeyboardButton("📝 Instruções PIX", callback_data="admin_edit_pix_instructions")],
            [InlineKeyboardButton("⬅️ Voltar", callback_data="admin_back")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Mostrar mensagens atuais
        text = "📝 Mensagens do Bot\n\n"
        text += "Mensagens atuais:\n\n"
        text += f"👋 Boas-vindas: {messages.get('start_message', 'Não definida')}\n\n"
        text += f"💎 Pagamento: {messages.get('payment_instructions', 'Não definida')}\n\n"
        text += f"✅ Sucesso: {messages.get('payment_success', 'Não definida')}\n\n"
        text += f"❌ Erro: {messages.get('payment_error', 'Não definida')}\n\n"
        text += f"📝 PIX: {messages.get('pix_automatico_instructions', 'Não definida')}\n\n"
        text += "Escolha uma mensagem para editar:"
        
        await query.message.edit_text(
            text,
            reply_markup=reply_markup
        )
        return
    elif query.data == "admin_broadcast_all":
        # Preparar para enviar para todos
        context.user_data['broadcast_type'] = 'all'
        keyboard = [[InlineKeyboardButton("❌ Cancelar", callback_data="admin_broadcast")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(
            "📢 Enviar mensagem para todos os usuários\n\n"
            "Digite a mensagem que deseja enviar:",
            reply_markup=reply_markup
        )
        return
    elif query.data == "admin_broadcast_vip":
        # Preparar para enviar para VIPs
        context.user_data['broadcast_type'] = 'vip'
        keyboard = [[InlineKeyboardButton("❌ Cancelar", callback_data="admin_broadcast")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(
            "📢 Enviar mensagem para usuários VIP\n\n"
            "Digite a mensagem que deseja enviar:",
            reply_markup=reply_markup
        )
        return
    
    # Se não for broadcast, continua com o código existente
    action = query.data.split('_')[1]
    logger.info(f"Ação: {action}")
    
    if action == "stats":
        # Mostrar estatísticas
        try:
            with open('stats.json', 'r', encoding='utf-8') as f:
                stats = json.load(f)
            
            text = "📊 Estatísticas do Bot\n\n"
            text += f"Total de Usuários: {stats['total_users']}\n"
            text += f"Total de VIPs: {sum(1 for u in stats['users'] if u.get('is_vip', False))}\n"
            text += f"Última Atualização: {stats['last_update']}\n\n"
            text += "👥 Últimos Usuários:\n"
            
            # Mostrar os últimos 5 usuários
            for user in stats['users'][-5:]:
                text += f"\nID: {user['id']}"
                if user['username']:
                    text += f"\nUsername: @{user['username']}"
                text += f"\nNome: {user['first_name']}"
                if user['last_name']:
                    text += f" {user['last_name']}"
                text += f"\nData: {user['joined_date']}"
                text += f"\nVIP: {'✅' if user.get('is_vip', False) else '❌'}\n"
            
        except Exception as e:
            logger.error(f"Erro ao carregar estatísticas: {e}")
            text = "Erro ao carregar estatísticas."
        
        keyboard = [[InlineKeyboardButton("⬅️ Voltar", callback_data="admin_back")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(text, reply_markup=reply_markup)
        
    elif action == "vip_users":
        # Listar usuários VIP
        try:
            with open('subscriptions.json', 'r', encoding='utf-8') as f:
                subscriptions = json.load(f)
        except FileNotFoundError:
            subscriptions = []
        
        # Filtrar assinaturas ativas
        active_subscriptions = [
            sub for sub in subscriptions 
            if datetime.strptime(sub['end_date'], "%Y-%m-%d %H:%M:%S") > datetime.now()
        ]
        
        if active_subscriptions:
            text = "👥 Usuários VIP Ativos:\n\n"
            for sub in active_subscriptions:
                text += f"ID: {sub['user_id']}\n"
                text += f"Plano: {sub['plan_id']}\n"
                text += f"Expira em: {sub['end_date']}\n\n"
        else:
            text = "Nenhum usuário VIP ativo."
        
        keyboard = [[InlineKeyboardButton("⬅️ Voltar", callback_data="admin_back")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(text, reply_markup=reply_markup)
        
    elif action == "maintenance":
        # Modo manutenção
        keyboard = [
            [InlineKeyboardButton(
                "🔴 Desativar Manutenção" if config.get('maintenance_mode', False) else "🟢 Ativar Manutenção",
                callback_data="admin_toggle_maintenance"
            )],
            [InlineKeyboardButton("⬅️ Voltar", callback_data="admin_back")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        status = "ativado" if config.get('maintenance_mode', False) else "desativado"
        await query.message.edit_text(
            f"🔄 Modo Manutenção\n\nStatus atual: {status}",
            reply_markup=reply_markup
        )
        
    elif action == "back":
        # Menu principal com layout melhorado
        keyboard = [
            [InlineKeyboardButton("📊 Estatísticas", callback_data="admin_stats")],
            [InlineKeyboardButton("⚙️ Configurações", callback_data="admin_settings")],
            [InlineKeyboardButton("👥 Usuários VIP", callback_data="admin_vip_users")],
            [InlineKeyboardButton("📝 Mensagens", callback_data="admin_messages")],
            [InlineKeyboardButton("🔄 Manutenção", callback_data="admin_maintenance")],
            [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(
            "🔧 Painel Administrativo\n\nEscolha uma opção:",
            reply_markup=reply_markup
        )

async def handle_admin_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    logger.info(f"Callback de edição recebido: {query.data}")
    
    config = load_config()
    if str(update.effective_user.id) != config['admin_id']:
        await query.message.reply_text("Acesso negado.")
        return
    
    # Verifica se é uma edição de configuração
    if query.data == "admin_edit_bot_token":
        keyboard = [[InlineKeyboardButton("⬅️ Voltar", callback_data="admin_settings")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(
            "🔑 Editar Token do Bot\n\n"
            f"Token atual: {config['bot_token']}\n\n"
            "Envie o novo token do bot:",
            reply_markup=reply_markup
        )
        context.user_data['editing'] = 'bot_token'
        return
        
    elif query.data == "admin_edit_mp_token":
        keyboard = [[InlineKeyboardButton("⬅️ Voltar", callback_data="admin_settings")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(
            "💳 Editar Token do MercadoPago\n\n"
            f"Token atual: {config['mercadopago']['access_token']}\n\n"
            "Envie o novo token do MercadoPago:",
            reply_markup=reply_markup
        )
        context.user_data['editing'] = 'mp_token'
        return
        
    elif query.data == "admin_edit_pix_key":
        keyboard = [[InlineKeyboardButton("⬅️ Voltar", callback_data="admin_settings")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(
            "📱 Editar Chave PIX\n\n"
            f"Chave atual: {config['payment_methods']['pix_manual']['chave_pix']}\n\n"
            "Envie a nova chave PIX:",
            reply_markup=reply_markup
        )
        context.user_data['editing'] = 'pix_key'
        return
        
    elif query.data == "admin_edit_pix_name":
        keyboard = [[InlineKeyboardButton("⬅️ Voltar", callback_data="admin_settings")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(
            "👤 Editar Nome do Titular PIX\n\n"
            f"Nome atual: {config['payment_methods']['pix_manual']['nome_titular']}\n\n"
            "Envie o novo nome do titular:",
            reply_markup=reply_markup
        )
        context.user_data['editing'] = 'pix_name'
        return
    
    # Verifica se é uma edição de plano VIP
    if query.data.startswith("admin_edit_plan_") and not query.data.endswith("_input"):
        plan_id = int(query.data.split('_')[-1])
        plan = next((p for p in config['vip_plans'] if p['id'] == plan_id), None)
        if not plan:
            await query.message.reply_text("Plano não encontrado.")
            return
            
        keyboard = [
            [InlineKeyboardButton("📝 Nome", callback_data=f"admin_edit_plan_name_input_{plan_id}")],
            [InlineKeyboardButton("💰 Preço", callback_data=f"admin_edit_plan_price_input_{plan_id}")],
            [InlineKeyboardButton("⏱️ Duração (dias)", callback_data=f"admin_edit_plan_duration_input_{plan_id}")],
            [InlineKeyboardButton("⬅️ Voltar", callback_data="admin_vip_plans")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(
            f"💎 Editar Plano: {plan['name']}\n\n"
            f"Preço atual: R${plan['price']:.2f}\n"
            f"Duração atual: {plan['duration_days']} dias\n\n"
            "Escolha o que deseja editar:",
            reply_markup=reply_markup
        )
        return
    
    # Verifica se é uma edição específica do plano
    if query.data.startswith("admin_edit_plan_name_input_"):
        plan_id = int(query.data.split('_')[-1])
        plan = next((p for p in config['vip_plans'] if p['id'] == plan_id), None)
        if not plan:
            await query.message.reply_text("Plano não encontrado.")
            return
            
        keyboard = [[InlineKeyboardButton("⬅️ Voltar", callback_data=f"admin_edit_plan_{plan_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(
            f"📝 Editar Nome do Plano\n\n"
            f"Nome atual: {plan['name']}\n\n"
            "Envie o novo nome do plano:",
            reply_markup=reply_markup
        )
        context.user_data['editing'] = f"plan_name_{plan_id}"
        
    elif query.data.startswith("admin_edit_plan_price_input_"):
        plan_id = int(query.data.split('_')[-1])
        plan = next((p for p in config['vip_plans'] if p['id'] == plan_id), None)
        if not plan:
            await query.message.reply_text("Plano não encontrado.")
            return
            
        keyboard = [[InlineKeyboardButton("⬅️ Voltar", callback_data=f"admin_edit_plan_{plan_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(
            f"💰 Editar Preço do Plano\n\n"
            f"Preço atual: R${plan['price']:.2f}\n\n"
            "Envie o novo preço (apenas números):",
            reply_markup=reply_markup
        )
        context.user_data['editing'] = f"plan_price_{plan_id}"
        
    elif query.data.startswith("admin_edit_plan_duration_input_"):
        plan_id = int(query.data.split('_')[-1])
        plan = next((p for p in config['vip_plans'] if p['id'] == plan_id), None)
        if not plan:
            await query.message.reply_text("Plano não encontrado.")
            return
            
        keyboard = [[InlineKeyboardButton("⬅️ Voltar", callback_data=f"admin_edit_plan_{plan_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(
            f"⏱️ Editar Duração do Plano\n\n"
            f"Duração atual: {plan['duration_days']} dias\n\n"
            "Envie a nova duração em dias (apenas números):",
            reply_markup=reply_markup
        )
        context.user_data['editing'] = f"plan_duration_{plan_id}"

async def handle_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'editing' not in context.user_data and 'broadcast_type' not in context.user_data:
        return
    
    logger.info(f"Texto recebido para edição: {update.message.text}")
    
    config = load_config()
    if str(update.effective_user.id) != config['admin_id']:
        return
    
    # Verificar se é uma mensagem de broadcast
    if 'broadcast_type' in context.user_data:
        broadcast_type = context.user_data['broadcast_type']
        message_text = update.message.text
        
        try:
            # Carregar usuários
            with open('stats.json', 'r', encoding='utf-8') as f:
                stats = json.load(f)
            
            # Carregar assinaturas VIP
            with open('subscriptions.json', 'r', encoding='utf-8') as f:
                subscriptions = json.load(f)
            
            # Filtrar usuários VIP ativos
            active_vip_users = {
                sub['user_id'] for sub in subscriptions
                if datetime.strptime(sub['end_date'], "%Y-%m-%d %H:%M:%S") > datetime.now()
            }
            
            # Preparar lista de destinatários
            if broadcast_type == 'all':
                recipients = [user['id'] for user in stats['users']]
            else:  # vip
                recipients = [user['id'] for user in stats['users'] if user['id'] in active_vip_users]
            
            # Enviar mensagem
            success_count = 0
            error_count = 0
            
            # Mensagem de progresso
            progress_message = await update.message.reply_text(
                f"📢 Enviando mensagem para {len(recipients)} usuários...\n"
                f"✅ Enviados: 0\n"
                f"❌ Erros: 0"
            )
            
            for user_id in recipients:
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=message_text
                    )
                    success_count += 1
                except Exception as e:
                    logger.error(f"Erro ao enviar mensagem para {user_id}: {e}")
                    error_count += 1
                
                # Atualizar mensagem de progresso a cada 10 envios
                if (success_count + error_count) % 10 == 0:
                    await progress_message.edit_text(
                        f"📢 Enviando mensagem para {len(recipients)} usuários...\n"
                        f"✅ Enviados: {success_count}\n"
                        f"❌ Erros: {error_count}"
                    )
            
            # Mensagem final
            await progress_message.edit_text(
                f"📢 Broadcast concluído!\n\n"
                f"✅ Mensagens enviadas: {success_count}\n"
                f"❌ Erros: {error_count}\n\n"
                f"Tipo: {'Todos os usuários' if broadcast_type == 'all' else 'Usuários VIP'}"
            )
            
            # Limpar estado de broadcast
            del context.user_data['broadcast_type']
            
            # Voltar ao menu de broadcast
            keyboard = [
                [InlineKeyboardButton("📢 Enviar para Todos", callback_data="admin_broadcast_all")],
                [InlineKeyboardButton("👥 Enviar para VIPs", callback_data="admin_broadcast_vip")],
                [InlineKeyboardButton("⬅️ Voltar", callback_data="admin_back")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                "📢 Broadcast\n\nEscolha o tipo de broadcast:",
                reply_markup=reply_markup
            )
            
        except Exception as e:
            logger.error(f"Erro ao realizar broadcast: {e}")
            await update.message.reply_text(
                f"❌ Erro ao realizar broadcast: {str(e)}\n\n"
                "Tente novamente mais tarde."
            )
            # Limpar estado de broadcast
            del context.user_data['broadcast_type']
        return
    
    # Edição de configurações
    new_value = update.message.text
    editing = context.user_data['editing']
    
    try:
        if editing == 'bot_token':
            config['bot_token'] = new_value
            success_message = "✅ Token do bot atualizado com sucesso!"
        elif editing == 'mp_token':
            config['mercadopago']['access_token'] = new_value
            success_message = "✅ Token do MercadoPago atualizado com sucesso!"
        elif editing == 'pix_key':
            config['payment_methods']['pix_manual']['chave_pix'] = new_value
            success_message = "✅ Chave PIX atualizada com sucesso!"
        elif editing == 'pix_name':
            config['payment_methods']['pix_manual']['nome_titular'] = new_value
            success_message = "✅ Nome do titular PIX atualizado com sucesso!"
        else:
            await update.message.reply_text("❌ Tipo de edição inválido.")
            return
        
        # Salvar configurações
        if save_config(config):
            # Limpar estado de edição
            del context.user_data['editing']
            
            # Confirmar atualização
            keyboard = [[InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data="admin_settings")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                success_message,
                reply_markup=reply_markup
            )
        else:
            await update.message.reply_text("❌ Erro ao salvar configuração. Tente novamente.")
            
    except Exception as e:
        logger.error(f"Erro ao editar configuração: {e}")
        await update.message.reply_text("❌ Erro ao editar configuração. Tente novamente.")

async def handle_maintenance_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    config = load_config()
    if str(update.effective_user.id) != config['admin_id']:
        return
    
    # Inicializa admin_settings se não existir
    if 'admin_settings' not in config:
        config['admin_settings'] = {}
    
    # Alternar modo manutenção
    current_mode = config['admin_settings'].get('maintenance_mode', False)
    config['admin_settings']['maintenance_mode'] = not current_mode
    
    # Salvar configurações
    if save_config(config):
        # Atualizar mensagem
        status = "ativado" if not current_mode else "desativado"
        keyboard = [
            [InlineKeyboardButton(
                "🔴 Desativar Manutenção" if not current_mode else "🟢 Ativar Manutenção",
                callback_data="admin_toggle_maintenance"
            )],
            [InlineKeyboardButton("⬅️ Voltar", callback_data="admin_back")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(
            f"🔄 Modo Manutenção\n\nStatus atual: {status}",
            reply_markup=reply_markup
        )
    else:
        await query.message.reply_text("❌ Erro ao salvar configuração. Tente novamente.")

async def handle_payment_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    logger.info(f"Callback de toggle recebido: {query.data}")
    
    try:
        config = load_config()
        logger.info(f"Config carregada: {config}")
        
        if str(update.effective_user.id) != config['admin_id']:
            logger.error("Acesso negado - ID não corresponde")
            return
        
        # Extrai o tipo de PIX do callback
        if "pix_auto" in query.data:
            action = "auto"
        elif "pix_manual" in query.data:
            action = "manual"
        else:
            logger.error(f"Callback inválido: {query.data}")
            return
            
        logger.info(f"Ação de toggle: {action}")
        
        # Alterna o estado do método correto
        if action == "auto":
            current_state = config['payment_methods']['pix_automatico']['enabled']
            logger.info(f"Estado atual do PIX Automático: {current_state}")
            config['payment_methods']['pix_automatico']['enabled'] = not current_state
            new_state = config['payment_methods']['pix_automatico']['enabled']
            logger.info(f"Novo estado do PIX Automático: {new_state}")
            method_name = "Automático"
        else:  # manual
            current_state = config['payment_methods']['pix_manual']['enabled']
            logger.info(f"Estado atual do PIX Manual: {current_state}")
            config['payment_methods']['pix_manual']['enabled'] = not current_state
            new_state = config['payment_methods']['pix_manual']['enabled']
            logger.info(f"Novo estado do PIX Manual: {new_state}")
            method_name = "Manual"
        
        # Salva a configuração
        logger.info("Tentando salvar configuração...")
        if save_config(config):
            logger.info("Configuração salva com sucesso")
            # Atualiza a mensagem
            keyboard = [
                [InlineKeyboardButton("🔑 Token do Bot", callback_data="admin_edit_bot_token")],
                [InlineKeyboardButton("💳 Token MercadoPago", callback_data="admin_edit_mp_token")],
                [InlineKeyboardButton("📱 Chave PIX", callback_data="admin_edit_pix_key")],
                [InlineKeyboardButton("👤 Nome Titular PIX", callback_data="admin_edit_pix_name")],
                [InlineKeyboardButton(
                    f"{'🔴' if not config['payment_methods']['pix_automatico']['enabled'] else '🟢'} PIX Automático",
                    callback_data="admin_toggle_pix_auto"
                )],
                [InlineKeyboardButton(
                    f"{'🔴' if not config['payment_methods']['pix_manual']['enabled'] else '🟢'} PIX Manual",
                    callback_data="admin_toggle_pix_manual"
                )],
                [InlineKeyboardButton("⬅️ Voltar", callback_data="admin_back")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            status = "ativado" if new_state else "desativado"
            await query.message.edit_text(
                f"⚙️ Configurações\n\nPIX {method_name} {status}!",
                reply_markup=reply_markup
            )
        else:
            logger.error("Falha ao salvar configuração")
            await query.message.reply_text("❌ Erro ao salvar configuração. Tente novamente.")
            
    except Exception as e:
        logger.error(f"Erro ao alternar PIX {action}: {e}")
        await query.message.reply_text("❌ Erro ao alternar método de pagamento. Tente novamente.")

async def check_expired_subscriptions(context: ContextTypes.DEFAULT_TYPE):
    """Verifica e remove assinaturas expiradas."""
    try:
        logger.info("Iniciando verificação de assinaturas expiradas...")
        # Carregar assinaturas
        with json_lock:
            with open('subscriptions.json', 'r', encoding='utf-8') as f:
                subscriptions = json.load(f)
        
        # Carregar configuração
        config = load_config()
        current_time = datetime.now()
        logger.info(f"Verificando assinaturas em: {current_time}")
        logger.info(f"Total de assinaturas carregadas: {len(subscriptions)}")
        
        # Filtrar assinaturas expiradas (exceto permanentes)
        expired_subscriptions = []
        for sub in subscriptions:
            try:
                logger.info(f"\nVerificando assinatura do usuário {sub['user_id']}:")
                logger.info(f"É permanente? {sub.get('is_permanent', False)}")
                
                if not sub.get('is_permanent', False):
                    end_date = datetime.strptime(sub['end_date'], "%Y-%m-%d %H:%M:%S")
                    logger.info(f"Data de expiração: {end_date}")
                    logger.info(f"Data atual: {current_time}")
                    logger.info(f"Está expirada? {end_date <= current_time}")
                    
                    if end_date <= current_time:
                        logger.info(f"Assinatura do usuário {sub['user_id']} está expirada!")
                        expired_subscriptions.append(sub)
                else:
                    logger.info(f"Assinatura do usuário {sub['user_id']} é permanente, ignorando...")
            except Exception as e:
                logger.error(f"Erro ao processar assinatura: {e}")
        
        logger.info(f"\nEncontradas {len(expired_subscriptions)} assinaturas expiradas")
        
        for sub in expired_subscriptions:
            try:
                # Encontrar o plano
                plan = next((p for p in config['vip_plans'] if p['id'] == sub['plan_id']), None)
                if plan:
                    logger.info(f"Processando expiração do usuário {sub['user_id']} - Plano: {plan['name']}")
                    # Remover usuário dos grupos
                    for group_id in plan['groups']:
                        try:
                            await context.bot.ban_chat_member(
                                chat_id=group_id,
                                user_id=sub['user_id']
                            )
                            # Desbanir imediatamente para permitir reentrada
                            await context.bot.unban_chat_member(
                                chat_id=group_id,
                                user_id=sub['user_id']
                            )
                            logger.info(f"Usuário {sub['user_id']} removido do grupo {group_id}")
                        except Exception as e:
                            logger.error(f"Erro ao remover usuário {sub['user_id']} do grupo {group_id}: {e}")
                    
                    # Atualizar status VIP
                    await update_user_vip_status(sub['user_id'], False)
                    
                    # Notificar usuário
                    try:
                        await context.bot.send_message(
                            chat_id=sub['user_id'],
                            text=f"⚠️ Sua assinatura VIP expirou!\n\n"
                                 f"Plano: {plan['name']}\n"
                                 f"Data de expiração: {sub['end_date']}\n\n"
                                 f"Para continuar com acesso VIP, adquira um novo plano usando /start"
                        )
                        logger.info(f"Notificação de expiração enviada para usuário {sub['user_id']}")
                    except Exception as e:
                        logger.error(f"Erro ao notificar usuário {sub['user_id']}: {e}")
            
            except Exception as e:
                logger.error(f"Erro ao processar assinatura expirada: {e}")
        
        # Remover assinaturas expiradas do arquivo
        if expired_subscriptions:
            subscriptions = [
                sub for sub in subscriptions
                if sub not in expired_subscriptions
            ]
            with json_lock:
                with open('subscriptions.json', 'w', encoding='utf-8') as f:
                    json.dump(subscriptions, f, indent=4, ensure_ascii=False)
            logger.info(f"Removidas {len(expired_subscriptions)} assinaturas expiradas do arquivo")
            
    except Exception as e:
        logger.error(f"Erro ao verificar assinaturas expiradas: {e}")

async def check_expiring_subscriptions(context: ContextTypes.DEFAULT_TYPE):
    """Verifica e notifica assinaturas próximas de expirar."""
    try:
        logger.info("Iniciando verificação de assinaturas próximas de expirar...")
        # Carregar assinaturas
        with json_lock:
            with open('subscriptions.json', 'r', encoding='utf-8') as f:
                subscriptions = json.load(f)
        
        # Carregar configuração
        config = load_config()
        current_time = datetime.now()
        logger.info(f"Verificando assinaturas em: {current_time}")
        logger.info(f"Total de assinaturas carregadas: {len(subscriptions)}")
        
        # Filtrar assinaturas próximas de expirar
        expiring_subscriptions = [
            sub for sub in subscriptions
            if not sub.get('is_permanent', False) and 
            datetime.strptime(sub['end_date'], "%Y-%m-%d %H:%M:%S") > current_time
        ]
        
        logger.info(f"Encontradas {len(expiring_subscriptions)} assinaturas próximas de expirar")
        
        for sub in expiring_subscriptions:
            try:
                # Encontrar o plano
                plan = next((p for p in config['vip_plans'] if p['id'] == sub['plan_id']), None)
                if plan:
                    # Calcular dias restantes
                    end_date = datetime.strptime(sub['end_date'], "%Y-%m-%d %H:%M:%S")
                    time_left = end_date - current_time
                    days_left = time_left.days
                    hours_left = time_left.seconds // 3600
                    
                    logger.info(f"Verificando assinatura do usuário {sub['user_id']}:")
                    logger.info(f"Dias restantes: {days_left}")
                    logger.info(f"Horas restantes: {hours_left}")
                    
                    # Verificar se deve notificar (3, 2 ou 1 dia, ou menos de 24 horas)
                    should_notify = False
                    notification_key = None
                    
                    if days_left == 0 and hours_left <= 24:
                        should_notify = True
                        notification_key = "notified_1"
                    elif days_left == 1:
                        should_notify = True
                        notification_key = "notified_1"
                    elif days_left == 2:
                        should_notify = True
                        notification_key = "notified_2"
                    elif days_left == 3:
                        should_notify = True
                        notification_key = "notified_3"
                    
                    if should_notify and not sub.get(notification_key, False):
                        # Notificar usuário
                        try:
                            message = f"⚠️ Sua assinatura VIP está próxima de expirar!\n\n"
                            message += f"Plano: {plan['name']}\n"
                            if days_left == 0:
                                message += f"Horas restantes: {hours_left}\n"
                            else:
                                message += f"Dias restantes: {days_left}\n"
                            message += f"Data de expiração: {sub['end_date']}\n\n"
                            message += f"Para renovar seu acesso VIP, use /start e escolha um novo plano! 🎉"
                            
                            await context.bot.send_message(
                                chat_id=sub['user_id'],
                                text=message
                            )
                            logger.info(f"Notificação enviada para usuário {sub['user_id']}")
                            
                            # Marcar como notificado
                            sub[notification_key] = True
                            logger.info(f"Usuário {sub['user_id']} marcado como notificado para {notification_key}")
                            
                        except Exception as e:
                            logger.error(f"Erro ao notificar usuário {sub['user_id']}: {e}")
            
            except Exception as e:
                logger.error(f"Erro ao processar assinatura próxima de expirar: {e}")
        
        # Salvar alterações (marcação de notificados)
        if expiring_subscriptions:
            with json_lock:
                with open('subscriptions.json', 'w', encoding='utf-8') as f:
                    json.dump(subscriptions, f, indent=4, ensure_ascii=False)
            logger.info("Alterações salvas no arquivo de assinaturas")
            
    except Exception as e:
        logger.error(f"Erro ao verificar assinaturas próximas de expirar: {e}")

async def initial_check(context: ContextTypes.DEFAULT_TYPE):
    """Verificação inicial de assinaturas quando o bot inicia."""
    logger.info("Iniciando verificação inicial de assinaturas...")
    
    # Verificar assinaturas expiradas
    await check_expired_subscriptions(context)
    
    # Verificar assinaturas próximas de expirar
    await check_expiring_subscriptions(context)
    
    logger.info("Verificação inicial concluída!")

async def handle_back_to_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # Limpar estado do usuário
    if 'waiting_for_proof' in context.user_data:
        del context.user_data['waiting_for_proof']
    
    # Retornar para a lista de planos
    keyboard = []
    config = load_config()
    for plan in config['vip_plans']:
        keyboard.append([InlineKeyboardButton(
            f"💎 {plan['name']} - R${plan['price']:.2f}",
            callback_data=f"plan_{plan['id']}"
        )])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(
        "Escolha um dos planos VIP disponíveis:",
        reply_markup=reply_markup
    )

async def check_bot_initialization(bot, config):
    """Verifica a inicialização do bot e envia relatório ao admin."""
    try:
        # Verificar se o token é válido
        bot_info = await bot.get_me()
        logger.info(f"Bot iniciado com sucesso: @{bot_info.username}")
        
        # Verificar dependências
        missing_deps = []
        try:
            import qrcode
        except ImportError:
            missing_deps.append("qrcode")
        try:
            import mercadopago
        except ImportError:
            missing_deps.append("mercadopago")
        try:
            from PIL import Image
        except ImportError:
            missing_deps.append("Pillow")
            
        # Verificar arquivos de configuração
        missing_files = []
        if not os.path.exists('config.json'):
            missing_files.append("config.json")
        if not os.path.exists('messages.txt'):
            missing_files.append("messages.txt")
            
        # Verificar estrutura do config.json
        config_errors = []
        if 'bot_token' not in config:
            config_errors.append("Token do bot não encontrado")
        if 'admin_id' not in config:
            config_errors.append("ID do admin não encontrado")
        if 'payment_methods' not in config:
            config_errors.append("Configurações de pagamento não encontradas")
        if 'vip_plans' not in config:
            config_errors.append("Planos VIP não encontrados")
            
        # Preparar mensagem de status
        status_message = f"🤖 *Status de Inicialização do Bot*\n\n"
        status_message += f"✅ Bot iniciado: @{bot_info.username}\n"
        
        if missing_deps:
            status_message += f"\n❌ Dependências faltando:\n"
            for dep in missing_deps:
                status_message += f"• {dep}\n"
                
        if missing_files:
            status_message += f"\n❌ Arquivos faltando:\n"
            for file in missing_files:
                status_message += f"• {file}\n"
                
        if config_errors:
            status_message += f"\n❌ Erros de configuração:\n"
            for error in config_errors:
                status_message += f"• {error}\n"
                
        if not (missing_deps or missing_files or config_errors):
            status_message += "\n✅ Todas as verificações passaram com sucesso!"
            
        # Enviar mensagem ao admin
        try:
            await bot.send_message(
                chat_id=config['admin_id'],
                text=status_message,
                parse_mode='Markdown'
            )
            logger.info("Relatório de inicialização enviado ao admin")
        except Exception as e:
            logger.error(f"Erro ao enviar relatório ao admin: {e}")
            
    except Exception as e:
        logger.error(f"Erro ao verificar inicialização: {e}")
        try:
            await bot.send_message(
                chat_id=config['admin_id'],
                text=f"❌ *Erro na inicialização do bot*\n\nErro: {str(e)}",
                parse_mode='Markdown'
            )
        except:
            logger.error("Não foi possível enviar mensagem de erro ao admin")


def main():
    """Função principal que inicia o bot"""
    global _bot_instance
    
    config = load_config()
    if not config:
        logger.error("Não foi possível carregar config.json")
        return

    # Criar a instância do bot
    _bot_instance = Bot(token=config['bot_token'])
    
    # Criar a aplicação
    application = Application.builder().token(config['bot_token']).build()
    
    try:
        # Verificar inicialização e enviar relatório ao admin
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(check_bot_initialization(_bot_instance, config))
        
        # Adicionar job para verificação inicial (após 5 segundos)
        application.job_queue.run_once(
            initial_check,
            when=5  # 5 segundos após iniciar
        )
        
        # Adicionar job para verificar assinaturas expiradas (a cada 15 minutos)
        application.job_queue.run_repeating(
            check_expired_subscriptions,
            interval=900,  # 15 minutos
            first=10  # Primeira verificação após 10 segundos
        )
        
        # Adicionar job para verificar assinaturas próximas de expirar (a cada 12 horas)
        application.job_queue.run_repeating(
            check_expiring_subscriptions,
            interval=43200,  # 12 horas
            first=60  # Primeira verificação após 1 minuto
        )
        
        # Adicionar handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("admin", admin))
        
        # Handlers de edição e configurações (mais específicos primeiro)
        application.add_handler(CallbackQueryHandler(handle_admin_edit, pattern="^admin_edit_"))
        application.add_handler(CallbackQueryHandler(handle_payment_toggle, pattern="^admin_toggle_pix_"))
        application.add_handler(CallbackQueryHandler(handle_maintenance_toggle, pattern="^admin_toggle_maintenance"))
        
        # Handlers de pagamento e planos
        application.add_handler(CallbackQueryHandler(handle_plan_selection, pattern="^plan_"))
        application.add_handler(CallbackQueryHandler(handle_plan_selection, pattern="^renew_"))
        application.add_handler(CallbackQueryHandler(handle_renewal_confirmation, pattern="^(confirm|cancel)_renew"))
        application.add_handler(CallbackQueryHandler(handle_payment_method, pattern="^pix_"))
        application.add_handler(CallbackQueryHandler(check_payment_manual, pattern="^check_"))
        
        # Handler geral de admin (menos específico por último)
        application.add_handler(CallbackQueryHandler(handle_admin_callback, pattern="^admin_"))
        
        # Handler de texto para edições
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_text))
        
        # Adicionar handler de erro
        application.add_error_handler(error_handler)
        
        # Adicionar handler para o botão de voltar
        application.add_handler(CallbackQueryHandler(handle_back_to_plans, pattern="^back_to_plans$"))
        
        # Iniciar o bot
        logger.info("Iniciando o bot...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        logger.error(f"Erro ao iniciar o bot: {e}")
        # Tentar reiniciar após 5 segundos
        time.sleep(5)
        main()

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tratamento de erros do bot."""
    logger.error(f"Erro não tratado: {context.error}")
    
    # Se for erro de conflito, reiniciar o bot
    if "Conflict" in str(context.error):
        logger.info("Detectado conflito de instâncias. Reiniciando...")
        await context.application.stop()
        time.sleep(5)
        main()
    else:
        # Para outros erros, apenas logar
        logger.error(f"Erro: {context.error}")
        if update:
            logger.error(f"Update: {update}")

if __name__ == '__main__':
    main()
