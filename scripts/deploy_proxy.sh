#!/bin/bash
# 公開入口 php/kbousai.php を heteml (kurage.exbridge.jp) へ FTP 配置する。
# バックエンド設定 kbousai_config.php は同じ場所に置く（リポジトリには含めない）。
# 認証情報は aixec/.env の FTP_HOST / FTP_USER / FTP_PASS。
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . /home/kojima/work/aixec/.env; set +a
BACKEND="${KBOUSAI_BACKEND_URL:-http://exbridge.ddns.net:18393}"
TMP=$(mktemp)
printf '<?php define("KBOUSAI_BACKEND", "%s");\n' "$BACKEND" > "$TMP"
curl -sS -T php/kbousai.php "ftp://${FTP_USER}:${FTP_PASS}@${FTP_HOST}/web/kurage_exbridge_jp/kbousai.php"
curl -sS -T "$TMP" "ftp://${FTP_USER}:${FTP_PASS}@${FTP_HOST}/web/kurage_exbridge_jp/kbousai_config.php"
rm -f "$TMP"
echo "deployed: https://kurage.exbridge.jp/kbousai.php/"
curl -s -o /dev/null -w "public: %{http_code}\n" "https://kurage.exbridge.jp/kbousai.php/"
