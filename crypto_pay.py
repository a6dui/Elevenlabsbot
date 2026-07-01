import os
import aiohttp
import logging

# Fallback default token if environment variable is not exported
DEFAULT_CRYPTO_PAY_TOKEN = "583680:AAQV0SP1zNn2anQLh4W6qa6Yje8itsNpAt5"

logger = logging.getLogger("ElevenLabsCryptoPay")

def get_token() -> str:
    """Gets the active Crypto Pay token from environment variables or fallback."""
    token = os.environ.get("CRYPTO_PAY_TOKEN")
    if not token:
        token = os.environ.get("CRYPTO_PAY_API_TOKEN")
    if not token:
        token = os.environ.get("CRYPTO_BOT_TOKEN")
    if not token:
        token = os.environ.get("CRYPTO_BOT_API_TOKEN")
    return (token or DEFAULT_CRYPTO_PAY_TOKEN).strip().strip("'").strip('"')

async def get_api_url(token: str) -> str:
    """
    Dynamically auto-detects whether the token is for Mainnet or Testnet.
    Returns the appropriate base API URL.
    """
    if token.startswith("NS-"):
        logger.info("Crypto Bot API: Auto-detected Testnet via token prefix.")
        return "https://testnet-pay.crypt.bot/api"
    else:
        logger.info("Crypto Bot API: Auto-detected Mainnet via token prefix.")
        return "https://pay.crypt.bot/api"

async def create_cryptobot_invoice(amount_rub: float) -> dict:
    """
    Creates a Crypto Bot invoice for the specified amount in RUB.
    Returns a dict with 'invoice_id' and 'pay_url' if successful, or None.
    """
    token = get_token()
    api_url = await get_api_url(token)
    
    url = f"{api_url}/createInvoice"
    headers = {
        "Crypto-Pay-API-Token": token
    }
    
    # Try using official fiat billing (amount in RUB, paid in USDT/TON)
    payload = {
        "amount": str(amount_rub),
        "currency_type": "fiat",
        "fiat": "RUB",
        "accepted_assets": "USDT,TON",
        "description": f"Покупка подписки ElevenLabs Voice ({amount_rub} ₽)"
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                data = await resp.json()
                if resp.status == 200 and data.get("ok"):
                    result = data["result"]
                    return {
                        "invoice_id": result["invoice_id"],
                        "pay_url": result["pay_url"],
                        "amount_rub": amount_rub
                    }
                logger.error(f"Failed to create fiat invoice: {data}")
    except Exception as e:
        logger.error(f"Error creating Crypto Bot fiat invoice: {e}")
    
    # Fallback to direct USDT invoice if fiat option is unsupported/fails
    try:
        usdt_amount = round(amount_rub / 95.0, 2)
        if usdt_amount < 0.01:
            usdt_amount = 0.01
            
        payload_fallback = {
            "asset": "USDT",
            "amount": str(usdt_amount),
            "description": f"Покупка подписки ElevenLabs Voice ({amount_rub} ₽)"
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload_fallback) as resp:
                data = await resp.json()
                if resp.status == 200 and data.get("ok"):
                    result = data["result"]
                    return {
                        "invoice_id": result["invoice_id"],
                        "pay_url": result["pay_url"],
                        "amount_rub": amount_rub,
                        "is_fallback": True,
                        "usdt_amount": usdt_amount
                    }
                logger.error(f"Failed to create direct USDT fallback invoice: {data}")
    except Exception as e:
        logger.error(f"Fallback Crypto Bot invoice creation also failed: {e}")
        
    return None

async def get_invoice_status(invoice_id) -> str:
    """
    Checks the status of a specific invoice.
    Returns the status string (e.g., 'paid', 'active', 'expired') or None.
    """
    token = get_token()
    api_url = await get_api_url(token)
    
    url = f"{api_url}/getInvoices"
    headers = {
        "Crypto-Pay-API-Token": token
    }
    params = {
        "invoice_ids": str(invoice_id)
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("ok"):
                        invoices = data["result"].get("items", [])
                        if invoices:
                            return invoices[0]["status"]
    except Exception as e:
        logger.error(f"Error checking Crypto Bot invoice: {e}")
    return None
