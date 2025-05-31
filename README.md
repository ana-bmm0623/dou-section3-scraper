# Scraper da Seção 3 do Diário Oficial da União (DOU)

Um script em Python para automatizar a raspagem de PDFs da Seção 3 do Diário Oficial da União (DOU) do Brasil, buscar por um nome específico e a palavra-chave "Convocação", e enviar os resultados via Telegram. Projetado para rodar continuamente em uma máquina virtual Ubuntu usando um serviço systemd.

## Funcionalidades
*   Raspa PDFs da Seção 3 do DOU de 1º de novembro de 2024 até o último dia útil (exemplo: 30 de maio de 2025).
*   Envia notificações no Telegram em ordem cronológica para processamento histórico.
*   Ignora fins de semana e feriados brasileiros.
*   Retoma a partir da última data processada.
*   Lida com erros (PDFs inválidos, problemas de servidor) com tentativas de repetição e registro detalhado.
*   Executa verificações diárias às 6h da manhã após o processamento histórico.

## Requisitos
*   Ubuntu 24.10 (ou compatível)
*   Python 3.12 ou superior
*   Dependências Python:
    *   `aiohttp`
    *   `beautifulsoup4`
    *   `pdfplumber`
    *   `python-telegram-bot`
    *   `PyPDF2`
*   Token de bot do Telegram (obtido via BotFather) e ID do chat

## Configuração

### 1. Instalar Pré-requisitos
Atualize o sistema e instale as dependências necessárias:
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv curl ufw
sudo ufw allow 80
sudo ufw allow 443
sudo ufw enable
```

### 2. Criar Ambiente Virtual
Crie e ative um ambiente virtual para isolar as dependências:
```bash
python3 -m venv ~/.venv
source ~/.venv/bin/activate
pip install aiohttp beautifulsoup4 pdfplumber python-telegram-bot PyPDF2 python-dotenv
```

### 3. Configurar o Script
Copie o arquivo `dou_daily_scraper.py` para o diretório desejado (exemplo: `/root/` ou `/home/usuario/`).

Crie um arquivo `.env` na mesma pasta, com o seguinte conteúdo:
```env
YOUR_NAME="Seu nome completo (ex: João Silva)"
TELEGRAM_TOKEN="Seu token do bot Telegram"
CHAT_ID="Seu chat ID do Telegram"
```
**Importante:** Nunca envie o arquivo `.env` para o GitHub! Adicione-o ao `.gitignore`.

Edite o `dou_daily_scraper.py` para carregar essas variáveis do `.env` usando `python-dotenv`.

Defina permissões de execução para o script:
```bash
chmod +x dou_daily_scraper.py
```

### 4. Configurar Serviço systemd
Crie um serviço systemd para executar o script continuamente:
```bash
sudo nano /etc/systemd/system/dou-scraper.service
```
Adicione o conteúdo abaixo, ajustando o usuário e os caminhos conforme sua instalação:
```ini
[Unit]
Description=Scraper da Seção 3 do DOU
After=network-online.target
Wants=network-online.target

[Service]
User=root
WorkingDirectory=/root
ExecStart=/root/.venv/bin/python3 /root/dou_daily_scraper.py
Restart=always
RestartSec=60
Environment="PYTHONUNBUFFERED=1"

[Install]
WantedBy=multi-user.target
```
Ative e inicie o serviço:
```bash
sudo systemctl daemon-reload
sudo systemctl enable dou-scraper.service
sudo systemctl start dou-scraper.service
```

### 5. Configurar Rotação de Logs
Crie uma configuração para o logrotate para gerenciar o arquivo de log:
```bash
sudo nano /etc/logrotate.d/dou-scraper
```
Adicione:
```lua
/root/dou_scraper.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
    create 0644 root root
}
```
Teste a rotação:
```bash
sudo logrotate -f /etc/logrotate.d/dou-scraper
```

## Uso

### Monitorar Logs
Verifique o progresso do script e erros:
```bash
tail -f /root/dou_scraper.log
```
Procure mensagens como:
```css
Processando DOU para [data]
Mensagem de texto enviada para [data]
```

### Verificar Status do Serviço
Confirme que o serviço está ativo e rodando:
```bash
sudo systemctl status dou-scraper.service
```

### Notificações no Telegram
As mensagens enviadas ao Telegram terão este formato:

Caso não encontre entradas:
```kotlin
ℹ️ Nenhuma entrada para '[SEU_NOME]' encontrada no DOU de [data] (Seção 3).
```
Caso encontre:
```yaml
🚨 Entradas encontradas para '[SEU_NOME]' no DOU de [data] (Seção 3):
📄 Página X:
[Texto da entrada]

---
```

## Notas
*   O processamento histórico cobre de 1º de novembro de 2024 até o último dia útil (exemplo: 30 de maio de 2025).
*   As verificações diárias iniciam às 6h da manhã, pulando fins de semana e feriados.
*   Erros são registrados no arquivo `dou_scraper.log` para facilitar a depuração.
*   Requer conexão estável com a internet e acesso ao domínio `pesquisa.in.gov.br`.
*   Para problemas com downloads de PDF, como “Conteúdo não é PDF”, verifique os logs para mais detalhes.

## Solução de Problemas
Para ver os últimos erros no log:
```bash
tail -n 100 /root/dou_scraper.log
```
Para testar URLs manualmente:
```bash
curl -I [url_do_log]
```
Problemas com Telegram:
*   Verifique se o token do bot e chat ID estão corretos, usando `@BotFather` e `@userinfobot` no Telegram.

Serviço systemd parado:
```bash
journalctl -u dou-scraper.service -n 100
```

## Licença
MIT License — livre para uso e modificação.
