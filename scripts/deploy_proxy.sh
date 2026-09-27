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
# 当社の公開先だけ simpletrack（kurage版）を差し込む。配布物の本体には入れない
cat >> "$TMP" <<'PHPEOF'
define('KBOUSAI_TRACK_JS', '<script>(function(){var s=document.createElement("script");s.src="https://kurage.exbridge.jp/simpletrack.php?url="+encodeURIComponent(location.href)+"&ref="+encodeURIComponent(document.referrer);s.async=true;document.head.appendChild(s)})();</script>');
PHPEOF
curl -sS -T php/kbousai.php "ftp://${FTP_USER}:${FTP_PASS}@${FTP_HOST}/web/kurage_exbridge_jp/kbousai.php"
curl -sS -T "$TMP" "ftp://${FTP_USER}:${FTP_PASS}@${FTP_HOST}/web/kurage_exbridge_jp/kbousai_config.php"
rm -f "$TMP"
echo "deployed: https://kurage.exbridge.jp/kbousai.php/"
curl -s -o /dev/null -w "public: %{http_code}\n" "https://kurage.exbridge.jp/kbousai.php/"
