import logging
import os
import requests
import time
import json
from datetime import datetime, timedelta
import pytz
from dotenv import load_dotenv
from substrateinterface import SubstrateInterface
from typing import Dict, Optional
from graph import generate_quickchart_url  

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Define global variables for configuration
DISCORD_URL = os.getenv('DISCORD_WEBHOOK_URL')
NODE_IP = os.getenv('NODE_IP', '127.0.0.1')
NODE_PORT = os.getenv('NODE_PORT', '9944')
WAIT_PERIOD = int(os.getenv('WAIT_PERIOD', 300))

# Initialize the SubstrateInterface
substrate = SubstrateInterface(url=f"ws://{NODE_IP}:{NODE_PORT}")

def load_wallets() -> Dict[str, str]:
    wallets = {}
    i = 1
    while True:
        wallet_address = os.getenv(f'WALLET_{i}_ADDRESS')
        wallet_name = os.getenv(f'WALLET_{i}_NAME')
        if wallet_address and wallet_name:
            wallets[wallet_address] = wallet_name
            i += 1
        else:
            break
    return wallets

def query_wallet(wallet_address: str) -> dict:
    return substrate.query("System", "Account", [wallet_address])

def fetch_daily_gains(address: str) -> str:
    # Calculate the Unix timestamp for the previous day at 23:59 UTC
    previous_day_timestamp = datetime.now(pytz.utc) - timedelta(days=1)
    previous_day_timestamp = previous_day_timestamp.replace(hour=23, minute=59, second=0, microsecond=0)
    unix_timestamp = int(previous_day_timestamp.timestamp())

    # Use the Subscan API to find the closest block number
    url = "https://subspace.api.subscan.io/api/scan/block"
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    payload = {"block_timestamp": unix_timestamp}

    response = requests.post(url, json=payload, headers=headers)
    if response.status_code == 200:
        data = response.json()
        block_number = data.get("data", {}).get("block_num")

        # Query the balance at the closest block
        previous_day_balance_info = substrate.query(module='System', storage_function='Account', params=[address], block_hash=substrate.get_block_hash(block_number))
        previous_day_balance = previous_day_balance_info.value['data']['free']

        # Query the current balance
        current_balance_info = substrate.query(module='System', storage_function='Account', params=[address])
        current_balance = current_balance_info.value['data']['free']

        # Calculate the balance gain and adjust for token decimal places
        gain = max(0, current_balance - previous_day_balance)  # Ensure the result is non-negative
        gain_adjusted = gain / 10**18  # Adjust for token's decimal places
        
        # Format the result to show two decimal places
        gain_formatted = "{:.2f}".format(gain_adjusted)

        return gain_formatted
    else:
        return "0.00"


def format_message(name: str, balance: float, daily_gains: str, balance_change: float, wallet_address: str, chart_url: str) -> Dict:
    timestamp = datetime.utcnow().isoformat() + 'Z'
    explorer_url = f"https://subspace.subscan.io/account/{wallet_address}?tab=balance_history"
    embed = {
        "content": None,
        "embeds": [{
            "title": name,
            "description": f"Balance: {balance:.2f} tSSC  (Change {balance_change:+.2f})\n"
                           f"Gains Today: +{daily_gains} tSSC\n"
                           f"[View on Subscan Explorer]({explorer_url})",
            "color": 16448250,
            "author": {
                "name": "Subspace Rewards",
                "icon_url": "https://pbs.twimg.com/profile_images/1382564944198078464/-7D9uyig_400x400.jpg"
            },
            "image": {
                "url": chart_url
            },
            "timestamp": timestamp
        }],
    }
    return embed  

def send(embed: Dict):
    headers = {"Content-Type": "application/json"}
    data = json.dumps(embed)  
    try:
        response = requests.post(DISCORD_URL, json=embed, headers=headers)
        response.raise_for_status() 
    except requests.exceptions.RequestException as e:
        logging.error(f'Error sending to Discord: {e}')
        
def save_balances_to_json(balances: dict, filepath: str = 'wallet_balances.json'):
        with open(filepath, 'w') as file:
            json.dump(balances, file)

def load_balances_from_json(filepath: str = 'wallet_balances.json') -> dict:
    try:
        with open(filepath, 'r') as file:
            balances = json.load(file)
        return balances
    except FileNotFoundError:
        logging.info("No existing balances file found. Starting fresh.")
        return {}
    except Exception as e:
        return {}

def wallet_monitor(wallets: Dict[str, str]) -> None:
    logging.info('Monitoring started. Querying initial balances...')
    last_known_balances = load_balances_from_json()  # Load balances from JSON

    try:
        while True:
            for wallet, name in wallets.items():
                account_info = query_wallet(wallet)
                balance_free = account_info.value["data"]["free"]
                balance_reserved = account_info.value["data"]["reserved"]
                balance_total = balance_free + balance_reserved
                balance_from_exp = balance_total / 10 ** substrate.properties.get('tokenDecimals', 0)

                if wallet in last_known_balances:
                    # Calculate balance_change only if the wallet was previously known
                    balance_change = balance_from_exp - last_known_balances[wallet]
                    if balance_change != 0:
                        logging.info(f'Detected balance change for {name}: {balance_change:+.2f} tSSC')
                        daily_gains = fetch_daily_gains(wallet)  # Fetch daily gains
                        chart_url = generate_quickchart_url(wallet, name)  # Generate chart URL
                        message = format_message(name, balance_from_exp, daily_gains, balance_change, wallet, chart_url)
                        send(message)
                else:
                    logging.info(f'New wallet detected: {name}, initializing balance.')

                # Update the last known balance after checking for changes
                last_known_balances[wallet] = balance_from_exp

            save_balances_to_json(last_known_balances)
            logging.info('Balance query completed. Waiting for the next check...')
            time.sleep(WAIT_PERIOD)

    except Exception as e:
        logging.error(f'Error encountered: {e}')

if __name__ == '__main__':
    wallets = load_wallets()
    wallet_monitor(wallets)