#!/usr/bin/env bash
# Прокси с российским адресом для стенда за рубежом — одной командой на любом российском VPS (Ubuntu 22.04/24.04).
#
# Зачем: стенд стоит в Нидерландах, а часть российских госсайтов (ЕИС госзакупок, Роспатент) из-за рубежа отвечает
# нестабильно. Приложение отправляет только эти сайты через прокси (RU_PROXY_HOSTS), всё остальное — напрямую;
# если прокси недоступен, запрос автоматически идёт напрямую. Прокси открыт только для IP стенда, с паролем,
# и пускает только на сайты из списка — это не открытый прокси.
#
# Запуск на российском VPS:   sudo STAND_IP=77.239.111.137 bash ru-proxy-setup.sh
# В конце скрипт печатает строку RU_PROXY_URL=... — её нужно вписать в .env стенда и перезапустить стенд.
set -euo pipefail

STAND_IP="${STAND_IP:?Укажите IP стенда: STAND_IP=77.239.111.137}"
PORT="${PORT:-3128}"
USER_NAME="${PROXY_USER:-radar}"
PASS="${PROXY_PASS:-$(head -c 18 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 24)}"
# Сайты, на которые прокси пускает (совпадает с RU_PROXY_HOSTS по умолчанию).
DOMAINS="${DOMAINS:-.zakupki.gov.ru .rospatent.gov.ru .cyberleninka.ru .habr.com .vc.ru .cnews.ru}"

apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq squid apache2-utils ufw >/dev/null

htpasswd -bc /etc/squid/radar.passwd "$USER_NAME" "$PASS" >/dev/null
chown proxy:proxy /etc/squid/radar.passwd 2>/dev/null || true
chmod 640 /etc/squid/radar.passwd

cat > /etc/squid/squid.conf <<EOF
# Прокси «Радара слабых сигналов»: только IP стенда, только по паролю, только сайты из списка.
http_port ${PORT}
auth_param basic program /usr/lib/squid/basic_ncsa_auth /etc/squid/radar.passwd
auth_param basic realm radar
acl stand src ${STAND_IP}
acl radar_users proxy_auth REQUIRED
acl ru_sites dstdomain ${DOMAINS}
acl SSL_ports port 443
acl Safe_ports port 80 443
acl CONNECT method CONNECT
http_access deny !Safe_ports
http_access deny CONNECT !SSL_ports
http_access allow stand radar_users ru_sites
http_access deny all
# Не раскрывать адрес стенда и не кэшировать ответы.
forwarded_for delete
via off
cache deny all
access_log /var/log/squid/access.log
EOF

systemctl restart squid
systemctl enable squid >/dev/null

ufw allow OpenSSH >/dev/null
ufw allow from "${STAND_IP}" to any port "${PORT}" proto tcp >/dev/null
ufw --force enable >/dev/null

MY_IP="$(curl -s https://yandex.ru/internet/api/v0/ip | tr -d '"' || hostname -I | awk '{print $1}')"
echo
echo "Готово. Впишите в .env стенда и перезапустите его:"
echo "RU_PROXY_URL=http://${USER_NAME}:${PASS}@${MY_IP}:${PORT}"
echo
echo "Проверка с самого стенда:  cd backend && python -m scripts.check_sources \"solid state battery\" \"твердотельный аккумулятор\""
