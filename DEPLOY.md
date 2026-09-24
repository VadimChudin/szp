# Развёртывание

Вся эмуляция (ПЛК и установка) работает в браузере. Сервер нужен только для
раздачи статики, у каждого пользователя — своя независимая симуляция.

## Вариант 1. Статика

```bash
scp -r frontend/ user@server:/var/www/lpzs/
```

```nginx
server {
    listen 80;
    server_name lpzs.example.ru;
    root /var/www/lpzs;
    index index.html;
    location / { try_files $uri $uri/ /index.html; }
    location ~* \.(webp|png|css|js)$ { expires 7d; }
}
```

## Вариант 2. Docker Compose

```bash
docker compose up -d --build
```

Открыть `http://<IP сервера>` (через nginx) или `http://<IP сервера>:8000`.
HTTPS: положите `fullchain.pem` и `privkey.pem` в `deploy/certs/` и снимите
комментарии с блока `listen 443` в `deploy/nginx.conf`.

## Вариант 3. systemd

```bash
sudo useradd -r -s /bin/false lpzs
sudo mkdir -p /opt/lpzs && sudo chown lpzs:lpzs /opt/lpzs
sudo -u lpzs cp -r backend frontend requirements.txt /opt/lpzs/
cd /opt/lpzs
sudo -u lpzs python3 -m venv .venv
sudo -u lpzs .venv/bin/pip install -r requirements.txt
sudo cp deploy/lpzs.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now lpzs
```

Сервис слушает `127.0.0.1:8000`; наружу его публикует nginx
(в `deploy/nginx.conf` замените `upstream` на `server 127.0.0.1:8000;`).

## Эндпоинты

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/` | Страница пульта |
| GET | `/css/*`, `/js/*`, `/assets/*` | Статика |
| GET | `/api/health` | Проверка живости для Docker и балансировщика |
