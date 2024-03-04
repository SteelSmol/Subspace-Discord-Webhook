import requests
from datetime import datetime, timedelta
import json
from urllib.parse import quote
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

def fetch_balance_history(address: str, days: int) -> list:
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)

    url = "https://subspace.webapi.subscan.io/api/scan/account/balance_history"
    payload = json.dumps({
        "address": address,
        "start": start_date.strftime('%Y-%m-%d'),
        "end": end_date.strftime('%Y-%m-%d')
    })
    headers = {
        'User-Agent': 'Apidog/1.0.0 (https://apidog.com)',
        'Content-Type': 'application/json'
    }

    response = requests.post(url, data=payload, headers=headers)
    if response.status_code == 200:
        data = response.json()
        return data['data']['history']
    else:
        print(f"Failed to fetch balance history for {address}: {response.status_code}, {response.text}")
        return []

def generate_quickchart_url(address: str, name: str, days: int = 7) -> str:
    data = fetch_balance_history(address, days)
    if not data:
        print(f"No data available to plot for {name}.")
        return ""

    dates = [datetime.strptime(item['date'], '%Y-%m-%d').strftime('%m-%d') for item in data]
    balances = [int(item['balance']) / 10**18 for item in data]  

    # Define the chart configuration
    chart_config = {
        "type": "line",
        "data": {
            "labels": dates,
            "datasets": [{
                "data": balances,
                "fill": True,  
                "backgroundColor": "rgba(114, 137, 218, 0.1)",
                "borderColor": "rgb(114, 137, 218)",
                "pointBackgroundColor": "rgb(114, 137, 218)",
                "pointBorderColor": "#fff",
                "pointHoverBackgroundColor": "#fff",
                "pointHoverBorderColor": "rgb(114, 137, 218)"
            }]
        },
        "options": {
            "legend": {
                "display": False  
            },
            "title": {
                "display": True,
                "text": f"Balance (Last {days} Days)",
                "fontColor": "#ffffff"
            },
            "scales": {
                "yAxes": [{
                    "gridLines": {
                        "color": "#444444"  
                    },
                    "ticks": {
                        "beginAtZero": False,  
                        "fontColor": "#ffffff"  
                    }
                }],
                "xAxes": [{
                    "gridLines": {
                        "color": "#444444"  
                    },
                    "ticks": {
                        "fontColor": "#ffffff"
                    }
                }]
            },
        }
    }

    # URL encode the chart configuration
    encoded_chart_config = quote(json.dumps(chart_config))

    # Generate the QuickChart URL
    quickchart_url = f"https://quickchart.io/chart?c={encoded_chart_config}"

    return quickchart_url

