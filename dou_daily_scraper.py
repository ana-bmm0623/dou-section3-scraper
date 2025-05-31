import aiohttp
import asyncio
from bs4 import BeautifulSoup
import pdfplumber
from telegram import Bot
import os
from datetime import datetime, timedelta
import logging
import re
from urllib.parse import urljoin
import PyPDF2

# Configure logging to file and console with UTF-8 encoding
script_dir = os.path.abspath(os.path.dirname(__file__))
log_file_path = os.path.join(script_dir, "dou_scraper.log")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s',
    handlers=[
        logging.FileHandler(log_file_path, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# Configuration constants - Replace with your own values
YOUR_NAME = "YOUR_NAME_HERE"  # Name to search in PDFs (e.g., "John Doe")
TELEGRAM_TOKEN = "YOUR_TELEGRAM_TOKEN_HERE"  # Telegram bot token from BotFather
CHAT_ID = "YOUR_CHAT_ID_HERE"  # Telegram chat ID for notifications
PDF_PATH = os.path.join(script_dir, "dou_latest_{}.pdf")  # Template for temporary PDF files
LAST_DATE_FILE = os.path.join(script_dir, "last_processed_date.txt")  # File to store last processed date

# List of Brazilian holidays (DD-MM-YYYY) to skip
HOLIDAYS = [
    "01-01-2024", "20-04-2024", "01-05-2024", "07-09-2024", "12-10-2024",
    "02-11-2024", "15-11-2024", "20-11-2024", "25-12-2024",
    "01-01-2025", "20-04-2025", "01-05-2025", "07-09-2025", "12-10-2025",
    "02-11-2025", "15-11-2025", "20-11-2025", "25-12-2025"
]

def is_valid_pdf(file_path):
    """Validate if a file is a proper PDF using PyPDF2."""
    try:
        with open(file_path, "rb") as f:
            PyPDF2.PdfReader(f)
        return True
    except Exception as e:
        logging.error(f"Arquivo {file_path} não é um PDF válido: {e}")
        return False

def save_last_processed_date(date_str):
    """Save the last processed date to a file."""
    try:
        with open(LAST_DATE_FILE, "w", encoding='utf-8') as f:
            f.write(date_str)
        logging.info(f"Data processada salva: {date_str}")
    except Exception as e:
        logging.error(f"Erro ao salvar data processada: {e}")

def load_last_processed_date():
    """Load the last processed date from a file."""
    try:
        if os.path.exists(LAST_DATE_FILE):
            with open(LAST_DATE_FILE, "r", encoding='utf-8') as f:
                date_str = f.read().strip()
                return datetime.strptime(date_str, "%d-%m-%Y")
        return None
    except Exception as e:
        logging.error(f"Erro ao carregar data processada: {e}")
        return None

async def get_dou_section3_pdf_url(session, target_date: datetime):
    """Fetch the URL of the DOU Section 3 PDF for a given date."""
    search_page_url = "https://pesquisa.in.gov.br/imprensa/core/jornalList.action"
    date_dd_mm = target_date.strftime("%d/%m")
    year_yyyy = str(target_date.year)

    # Payload for the POST request to search for DOU Section 3
    payload = {
        "edicao.txtPesquisa": "",
        "edicao.dtInicio": date_dd_mm,
        "edicao.dtFim": date_dd_mm,
        "edicao.ano": year_yyyy,
        "edicao.jornal": "3,3000,3020,1040,526,530,608,609,610,611",
        "edicao.fonetica": "null",
        "jornal": "do3",
        "t": "com.liferay.journal.model.JournalArticle"
    }

    leitura_jornal_date_str = target_date.strftime("%d-%m-%Y")
    referer_url = f"https://www.in.gov.br/leiturajornal?data={leitura_jornal_date_str}&secao=do3"

    # Headers to mimic a browser request
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://www.in.gov.br",
        "Referer": referer_url,
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
    }

    try:
        # Pre-fetch referer URL to set session state
        async with session.get(referer_url, headers=headers, timeout=15) as resp:
            resp.raise_for_status()
        # Post request to get the journal list
        async with session.post(search_page_url, data=payload, headers=headers, timeout=30) as response:
            response.raise_for_status()
            text = await response.text()
    except aiohttp.ClientResponseError as e:
        if e.status == 500:
            logging.warning(f"Erro 500 do servidor para {target_date.strftime('%d/%m/%Y')}: {e}")
        else:
            logging.error(f"Erro HTTP na requisição para {search_page_url} em {target_date.strftime('%d/%m/%Y')}: {e}")
        return None
    except aiohttp.ClientError as e:
        logging.error(f"Erro de conexão para {search_page_url} em {target_date.strftime('%d/%m/%Y')}: {e}")
        return None
    except asyncio.TimeoutError:
        logging.error(f"Timeout na requisição para {search_page_url} em {target_date.strftime('%d/%m/%Y')}")
        return None

    # Parse the response to find the PDF URL
    soup = BeautifulSoup(text, "html.parser")
    table = soup.find("table", id="ResultadoConsulta")
    if not table:
        logging.warning(f"Tabela 'ResultadoConsulta' não encontrada para {target_date.strftime('%d/%m/%Y')}")
        return None

    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        journal_name_tag = cells[0].find("a")
        if journal_name_tag:
            journal_text = journal_name_tag.get_text(strip=True).lower()
            if "diário oficial da união - seção 3" in journal_text and "extra" not in journal_text:
                download_cell = cells[-1]
                link_tag = download_cell.find("a", onclick=True, title=lambda t: t and "download da edição completa" in t.lower())
                if link_tag:
                    onclick_value = link_tag.get("onclick")
                    match = re.search(r"redirecionaSelect\('(.*?)'\);", onclick_value)
                    if match:
                        extracted_url = match.group(1)
                        pdf_url = extracted_url.replace('&', '&')
                        if not pdf_url.startswith("http"):
                            pdf_url = urljoin("https://pesquisa.in.gov.br/imprensa/core/", pdf_url)
                        logging.info(f"URL do PDF encontrada: {pdf_url}")
                        return pdf_url
    logging.warning(f"Nenhum PDF da Seção 3 encontrado para {target_date.strftime('%d/%m/%Y')}")
    return None

async def download_dou(session, pdf_url, date_str):
    """Download the DOU PDF from the given URL and validate it."""
    if not pdf_url:
        logging.error(f"Nenhuma URL de PDF fornecida para {date_str}")
        return None
    pdf_path = PDF_PATH.format(date_str.replace("-", ""))
    try:
        async with session.get(pdf_url, timeout=60) as response:
            response.raise_for_status()
            content_type = response.headers.get('Content-Type', '').lower()
            if 'application/pdf' not in content_type:
                # Log response details for debugging
                content = await response.text()
                logging.error(f"Conteúdo não é PDF para {date_str}: Content-Type={content_type}, Status={response.status}, URL={pdf_url}")
                logging.debug(f"Resposta do servidor: {content[:500]}...")
                return None
            content = await response.read()
            with open(pdf_path, "wb") as f:
                f.write(content)
        if is_valid_pdf(pdf_path):
            logging.info(f"PDF baixado para {date_str}: {pdf_path}")
            return pdf_path
        else:
            os.remove(pdf_path)
            logging.error(f"PDF inválido removido: {pdf_path}")
            return None
    except aiohttp.ClientResponseError as e:
        logging.error(f"Erro HTTP ao baixar PDF de {pdf_url} para {date_str}: {e}")
        return None
    except aiohttp.ClientConnectionError as e:
        logging.error(f"Erro de conexão ao baixar PDF de {pdf_url} para {date_str}: {e}")
        return None
    except asyncio.TimeoutError:
        logging.error(f"Timeout ao baixar PDF de {pdf_url} para {date_str}")
        return None
    except Exception as e:
        logging.error(f"Erro inesperado ao baixar PDF de {pdf_url} para {date_str}: {e}", exc_info=True)
        return None

def search_entries(pdf_path, name, keyword="Convocação"):
    """Search the PDF for lines containing the name and keyword."""
    if not pdf_path or not os.path.exists(pdf_path):
        logging.error(f"Arquivo PDF não encontrado: {pdf_path}")
        return []
    try:
        entries = []
        name_lower = name.lower()
        keyword_lower = keyword.lower()
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                text = page.extract_text()
                if not text:
                    continue
                for line in text.splitlines():
                    line_lower = line.lower()
                    if name_lower in line_lower and keyword_lower in line_lower:
                        entries.append({
                            "page": page_num,
                            "text": line.strip(),
                            "section": "Seção 3"
                        })
        logging.info(f"{len(entries)} entradas encontradas para '{name}' em {pdf_path}")
        return entries
    except Exception as e:
        logging.error(f"Erro ao extrair texto do PDF {pdf_path}: {e}")
        return []

async def send_to_telegram(entries, date_str, pdf_path=None):
    """Send search results to Telegram, attaching the PDF if entries are found."""
    bot = Bot(token=TELEGRAM_TOKEN)
    max_len = 4096
    date_formatted = datetime.strptime(date_str, "%d-%m-%Y").strftime("%d/%m/%Y")

    if entries:
        message = f"🚨 *Entradas encontradas* para '{YOUR_NAME}' no DOU de {date_formatted} (Seção 3):\n\n"
        for entry in entries:
            message += f"📄 *Página {entry['page']}*:\n{entry['text']}\n\n---\n\n"
        if pdf_path and os.path.exists(pdf_path):
            message += "📎 PDF do DOU anexado abaixo."
    else:
        message = f"ℹ️ Nenhuma entrada para '{YOUR_NAME}' encontrada no DOU de {date_formatted} (Seção 3)."

    # Split long messages to comply with Telegram's 4096-char limit
    if len(message) > max_len:
        parts = [message[i:i+max_len] for i in range(0, len(message), max_len)]
        for i, part in enumerate(parts, 1):
            try:
                await bot.send_message(chat_id=CHAT_ID, text=part, parse_mode="Markdown")
                logging.info(f"Parte {i}/{len(parts)} da mensagem enviada para {date_str}")
                await asyncio.sleep(1)
            except Exception as e:
                logging.error(f"Erro ao enviar parte {i}/{len(parts)} para {date_str}: {e}")
    else:
        try:
            await bot.send_message(chat_id=CHAT_ID, text=message, parse_mode="Markdown")
            logging.info(f"Mensagem de texto enviada para {date_str}")
        except Exception as e:
            logging.error(f"Erro ao enviar mensagem para {date_str}: {e}")

    # Send PDF if entries are found and PDF exists
    if entries and pdf_path and os.path.exists(pdf_path):
        try:
            if os.path.getsize(pdf_path) > 20 * 1024 * 1024:
                logging.warning(f"PDF {pdf_path} excede 20MB, não enviado")
                await bot.send_message(chat_id=CHAT_ID, text="PDF muito grande para enviar (>20MB).")
            else:
                with open(pdf_path, "rb") as f:
                    await bot.send_document(chat_id=CHAT_ID, document=f, caption=f"DOU Seção 3 - {date_formatted}")
                logging.info(f"PDF enviado para {date_str}")
        except Exception as e:
            logging.error(f"Erro ao enviar PDF para {date_str}: {e}")

async def process_dou_date(session, target_date: datetime, max_retries=3):
    """Process a single DOU date: fetch PDF, search, and send results."""
    date_str = target_date.strftime("%d-%m-%Y")
    logging.info(f"Processando DOU para {date_str}")
    pdf_path = None
    try:
        # Skip future dates
        if target_date.date() > datetime.now().date():
            logging.warning(f"Data {date_str} está no futuro, pulando")
            return [], date_str, None

        for attempt in range(max_retries):
            pdf_url = await get_dou_section3_pdf_url(session, target_date)
            if pdf_url:
                pdf_path = await download_dou(session, pdf_url, date_str)
                if pdf_path:
                    entries = search_entries(pdf_path, YOUR_NAME)
                    save_last_processed_date(date_str)
                    return entries, date_str, pdf_path
            logging.warning(f"Tentativa {attempt+1}/{max_retries} falhou para {date_str}")
            await asyncio.sleep(20 * (attempt + 1))  # Retry delays: 20s, 40s, 60s
        logging.error(f"Falha após {max_retries} tentativas para {date_str}")
        save_last_processed_date(date_str)
        return [], date_str, None
    finally:
        if pdf_path and os.path.exists(pdf_path):
            try:
                os.remove(pdf_path)
                logging.info(f"PDF temporário removido: {pdf_path}")
            except Exception as e:
                logging.error(f"Erro ao remover PDF {pdf_path}: {e}")

async def process_historical_dous(end_date):
    """Process historical DOUs from start_date to end_date in batches."""
    start_date = datetime(2024, 11, 1)  # Adjusted to match your VM setup
    last_processed = load_last_processed_date()
    if last_processed and last_processed >= start_date:
        current_date = last_processed + timedelta(days=1)
        logging.info(f"Retomando processamento histórico a partir de {current_date.strftime('%d/%m/%Y')}")
    else:
        current_date = start_date

    # Adjust end_date to last business day before or on today
    today = datetime.now().date()
    if end_date.date() > today:
        end_date = datetime.now()
        while end_date.weekday() >= 5 or end_date.strftime("%d-%m-%Y") in HOLIDAYS:
            end_date -= timedelta(days=1)
        logging.info(f"Ajustando end_date para último dia útil: {end_date.strftime('%d/%m/%Y')}")

    days_processed = 0
    tasks = []
    results = []

    async with aiohttp.ClientSession() as session:
        logging.info(f"Processando DOUs históricos de {current_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}")
        while current_date <= end_date:
            date_str = current_date.strftime("%d-%m-%Y")
            if current_date.weekday() >= 5 or date_str in HOLIDAYS:
                logging.info(f"Pulando {date_str} (fim de semana ou feriado)")
            else:
                tasks.append(process_dou_date(session, current_date))
                days_processed += 1
                if len(tasks) >= 2:  # Process in batches of 2
                    batch_results = await asyncio.gather(*tasks, return_exceptions=True)
                    results.extend([r for r in batch_results if not isinstance(r, Exception)])
                    tasks = []
                    # Sort results by date for chronological Telegram messages
                    results.sort(key=lambda x: datetime.strptime(x[1], "%d-%m-%Y"))
                    for entries, date_str, pdf_path in results:
                        await send_to_telegram(entries, date_str, pdf_path)
                    results = []
                    await asyncio.sleep(10)  # Delay between batches
            current_date += timedelta(days=1)

        if tasks:
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            results.extend([r for r in batch_results if not isinstance(r, Exception)])
            results.sort(key=lambda x: datetime.strptime(x[1], "%d-%m-%Y"))
            for entries, date_str, pdf_path in results:
                await send_to_telegram(entries, date_str, pdf_path)

        logging.info(f"Processamento histórico concluído. {days_processed} dias processados.")

async def process_daily_dou():
    """Run daily DOU checks at 6:00 AM, skipping weekends and holidays."""
    while True:
        try:
            current_date = datetime.now()
            date_str = current_date.strftime("%d-%m-%Y")
            if current_date.weekday() >= 5 or date_str in HOLIDAYS:
                logging.info(f"Pulando {date_str} (fim de semana ou feriado)")
            else:
                async with aiohttp.ClientSession() as session:
                    entries, date_str, pdf_path = await process_dou_date(session, current_date)
                    await send_to_telegram(entries, date_str, pdf_path)

            # Schedule next run at 6:00 AM
            next_run = (current_date + timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)
            sleep_seconds = (next_run - datetime.now()).total_seconds()
            if sleep_seconds > 0:
                logging.info(f"Aguardando até {next_run.strftime('%d/%m/%Y %H:%M:%S')} para a próxima execução")
                await asyncio.sleep(sleep_seconds)
            else:
                logging.warning("Tempo de espera negativo, executando imediatamente")
        except Exception as e:
            logging.error(f"Erro no loop diário: {e}", exc_info=True)
            await asyncio.sleep(300)  # Wait 5 minutes before retrying

async def main():
    """Main function to run historical and daily processing."""
    logging.info("Iniciando scraper do Diário Oficial da União - Processamento Contínuo")
    end_date = datetime(2025, 5, 31)
    current_date = datetime.now()

    if current_date.date() <= end_date.date():
        await process_historical_dous(end_date)

    logging.info("Iniciando loop de processamento diário")
    await process_daily_dou()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Script interrompido pelo usuário")
    except Exception as e:
        logging.critical(f"Erro crítico: {e}", exc_info=True)
        time.sleep(60)
        asyncio.run(main())