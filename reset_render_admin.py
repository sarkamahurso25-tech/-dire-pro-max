import getpass
import urllib.parse
import urllib.request
import urllib.error

url = "https://dire-pro-max.onrender.com/internal/admin-password-reset"

phone = input("Admin phone number: ").strip()
full_name = input("Admin full name: ").strip()
token = getpass.getpass("Render reset token: ")
password = getpass.getpass("New password (10+ characters): ")
confirm = getpass.getpass("Confirm password: ")

if not phone or not full_name or len(password) < 10:
    raise SystemExit("Phone ykn password sirrii miti.")

if password != confirm:
    raise SystemExit("Password wal hin simu.")

data = urllib.parse.urlencode({
    "phone": phone,
    "full_name": full_name,
    "token": token,
    "password": password
}).encode()

req = urllib.request.Request(url, data=data, method="POST")

try:
    with urllib.request.urlopen(req, timeout=90) as response:
        print(response.status, response.read().decode())
except urllib.error.HTTPError as e:
    print("HTTP ERROR:", e.code, e.read().decode())
except Exception as e:
    print("ERROR:", e)
