"""
telegram_bot.py — Модуль отправки уведомлений в Telegram

Использует API Telegram для отправки текстовых сообщений.
"""
import requests
import config

def send_telegram_message(text: str) -> bool:
    """
    Отправляет текстовое сообщение в заданный чат Telegram.
    
    Args:
        text: Текст сообщения. Поддерживается базовая HTML разметка.
        
    Returns:
        True если успешно, иначе False.
    """
    if not config.ENABLE_TELEGRAM:
        return False
        
    if not config.TELEGRAM_BOT_TOKEN or config.TELEGRAM_BOT_TOKEN == "ВАШ_ТОКЕН":
        print("[telegram] Bot token not configured. Skipping alert.")
        return False
        
    if not config.TELEGRAM_CHAT_ID or config.TELEGRAM_CHAT_ID == "ВАШ_ЧАТ_ID":
        print("[telegram] Chat ID not configured. Skipping alert.")
        return False

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        print("[telegram] Message sent successfully.")
        return True
    except Exception as e:
        print(f"[telegram] Failed to send message: {e}")
        # Если 400 Bad Request, возможно проблема с разметкой
        if hasattr(e, 'response') and e.response is not None:
            print(f"[telegram] Response: {e.response.text}")
        return False

if __name__ == "__main__":
    # Локальный тест
    print("Testing Telegram Integration...")
    # Для теста можно временно подменить токены
    # config.ENABLE_TELEGRAM = True
    # config.TELEGRAM_BOT_TOKEN = "..."
    # config.TELEGRAM_CHAT_ID = "..."
    test_msg = "🚨 <b>Smart Zones Pro</b>\nТестовое сообщение об успешной интеграции!"
    send_telegram_message(test_msg)
