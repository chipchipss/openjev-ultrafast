"""Cross-check our policy.py blacklist against laya-browser-agent's RISKY_HINTS idea.

Our IRREVERSIBLE_BLACKLIST covers: pay/checkout/order, delete-account, send/post,
authorize/grant, password change. laya-browser-agent's confirmation gate (per its
README) targets 'sending, deleting, or paying' as irreversible classes, plus its
Limit section names: spend money, send messages, delete data.

Gap check against those three classes:
  spend money  -> pay now / confirm payment / buy now / checkout / place order /
                  purchase now (+CN)                    [covered]
  send         -> send message / send email / send now / post comment (+CN) [covered]
  delete       -> delete account / delete permanently / remove account (+CN)
                  ** but generic "delete" on non-account objects (files, records,
                  posts, repos) is NOT covered - only account deletion is.

Also missing vs Sac-Y/Jev-cu safety model (cited by laya-browser-agent):
  - publish/deploy actions (publishing content)
  - transfer/export data (exfiltration-shaped actions)
This script prints the comparison; it does NOT edit policy.py - adding keywords
is a judgment call for after real usage shows the need (policy.py docstring says
'add words, don't grow logic').
"""
from jev_ultrafast.policy import IRREVERSIBLE_BLACKLIST, CREDENTIAL_BLACKLIST

PROBE = {
    "spend money": ["pay now", "checkout", "place order", "buy now"],
    "send": ["send message", "send email", "post comment"],
    "delete data": ["delete account", "delete permanently"],
    # candidates we do NOT cover today (each needs real-usage evidence first):
    "publish/deploy (uncovered)": ["publish", "deploy", "go live"],
    "data transfer (uncovered)": ["export all", "download data", "transfer files"],
    "generic delete (partial)": ["delete file", "delete post", "delete repository",
                                  "删除文件", "删除记录"],
}

print("Our blacklist size:", len(IRREVERSIBLE_BLACKLIST), "+ credentials",
      len(CREDENTIAL_BLACKLIST))
for cls, kws in PROBE.items():
    missing = [k for k in kws if not any(k in b for b in IRREVERSIBLE_BLACKLIST)]
    status = "COVERED" if not missing else f"missing: {missing}"
    print(f"  {cls:<28} {status}")
print()
print("Decision: keep blacklist as-is for tonight. The three gaps are real but")
print("policy.py's own docstring requires real-usage evidence before adding words;")
print("revisit after the first week of daily MCP usage.")
