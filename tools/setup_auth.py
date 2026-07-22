import os
import json
import requests
import threading
import webbrowser
from dotenv import load_dotenv
from urllib.parse import urlparse, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler

load_dotenv()
CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
REDIRECT_URI = "http://localhost:8765"
SCOPES = [
    "chat:read",
    "chat:edit",
    "user:write:chat",
    "channel:moderate"
]
AUTH_CODE = None


class OAuthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global AUTH_CODE
        query = parse_qs(urlparse(self.path).query)
        if "code" in query:
            AUTH_CODE = query["code"][0]

            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"""
                <html>
                <body>
                <h1>Authorization successful!</h1>
                <p>You can close this window.</p>
                </body>
                </html>
                """
            )

        else:
            self.send_response(400)
            self.end_headers()


def start_server():
    server = HTTPServer(
        ("localhost", 8765),
        OAuthHandler
    )
    server.handle_request()


def main():
    if not CLIENT_ID or not CLIENT_SECRET:
        print("Error: Missing TWITCH_CLIENT_ID or TWITCH_CLIENT_SECRET from the .env") 
        return

    scope_string = "+".join(SCOPES)
    url = (
        "https://id.twitch.tv/oauth2/authorize?"
        f"client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        "&response_type=code"
        f"&scope={scope_string}"
    )

    print("--------------------------------")
    print("Starting Twitch OAuth") 
    print("--------------------------------")
    print(url)
    print("--------------------------------")

    threading.Thread(
        target=start_server,
        daemon=True
    ).start()
    webbrowser.open(url)

    global AUTH_CODE
    while AUTH_CODE is None:
        pass
    print("\nReceived Code.") 

    response = requests.post(
        "https://id.twitch.tv/oauth2/token",
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code": AUTH_CODE,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI
        }
    )

    token_data = response.json()
    print("\nToken response:") 
    print(json.dumps(token_data, indent=4))

    if "access_token" not in token_data:
        print("Token generation failed.") 
        return

    access_token = token_data["access_token"]
    refresh_token = token_data["refresh_token"]

    validate = requests.get(
        "https://id.twitch.tv/oauth2/validate",
        headers={
            "Authorization": f"OAuth {access_token}"
        }

    )
    user_data = validate.json()

    print("\nChecking token:") 
    print(json.dumps(user_data, indent=4))

    with open(".env", "a", encoding="utf-8") as file:
        file.write("\n")
        file.write(f"TWITCH_ACCESS_TOKEN={access_token}\n")
        file.write(f"TWITCH_REFRESH_TOKEN={refresh_token}\n")
        file.write(f"TWITCH_BOT_ID={user_data.get('user_id')}\n")
        file.write(f"TWITCH_BOT_USERNAME={user_data.get('login')}\n")
    print("\nDone! Token save to .env .") 


if __name__ == "__main__":

    main()