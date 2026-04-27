import requests
import time
import logging
import schedule
import sqlite3
import signal
import sys
import os
from bs4 import BeautifulSoup
from datetime import datetime

CONFIG = {
    "telegram": {
        "bot_token": "ENTER_YOUR_BOT_TOKEN_HERE",
        "chat_id": "ENTER_YOUR_CHAT_ID_HERE"
    },
    "settings": {
        "check_interval_minutes": 60,
        "db_name": "market_data.db"
    },
    "products": [
        {
            "name": "Client Product 1",
            "url": "https://www.example.com/product-url",
            "selectors": [".price", "#priceblock_ourprice", "span.a-price-whole"],
            "target_price": 150.00
        }
    ]
}

class CMDFormatter(logging.Formatter):
    def format(self, record):
        time_str = datetime.fromtimestamp(record.created).strftime('%H:%M:%S')
        if record.levelno >= logging.ERROR:
            sym = "[-]"
        elif record.levelno >= logging.WARNING:
            sym = "[!]"
        else:
            sym = "[+]" if "Found" in record.getMessage() or "Success" in record.getMessage() or "started" in record.getMessage() else "[*]"
        return f"{sym} [{time_str}] {record.getMessage()}"

logger = logging.getLogger()
logger.setLevel(logging.INFO)
file_handler = logging.FileHandler("saas_backend.log", encoding='utf-8')
console_handler = logging.StreamHandler(sys.stdout)
formatter = CMDFormatter()
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)
logger.addHandler(file_handler)
logger.addHandler(console_handler)

class PriceMonitorSaaS:
    def __init__(self, config):
        self.config = config
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        self.running = True
        
        self.db_conn = sqlite3.connect(self.config["settings"]["db_name"], check_same_thread=False)
        self.setup_database()

        signal.signal(signal.SIGINT, self.shutdown_handler)
        signal.signal(signal.SIGTERM, self.shutdown_handler)

    def setup_database(self):
        cursor = self.db_conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                product_name TEXT,
                price REAL
            )
        ''')
        self.db_conn.commit()
        logging.info("Database initialized successfully.")

    def shutdown_handler(self, signum, frame):
        logging.warning("Graceful shutdown initiated. Saving state...")
        self.running = False
        self.db_conn.close()
        logging.info("System offline.")
        sys.exit(0)

    def send_telegram_alert(self, message):
        token = self.config["telegram"]["bot_token"]
        chat_id = self.config["telegram"]["chat_id"]
        
        if token == "ENTER_YOUR_BOT_TOKEN_HERE" or not token:
            logging.info(f"ALERT (Telegram missing setup): \n{message}")
            return

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        try:
            response = requests.post(url, json={"chat_id": chat_id, "text": message}, timeout=10)
            if response.status_code == 200:
                logging.info("Telegram alert sent successfully.")
            else:
                logging.error(f"Telegram API Error: {response.text}")
        except Exception as e:
            logging.error(f"Telegram request failed: {e}")

    def save_to_db(self, product_name, price):
        try:
            cursor = self.db_conn.cursor()
            cursor.execute("INSERT INTO price_history (product_name, price) VALUES (?, ?)", (product_name, price))
            self.db_conn.commit()
        except Exception as e:
            logging.error(f"Database write error: {e}")

    def fetch_price(self, product):
        logging.info(f"Fetching: {product['name']}")
        try:
            response = requests.get(product["url"], headers=self.headers, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            price = None
            for selector in product["selectors"]:
                element = soup.select_one(selector)
                if element:
                    clean_str = "".join(c for c in element.get_text() if c.isdigit() or c in ".,").replace(",", ".")
                    try:
                        price = float(clean_str)
                        break
                    except ValueError:
                        continue
            
            if price is not None:
                logging.info(f"Found price for {product['name']}: {price}")
                self.save_to_db(product['name'], price)
                
                if price <= product["target_price"]:
                    logging.warning(f"PRICE DROP ALERT for {product['name']}! ({price})")
                    msg = f"🚨 PRICE DROP ALERT 🚨\nProduct: {product['name']}\nNew Price: {price}\nTarget: {product['target_price']}\nLink: {product['url']}"
                    self.send_telegram_alert(msg)
            else:
                logging.error(f"All selectors failed for {product['name']}")
                
        except requests.exceptions.RequestException as e:
            logging.error(f"Network error fetching {product['name']}: {e}")
        except Exception as e:
            logging.error(f"Unexpected error processing {product['name']}: {e}")

    def job(self):
        logging.info(f"{'='*40}")
        logging.info("Running scheduled data collection cycle...")
        for prod in self.config["products"]:
            self.fetch_price(prod)
        logging.info("Cycle complete. Waiting for next interval.")
        logging.info(f"{'='*40}")

    def run_forever(self):
        interval = self.config["settings"]["check_interval_minutes"]
        schedule.every(interval).minutes.do(self.job)
        
        os.system('cls' if os.name == 'nt' else 'clear')
        logging.info(f"SaaS Backend Service started.")
        logging.info(f"Monitoring interval: {interval} minutes.")
        logging.info(f"Press Ctrl+C to safely stop the service.")
        
        self.job()
        
        while self.running:
            try:
                schedule.run_pending()
                time.sleep(1)
            except KeyboardInterrupt:
                self.shutdown_handler(signal.SIGINT, None)

if __name__ == "__main__":
    service = PriceMonitorSaaS(CONFIG)
    service.run_forever()