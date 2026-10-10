"""Server-side functional test for the self-hosted captcha (run with the venv python)."""

import re
import sys
import time
import xml.dom.minidom

sys.path.insert(0, "/var/www/schedule/backend")

from app import captcha  # noqa: E402
from app.config import get_settings  # noqa: E402

settings = get_settings()
ip = "203.0.113.9"

challenge = captcha.issue(settings, ip)
code = "".join(re.findall(r">([A-Z2-9])</text>", challenge["svg"]))
print("svg bytes      :", len(challenge["svg"]), "| token:", challenge["token"][:28] + "...")
print("抽出的答案      :", code, f"({len(code)} 位)")
xml.dom.minidom.parseString(challenge["svg"])
print("SVG 是合法 XML  : ok")
print("正确           :", captcha.verify(settings, challenge["token"], code, ip))
print("小写 + 前后空格 :", captcha.verify(settings, challenge["token"], f"  {code.lower()} ", ip))
print("错误答案       :", captcha.verify(settings, challenge["token"], "ZZZZ", ip))
print("换个 IP        :", captcha.verify(settings, challenge["token"], code, "198.51.100.7"))
print("没带 token     :", captcha.verify(settings, None, code, ip))
print("篡改 token     :", captcha.verify(settings, challenge["token"][:-4] + "abcd", code, ip))

expired = int(time.time()) - 5
parts = challenge["token"].split(".")
forged_msg = f"{captcha.VERSION}.{expired}.{parts[2]}.{parts[3]}.{code}"
forged = f"{captcha.VERSION}.{expired}.{parts[2]}.{parts[3]}.{captcha._sign(settings, forged_msg)}"
print("过期 token     :", captcha.verify(settings, forged, code, ip))

print("可读性抽样      :", re.sub(r"<[^>]+>", "", challenge["svg"])[:8] or "(纯图形)")
