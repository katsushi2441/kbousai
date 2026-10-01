# 行政の MCP と自社の MCP を並べて使うデモ

防災AIチャット（kbousai）の MCP と、国土交通省の公式 MCP（国土交通データプラットフォーム・MLIT-DATA-PLATFORM/mlit-dpf-mcp）を
同じ AI エージェント（Claude Code）につなぎ、「この住所は危ない？ 逃げるならどこへ？ 周りの施設・PLATEAU・交通は？」に1回で答えさせる。

- `mcp.json` … 2つの MCP サーバーの設定（kbousai は stdio・ローカルの /api を呼ぶ。mlit は公式 MCP を stdio で起動）
- 公式 MCP は `demo/mlit-dpf-mcp/`（git に入れない。clone して venv を作り、.env に MLIT_API_KEY）
- 実行: `claude -p "<質問>" --mcp-config demo/mcp.json --strict-mcp-config --allowedTools mcp__kbousai__*,mcp__mlit__* --output-format stream-json --verbose`
- 2026-10-01: 名古屋市中川区尹田町で実行。39手・約2分。kbousai が返す緯度経度を国交省側の地点検索にそのまま使う（推測させない）

クレジット: このサービスは、国土交通データプラットフォームのAPI機能を使用していますが、最新のデータを保証するものではありません。
