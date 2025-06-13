import subprocess
import threading

def start_bot():
    subprocess.run(["python", "bot.py"])

def start_webhook():
    subprocess.run(["python", "run_webhook.py"])

# Cria threads para executar os dois scripts simultaneamente
threading.Thread(target=start_bot).start()
threading.Thread(target=start_webhook).start()
