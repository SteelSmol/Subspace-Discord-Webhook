import logging
import os
import requests
import time
import json
from datetime import datetime
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

def fetch_daily_gains(address: str) -> float:
    # Fetch the balance history from the API for the given address
    end_date = datetime.utcnow()
    start_date = datetime(2024, 2, 14)  # Adjust the start date as necessary
    url = "https://subspace.webapi.subscan.io/api/scan/account/balance_history"
    payload = json.dumps({"address": address, "start": start_date.strftime('%Y-%m-%d'), "end": end_date.strftime('%Y-%m-%d')})
    headers = {'User-Agent': 'Apidog/1.0.0 (https://apidog.com)', 'Content-Type': 'application/json'}
    response = requests.post(url, data=payload, headers=headers)
    
    if response.status_code == 200:
        data = response.json()
        history = data['data']['history']
        
        if history:
            # Assume the last entry in the history is the balance at the end of the previous day
            latest_history_balance = int(history[-1]['balance'])
            
            # Fetch the current balance directly from the node
            current_balance_info = substrate.query("System", "Account", [address])
            current_balance = int(current_balance_info.value["data"]["free"])
            
            # Calculate daily gains by comparing the current balance to the latest balance from history
            # Convert both balances to a decimal representation based on the token's decimals
            token_decimals = substrate.properties.get('tokenDecimals', 18)  # Defaulting to 18 if not specified
            daily_gains = (current_balance - latest_history_balance) / 10**token_decimals
            return daily_gains
    else:
        logging.error(f"Failed to fetch daily gains for {address}: {response.status_code}, {response.text}")
        return 0.0


def format_message(name: str, balance: float, daily_gains: float, balance_change: float, wallet_address: str, chart_url: str) -> Dict:
    timestamp = datetime.utcnow().isoformat() + 'Z'
    explorer_url = f"https://subspace.subscan.io/account/{wallet_address}?tab=balance_history"
    embed = {
        "content": None,
        "embeds": [{
            "title": name,
            "description": f"Balance: {balance:.2f} tSSC  (Change {balance_change:+.2f})\n"
                           f"Gains Today: +{daily_gains:.2f} tSSC\n"
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