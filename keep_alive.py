from flask import Flask, render_template
from threading import Thread
import logging
import socket
import os
import sys
import time

# Disable Flask's default logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# We'll use the same lock file as the main bot script
LOCK_FILE = "bot.lock"

def is_port_in_use(port):
    """Check if a port is already in use"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

# Port for the web server (try to use different ports to avoid conflicts)
PORT = 8000
# If PORT is in use, we'll increment it until we find an available one
ORIGINAL_PORT = PORT

app = Flask(__name__)

@app.route('/')
def home():
    """Return status message to confirm the bot is running"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>JoJo Discord Bot</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                max-width: 800px;
                margin: 0 auto;
                padding: 20px;
                background-color: #1e1f22;
                color: #ffffff;
            }
            .container {
                background-color: #2b2d31;
                border-radius: 8px;
                padding: 20px;
                box-shadow: 0 4px 8px rgba(0,0,0,0.3);
            }
            h1 {
                color: #5865f2;
                text-align: center;
                margin-bottom: 30px;
            }
            .status {
                padding: 12px;
                background-color: #23a55a;
                border-radius: 4px;
                text-align: center;
                margin: 20px 0;
                font-weight: bold;
            }
            .jojo {
                font-style: italic;
                border-left: 4px solid #5865f2;
                padding: 12px;
                margin: 20px 0;
                background-color: #313338;
                border-radius: 0 4px 4px 0;
            }
            .feature-box {
                background-color: #313338;
                border-radius: 8px;
                padding: 15px;
                margin: 15px 0;
            }
            .feature-title {
                color: #5865f2;
                margin-top: 0;
                font-size: 18px;
            }
            .command {
                display: inline-block;
                background-color: #2b2d31;
                padding: 4px 8px;
                border-radius: 4px;
                margin: 3px;
                font-family: monospace;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>JoJo's Bizarre Discord Bot</h1>
            <div class="status">
                ✅ Status: ONLINE
            </div>
            <p>The bot is currently running and ready to moderate your server with the power of a Stand!</p>
            <div class="jojo">
                "You thought it was a simple webpage, but it was me, DIO!"
            </div>
            
            <div class="feature-box">
                <h2 class="feature-title">🎮 JoJo Game</h2>
                <p>Progress through all 8 parts of JoJo's Bizarre Adventure!</p>
                <div><span class="command">!jojo</span> <span class="command">!daily</span> <span class="command">!profile</span> <span class="command">!stand</span></div>
            </div>
            
            <div class="feature-box">
                <h2 class="feature-title">🛡️ Moderation</h2>
                <p>Powerful tools to keep your server safe.</p>
                <div><span class="command">!kick</span> <span class="command">!ban</span> <span class="command">!mute</span> <span class="command">!clear</span></div>
            </div>
            
            <div class="feature-box">
                <h2 class="feature-title">🎭 Fun Commands</h2>
                <p>Entertaining commands for your server!</p>
                <div><span class="command">!scan</span> <span class="command">!hello</span> <span class="command">!poll</span></div>
            </div>
            
            <p>Use this URL with Uptime Robot to keep the bot running 24/7.</p>
        </div>
    </body>
    </html>
    """

@app.route('/health')
def health():
    """Simple health check endpoint"""
    return "OK"

def run():
    """Run the Flask app"""
    global PORT
    
    # Try up to 10 different ports
    for attempt in range(10):
        try:
            if is_port_in_use(PORT):
                PORT += 1
                continue
                
            app.run(host='0.0.0.0', port=PORT)
            break
        except OSError as e:
            # Handle port already in use error
            if 'Address already in use' in str(e):
                print(f"Port {PORT} is already in use, trying port {PORT+1}...")
                PORT += 1
                # If we've tried too many ports, give up
                if PORT > ORIGINAL_PORT + 10:
                    print("Too many attempts to find an available port.")
                    print("This is likely another instance of the bot already running.")
                    print("This instance will continue to run without the web server.")
                    break
            else:
                # Propagate other OSErrors
                raise

def keep_alive():
    """Start the Flask server in a separate thread"""
    try:
        # We no longer need to check the lock file here since main.py does that
        
        # Start the web server in a separate thread
        t = Thread(target=run)
        t.daemon = True
        t.start()
        
        # Wait a moment to see if the server starts properly
        time.sleep(1)
        
        if is_port_in_use(PORT):
            print(f"Web server started on http://0.0.0.0:{PORT}")
            print("Use this URL with Uptime Robot to keep the bot running 24/7")
        else:
            print("The web server could not be started, but the bot will continue to run.")
    except Exception as e:
        print(f"Error starting web server: {e}")
        print("Bot will continue to run without the web server.")
